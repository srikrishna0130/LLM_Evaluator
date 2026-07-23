import asyncio

import pytest
from sqlalchemy import func, select

from app.database import QueueJobRow
from app.domain import (
    EvaluationStatus,
    JobKind,
    ModelResponse,
    QueueJob,
)
from app.llm import MockLLM
from app.pipeline import EvaluationPipeline, Worker
from app.queue import DatabaseQueue
from app.scoring import HeuristicScorer


def _worker(test_app, candidate=None, max_attempts=3):
    runtime = test_app.state.runtime
    queue = DatabaseQueue(
        runtime.database, runtime.settings.queue_visibility_seconds
    )
    pipeline = EvaluationPipeline(
        repository=runtime.repository,
        candidate=candidate or MockLLM("candidate", "candidate-mock"),
        scorer=HeuristicScorer(),
        lease_seconds=runtime.settings.queue_visibility_seconds,
    )
    return Worker(
        pipeline=pipeline,
        repository=runtime.repository,
        queue=queue,
        max_attempts=max_attempts,
    )


@pytest.mark.asyncio
async def test_shadow_and_score_are_separate_jobs(client, test_app):
    created = await client.post(
        "/api/v1/evaluate", json={"prompt": "hello"}
    )
    evaluation_id = created.json()["evaluation_id"]
    worker = _worker(test_app)

    assert await worker.run_once(timeout=0.1) is True
    after_shadow = await test_app.state.runtime.repository.require(
        evaluation_id
    )
    assert after_shadow.status == EvaluationStatus.SCORE_QUEUED
    assert after_shadow.candidate is not None
    assert after_shadow.comparison is None

    assert await worker.run_once(timeout=0.1) is True
    complete = await test_app.state.runtime.repository.require(evaluation_id)
    assert complete.status == EvaluationStatus.COMPLETE
    assert complete.comparison is not None
    assert 0 <= complete.comparison.score <= 100

    comparison = await client.get(
        f"/api/v1/evaluations/{evaluation_id}/comparison"
    )
    metrics = await client.get("/api/v1/metrics")
    assert comparison.status_code == 200
    assert comparison.json()["scorer"] == "heuristic-v1"
    assert metrics.json()["completed"] == 1


class _FailingCandidate:
    async def generate(
        self, prompt, *, system=None, temperature=None
    ):
        raise RuntimeError("candidate unavailable")

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_exhausted_job_is_persisted_as_failed(client, test_app):
    created = await client.post(
        "/api/v1/evaluate", json={"prompt": "hello"}
    )
    evaluation_id = created.json()["evaluation_id"]
    worker = _worker(
        test_app, candidate=_FailingCandidate(), max_attempts=1
    )

    await worker.run_once(timeout=0.1)
    failed = await test_app.state.runtime.repository.require(evaluation_id)

    assert failed.status == EvaluationStatus.FAILED
    assert failed.error_stage == "shadow"
    assert failed.error == "candidate unavailable"


class _RacingCandidate:
    def __init__(self):
        self.calls = 0
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def generate(
        self, prompt, *, system=None, temperature=None
    ):
        self.calls += 1
        if self.calls == 1:
            self.first_started.set()
            await self.release_first.wait()
            text = "late result"
        else:
            text = "winning result"
        return ModelResponse(
            text=text, model="candidate", latency_ms=1
        )

    async def close(self):
        return None


class _BlockingCandidate:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(
        self, prompt, *, system=None, temperature=None
    ):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return ModelResponse(
            text="candidate", model="candidate", latency_ms=1
        )

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_busy_redelivery_keeps_recoverable_queue_job(test_app):
    runtime = test_app.state.runtime
    evaluation = await runtime.repository.create(
        "busy",
        ModelResponse(
            text="reference", model="primary", latency_ms=1
        ),
    )
    queue = DatabaseQueue(runtime.database, visibility_seconds=0)
    candidate = _BlockingCandidate()
    pipeline = EvaluationPipeline(
        repository=runtime.repository,
        candidate=candidate,
        scorer=HeuristicScorer(),
        lease_seconds=30,
    )
    first_worker = Worker(
        pipeline=pipeline,
        repository=runtime.repository,
        queue=queue,
        max_attempts=3,
    )
    second_worker = Worker(
        pipeline=pipeline,
        repository=runtime.repository,
        queue=queue,
        max_attempts=3,
    )

    active = asyncio.create_task(first_worker.run_once(timeout=0))
    await candidate.started.wait()
    await second_worker.run_once(timeout=0)
    candidate.release.set()
    await active

    stored = await runtime.repository.require(evaluation.id)
    assert candidate.calls == 1
    assert stored.status == EvaluationStatus.SCORE_QUEUED

    async with runtime.database.sessions() as session:
        shadow_jobs = await session.scalar(
            select(func.count(QueueJobRow.id)).where(
                QueueJobRow.kind == JobKind.SHADOW.value
            )
        )
        score_jobs = await session.scalar(
            select(func.count(QueueJobRow.id)).where(
                QueueJobRow.kind == JobKind.SCORE.value
            )
        )
    assert shadow_jobs == 1
    assert score_jobs == 1


@pytest.mark.asyncio
async def test_superseded_delivery_cannot_overwrite_completed_result(
    test_app,
):
    runtime = test_app.state.runtime
    evaluation = await runtime.repository.create(
        "race",
        ModelResponse(
            text="reference", model="primary", latency_ms=1
        ),
    )
    candidate = _RacingCandidate()
    pipeline = EvaluationPipeline(
        repository=runtime.repository,
        candidate=candidate,
        scorer=HeuristicScorer(),
        lease_seconds=0,
    )
    shadow = QueueJob(
        kind=JobKind.SHADOW, evaluation_id=evaluation.id
    )

    late_task = asyncio.create_task(pipeline.process(shadow))
    await candidate.first_started.wait()
    await pipeline.process(shadow)
    await pipeline.process(
        QueueJob(kind=JobKind.SCORE, evaluation_id=evaluation.id)
    )
    candidate.release_first.set()
    await late_task

    stored = await runtime.repository.require(evaluation.id)
    assert stored.status == EvaluationStatus.COMPLETE
    assert stored.candidate.text == "winning result"
    assert stored.comparison is not None

    async with runtime.database.sessions() as session:
        score_jobs = await session.scalar(
            select(func.count(QueueJobRow.id)).where(
                QueueJobRow.kind == JobKind.SCORE.value
            )
        )
    assert score_jobs == 1
