import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy import delete, or_, select, update

from app.config import Settings
from app.database import Database, QueueJobRow, utc_now
from app.domain import JobKind, QueueJob

log = logging.getLogger(__name__)


@dataclass
class ReceivedJob:
    job: QueueJob
    attempts: int
    receipt: Any


@dataclass(frozen=True)
class DatabaseReceipt:
    job_id: int
    lease_token: str


class JobQueue(Protocol):
    async def send(self, job: QueueJob) -> None: ...

    async def receive(self, timeout: float) -> ReceivedJob | None: ...

    async def ack(self, received: ReceivedJob) -> None: ...

    async def retry(self, received: ReceivedJob, delay: int) -> None: ...

    async def close(self) -> None: ...


class DatabaseQueue:
    """Durable queue and transactional outbox stored with evaluations."""

    def __init__(self, database: Database, visibility_seconds: int) -> None:
        self._sessions = database.sessions
        self._visibility_seconds = visibility_seconds

    async def send(self, job: QueueJob) -> None:
        async with self._sessions() as session:
            session.add(
                QueueJobRow(
                    kind=job.kind.value,
                    evaluation_id=job.evaluation_id,
                )
            )
            await session.commit()

    async def receive(self, timeout: float) -> ReceivedJob | None:
        deadline = time.monotonic() + timeout
        while True:
            now = utc_now()
            async with self._sessions() as session:
                async with session.begin():
                    row = await session.scalar(
                        select(QueueJobRow)
                        .where(
                            QueueJobRow.available_at <= now,
                            or_(
                                QueueJobRow.locked_until.is_(None),
                                QueueJobRow.locked_until < now,
                            ),
                        )
                        .order_by(QueueJobRow.id)
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )
                    if row is not None:
                        lease_token = str(uuid.uuid4())
                        row.attempts += 1
                        row.locked_until = now + timedelta(
                            seconds=self._visibility_seconds
                        )
                        row.lease_token = lease_token
                        received = ReceivedJob(
                            job=QueueJob(
                                kind=JobKind(row.kind),
                                evaluation_id=row.evaluation_id,
                            ),
                            attempts=row.attempts,
                            receipt=DatabaseReceipt(
                                job_id=row.id,
                                lease_token=lease_token,
                            ),
                        )
                    else:
                        received = None
            if received:
                return received
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            await asyncio.sleep(min(0.2, remaining))

    async def ack(self, received: ReceivedJob) -> None:
        receipt: DatabaseReceipt = received.receipt
        async with self._sessions() as session:
            await session.execute(
                delete(QueueJobRow).where(
                    QueueJobRow.id == receipt.job_id,
                    QueueJobRow.lease_token == receipt.lease_token,
                )
            )
            await session.commit()

    async def retry(self, received: ReceivedJob, delay: int) -> None:
        receipt: DatabaseReceipt = received.receipt
        async with self._sessions() as session:
            await session.execute(
                update(QueueJobRow)
                .where(
                    QueueJobRow.id == receipt.job_id,
                    QueueJobRow.lease_token == receipt.lease_token,
                )
                .values(
                    available_at=utc_now() + timedelta(seconds=delay),
                    locked_until=None,
                    lease_token=None,
                )
            )
            await session.commit()

    async def close(self) -> None:
        return None


