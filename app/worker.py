import asyncio
import logging
import signal
from contextlib import suppress

from app.config import Settings, get_settings
from app.database import Database, EvaluationRepository
from app.llm import build_llm
from app.observability import configure_logging
from app.pipeline import EvaluationPipeline, OutboxDispatcher, Worker
from app.queue import DatabaseQueue, build_queue
from app.scoring import build_scorer

log = logging.getLogger(__name__)


async def run_worker(settings: Settings) -> None:
    database = Database(settings.database_url)
    await database.create_schema()
    repository = EvaluationRepository(database)
    outbox = DatabaseQueue(database, settings.queue_visibility_seconds)
    queue = (
        outbox
        if settings.queue_backend == "database"
        else build_queue(settings, database)
    )
    pipeline = EvaluationPipeline(
        repository=repository,
        candidate=build_llm(settings, "candidate"),
        scorer=build_scorer(settings),
        lease_seconds=settings.queue_visibility_seconds,
    )
    worker = Worker(
        pipeline=pipeline,
        repository=repository,
        queue=queue,
        max_attempts=settings.queue_max_attempts,
    )
    dispatcher = (
        OutboxDispatcher(outbox=outbox, destination=queue)
        if settings.queue_backend != "database"
        else None
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, stop.set)

    log.info("worker started", extra={"queue": settings.queue_backend})
    try:
        while not stop.is_set():
            try:
                dispatched = (
                    await dispatcher.run_once() if dispatcher else False
                )
                await worker.run_once(
                    min(settings.worker_poll_seconds, 0.1)
                    if dispatched
                    else settings.worker_poll_seconds
                )
            except Exception:
                log.exception("worker iteration failed")
                await asyncio.sleep(settings.worker_poll_seconds)
    finally:
        await pipeline.close()
        await queue.close()
        if queue is not outbox:
            await outbox.close()
        await database.close()
        log.info("worker stopped")


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.environment)
    asyncio.run(run_worker(settings))


if __name__ == "__main__":
    main()
