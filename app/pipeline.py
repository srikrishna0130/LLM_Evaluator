import logging
from dataclasses import dataclass

from app.database import (
    ClaimStatus,
    EvaluationNotFoundError,
    EvaluationRepository,
)
from app.domain import JobKind, QueueJob
from app.llm import LLM
from app.queue import JobQueue, ReceivedJob
from app.scoring import Scorer

log = logging.getLogger(__name__)


@dataclass
class StageExecutionError(Exception):
    job: QueueJob
    token: str
    cause: Exception

    def __str__(self) -> str:
        return str(self.cause)


class EvaluationPipeline:
    def __init__(
        self,
        *,
        repository: EvaluationRepository,
        candidate: LLM,
        scorer: Scorer,
        lease_seconds: int,
    ) -> None:
        self._repository = repository
        self._candidate = candidate
        self._scorer = scorer
        self._lease_seconds = lease_seconds

    async def process(self, job: QueueJob) -> bool:
        claim = await self._repository.claim_stage(
            job.evaluation_id,
            job.kind,
            lease_seconds=self._lease_seconds,
        )
        if claim.status == ClaimStatus.BUSY:
            return False
        if claim.status == ClaimStatus.TERMINAL:
            return True
        token = claim.token
        if token is None:
            raise RuntimeError("Claimed stage is missing its lease token.")
        try:
            if job.kind == JobKind.SHADOW:
                await self._run_shadow(job.evaluation_id, token)
            else:
                await self._run_score(job.evaluation_id, token)
        except Exception as exc:
            raise StageExecutionError(job, token, exc) from exc
        return True

    async def close(self) -> None:
        await self._candidate.close()
        await self._scorer.close()

    async def _run_shadow(self, evaluation_id: str, token: str) -> None:
        evaluation = await self._repository.require(evaluation_id)
        candidate = await self._candidate.generate(evaluation.prompt)
        saved = await self._repository.save_candidate(
            evaluation_id, candidate, token=token
        )
        if not saved:
            log.warning(
                "discarding superseded shadow result",
                extra={"evaluation_id": evaluation_id},
            )
            return
        log.info(
            "shadow completed",
            extra={"evaluation_id": evaluation_id, "model": candidate.model},
        )

    async def _run_score(self, evaluation_id: str, token: str) -> None:
        evaluation = await self._repository.require(evaluation_id)
        if evaluation.candidate is None:
            raise RuntimeError(
                f"Evaluation '{evaluation_id}' has no candidate response."
            )

        comparison = await self._scorer.score(
            evaluation.prompt,
            evaluation.primary,
            evaluation.candidate,
        )
        saved = await self._repository.save_score(
            evaluation_id, comparison, token=token
        )
        if not saved:
            log.warning(
                "discarding superseded score result",
                extra={"evaluation_id": evaluation_id},
            )
            return
        log.info(
            "scoring completed",
            extra={
                "evaluation_id": evaluation_id,
                "score": comparison.score,
                "scorer": comparison.scorer,
            },
        )


class Worker:
    def __init__(
        self,
        *,
        pipeline: EvaluationPipeline,
        repository: EvaluationRepository,
        queue: JobQueue,
        max_attempts: int,
    ) -> None:
        self._pipeline = pipeline
        self._repository = repository
        self._queue = queue
        self._max_attempts = max_attempts

    async def run_once(self, timeout: float) -> bool:
        received = await self._queue.receive(timeout)
        if received is None:
            return False
        try:
            should_ack = await self._pipeline.process(received.job)
        except EvaluationNotFoundError:
            log.error(
                "discarding job for missing evaluation",
                extra={"evaluation_id": received.job.evaluation_id},
            )
            await self._queue.ack(received)
        except StageExecutionError as exc:
            await self._handle_stage_failure(received, exc)
        except Exception as exc:
            log.exception(
                "job infrastructure failure",
                extra={"evaluation_id": received.job.evaluation_id},
            )
            await self._queue.retry(
                received, delay=min(2 ** received.attempts, 60)
            )
        else:
            if should_ack:
                await self._queue.ack(received)
            else:
                await self._queue.retry(received, delay=1)
        return True

    async def _handle_stage_failure(
        self, received: ReceivedJob, exc: StageExecutionError
    ) -> None:
        log.exception(
            "job failed",
            extra={
                "evaluation_id": received.job.evaluation_id,
                "stage": received.job.kind.value,
                "attempt": received.attempts,
            },
        )
        if received.attempts < self._max_attempts:
            released = await self._repository.release_stage(
                exc.job.evaluation_id,
                exc.job.kind,
                token=exc.token,
            )
            if released:
                await self._queue.retry(
                    received, delay=min(2 ** received.attempts, 60)
                )
            else:
                await self._queue.ack(received)
            return

        await self._repository.fail_stage(
            exc.job.evaluation_id,
            exc.job.kind,
            token=exc.token,
            error=str(exc)[:2000],
        )
        await self._queue.ack(received)


class OutboxDispatcher:
    def __init__(
        self, *, outbox: JobQueue, destination: JobQueue
    ) -> None:
        self._outbox = outbox
        self._destination = destination

    async def run_once(self) -> bool:
        received = await self._outbox.receive(timeout=0)
        if received is None:
            return False
        try:
            await self._destination.send(received.job)
        except Exception:
            log.exception(
                "outbox dispatch failed",
                extra={"evaluation_id": received.job.evaluation_id},
            )
            await self._outbox.retry(
                received, delay=min(2 ** received.attempts, 60)
            )
        else:
            await self._outbox.ack(received)
        return True