class SQSQueue:
    def __init__(
        self,
        *,
        queue_url: str,
        region: str | None,
        visibility_seconds: int,
        client: Any = None,
    ) -> None:
        if not queue_url:
            raise ValueError("SQS_QUEUE_URL is required for the SQS backend.")
        if client is None:
            import boto3

            client = boto3.client("sqs", region_name=region)
        self._client = client
        self._queue_url = queue_url
        self._visibility_seconds = visibility_seconds

    async def send(self, job: QueueJob) -> None:
        await asyncio.to_thread(
            self._client.send_message,
            QueueUrl=self._queue_url,
            MessageBody=job.model_dump_json(),
        )

    async def receive(self, timeout: float) -> ReceivedJob | None:
        response = await asyncio.to_thread(
            self._client.receive_message,
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=max(0, min(int(timeout), 20)),
            VisibilityTimeout=self._visibility_seconds,
            AttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages", [])
        if not messages:
            return None
        message = messages[0]
        try:
            job = QueueJob.model_validate_json(message["Body"])
        except (ValidationError, json.JSONDecodeError):
            log.exception("Discarding malformed SQS job")
            await asyncio.to_thread(
                self._client.delete_message,
                QueueUrl=self._queue_url,
                ReceiptHandle=message["ReceiptHandle"],
            )
            return None
        return ReceivedJob(
            job=job,
            attempts=int(
                message.get("Attributes", {}).get("ApproximateReceiveCount", 1)
            ),
            receipt=message["ReceiptHandle"],
        )

    async def ack(self, received: ReceivedJob) -> None:
        await asyncio.to_thread(
            self._client.delete_message,
            QueueUrl=self._queue_url,
            ReceiptHandle=received.receipt,
        )

    async def retry(self, received: ReceivedJob, delay: int) -> None:
        await asyncio.to_thread(
            self._client.change_message_visibility,
            QueueUrl=self._queue_url,
            ReceiptHandle=received.receipt,
            VisibilityTimeout=min(delay, 43_200),
        )

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close:
            await asyncio.to_thread(close)


class AzureServiceBusQueue:
    def __init__(
        self, *, connection_string: str, queue_name: str
    ) -> None:
        if not connection_string or not queue_name:
            raise ValueError(
                "AZURE_SERVICE_BUS_CONNECTION_STRING and "
                "AZURE_SERVICE_BUS_QUEUE_NAME are required for Azure."
            )
        from azure.servicebus.aio import ServiceBusClient

        self._client = ServiceBusClient.from_connection_string(
            connection_string
        )
        self._queue_name = queue_name
        self._sender = None
        self._receiver = None
        self._started = False

    async def send(self, job: QueueJob) -> None:
        from azure.servicebus import ServiceBusMessage

        await self._ensure_started()
        await self._sender.send_messages(ServiceBusMessage(job.model_dump_json()))

    async def receive(self, timeout: float) -> ReceivedJob | None:
        await self._ensure_started()
        messages = await self._receiver.receive_messages(
            max_message_count=1,
            max_wait_time=max(timeout, 0.1),
        )
        if not messages:
            return None
        message = messages[0]
        try:
            job = QueueJob.model_validate_json(str(message))
        except (ValidationError, json.JSONDecodeError):
            log.exception("Discarding malformed Azure Service Bus job")
            await self._receiver.complete_message(message)
            return None
        return ReceivedJob(
            job=job,
            attempts=int(message.delivery_count or 0) + 1,
            receipt=message,
        )

    async def ack(self, received: ReceivedJob) -> None:
        await self._receiver.complete_message(received.receipt)

    async def retry(self, received: ReceivedJob, delay: int) -> None:
        await asyncio.sleep(delay)
        await self._receiver.abandon_message(received.receipt)

    async def close(self) -> None:
        if self._sender:
            await self._sender.__aexit__(None, None, None)
        if self._receiver:
            await self._receiver.__aexit__(None, None, None)
        if self._started:
            await self._client.__aexit__(None, None, None)

    async def _ensure_started(self) -> None:
        if self._started:
            return
        await self._client.__aenter__()
        self._sender = self._client.get_queue_sender(
            queue_name=self._queue_name
        )
        self._receiver = self._client.get_queue_receiver(
            queue_name=self._queue_name
        )
        await self._sender.__aenter__()
        await self._receiver.__aenter__()
        self._started = True


def build_queue(settings: Settings, database: Database) -> JobQueue:
    if settings.queue_backend == "database":
        return DatabaseQueue(database, settings.queue_visibility_seconds)
    if settings.queue_backend == "sqs":
        return SQSQueue(
            queue_url=settings.sqs_queue_url,
            region=settings.aws_region,
            visibility_seconds=settings.queue_visibility_seconds,
        )
    return AzureServiceBusQueue(
        connection_string=settings.azure_service_bus_connection_string,
        queue_name=settings.azure_service_bus_queue_name,
    )
