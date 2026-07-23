import asyncio

import pytest

from app.database import Database, EvaluationRepository
from app.domain import JobKind, ModelResponse, QueueJob
from app.pipeline import OutboxDispatcher
from app.queue import DatabaseQueue, SQSQueue


@pytest.mark.asyncio
async def test_database_queue_ack_and_retry(settings):
    database = Database(settings.database_url)
    await database.create_schema()
    repository = EvaluationRepository(database)
    evaluation = await repository.create(
        "hello",
        ModelResponse(text="primary", model="p", latency_ms=1),
    )
    queue = DatabaseQueue(database, visibility_seconds=10)
    job = QueueJob(
        kind=JobKind.SHADOW, evaluation_id=evaluation.id
    )

    first = await queue.receive(timeout=0)
    assert first is not None
    assert first.job == job
    assert first.attempts == 1

    await queue.retry(first, delay=0)
    second = await queue.receive(timeout=0)
    assert second is not None
    assert second.attempts == 2

    await queue.ack(first)
    await queue.retry(second, delay=0)
    third = await queue.receive(timeout=0)
    assert third is not None
    assert third.attempts == 3

    await queue.ack(third)
    assert await queue.receive(timeout=0) is None
    await database.close()


@pytest.mark.asyncio
async def test_concurrent_sqlite_schema_initialization(settings):
    databases = [Database(settings.database_url) for _ in range(5)]

    await asyncio.gather(
        *(database.create_schema() for database in databases)
    )

    await asyncio.gather(*(database.close() for database in databases))


class _DestinationQueue:
    def __init__(self):
        self.jobs = []

    async def send(self, job):
        self.jobs.append(job)


@pytest.mark.asyncio
async def test_outbox_dispatches_to_external_transport(settings):
    database = Database(settings.database_url)
    await database.create_schema()
    repository = EvaluationRepository(database)
    evaluation = await repository.create(
        "hello",
        ModelResponse(text="primary", model="p", latency_ms=1),
    )
    outbox = DatabaseQueue(database, visibility_seconds=10)
    destination = _DestinationQueue()
    dispatcher = OutboxDispatcher(
        outbox=outbox, destination=destination
    )

    assert await dispatcher.run_once() is True
    assert destination.jobs == [
        QueueJob(
            kind=JobKind.SHADOW, evaluation_id=evaluation.id
        )
    ]
    assert await outbox.receive(timeout=0) is None
    await database.close()


class _FakeSQSClient:
    def __init__(self):
        self.sent = None
        self.deleted = None
        self.visibility = None

    def send_message(self, **kwargs):
        self.sent = kwargs

    def receive_message(self, **kwargs):
        return {
            "Messages": [
                {
                    "Body": (
                        '{"kind":"shadow","evaluation_id":"evaluation-1"}'
                    ),
                    "ReceiptHandle": "receipt-1",
                    "Attributes": {"ApproximateReceiveCount": "2"},
                }
            ]
        }

    def delete_message(self, **kwargs):
        self.deleted = kwargs

    def change_message_visibility(self, **kwargs):
        self.visibility = kwargs


@pytest.mark.asyncio
async def test_sqs_adapter_uses_native_ack_and_retry():
    client = _FakeSQSClient()
    queue = SQSQueue(
        queue_url="https://sqs.example/queue",
        region="us-east-1",
        visibility_seconds=60,
        client=client,
    )
    job = QueueJob(
        kind=JobKind.SHADOW, evaluation_id="evaluation-1"
    )

    await queue.send(job)
    received = await queue.receive(timeout=1)
    assert received is not None
    assert received.job == job
    assert received.attempts == 2

    await queue.retry(received, delay=4)
    assert client.visibility["VisibilityTimeout"] == 4
    await queue.ack(received)
    assert client.deleted["ReceiptHandle"] == "receipt-1"
