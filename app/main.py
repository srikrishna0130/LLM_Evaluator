import logging
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.database import (
    Database,
    EvaluationNotFoundError,
    EvaluationRepository,
)
from app.domain import (
    ComparisonScore,
    EvaluateRequest,
    EvaluateResponse,
    Evaluation,
    EvaluationStats,
)
from app.llm import LLM, build_llm
from app.observability import configure_logging

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).with_name("static")


@dataclass
class Runtime:
    settings: Settings
    database: Database
    repository: EvaluationRepository
    primary: LLM


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    configure_logging(
        active_settings.log_level, active_settings.environment
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(active_settings.database_url)
        await database.create_schema()
        app.state.runtime = Runtime(
            settings=active_settings,
            database=database,
            repository=EvaluationRepository(database),
            primary=build_llm(active_settings, "primary"),
        )
        log.info("api started")
        try:
            yield
        finally:
            await app.state.runtime.primary.close()
            await database.close()
            log.info("api stopped")

    application = FastAPI(
        title=active_settings.app_name,
        version="1.0.0",
        lifespan=lifespan,
    )
    application.mount(
        "/static",
        StaticFiles(directory=STATIC_DIR),
        name="static",
    )

    @application.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/api/v1/health")
    async def health(request: Request) -> dict[str, str]:
        try:
            await _runtime(request).database.ping()
        except Exception as exc:
            log.exception("readiness check failed")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database unavailable.",
            ) from exc
        return {"status": "ok"}

    @application.post(
        "/api/v1/evaluate",
        response_model=EvaluateResponse,
        status_code=status.HTTP_200_OK,
    )
    async def evaluate(
        body: EvaluateRequest, request: Request
    ) -> EvaluateResponse:
        runtime = _runtime(request)
        if len(body.prompt) > runtime.settings.max_prompt_chars:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    "Prompt exceeds the configured MAX_PROMPT_CHARS limit."
                ),
            )
        try:
            primary = await runtime.primary.generate(body.prompt)
        except Exception as exc:
            log.exception("primary inference failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Primary model unavailable.",
            ) from exc

        sampled = random.random() < runtime.settings.sample_rate
        evaluation_id = None
        if sampled:
            try:
                evaluation = await runtime.repository.create(
                    body.prompt, primary
                )
                evaluation_id = evaluation.id
            except Exception:
                log.exception(
                    "failed to persist sampled evaluation; "
                    "returning primary response"
                )

        return EvaluateResponse(
            response=primary.text,
            model=primary.model,
            sampled=sampled,
            evaluation_id=evaluation_id,
        )

    @application.get(
        "/api/v1/evaluations", response_model=list[Evaluation]
    )
    async def list_evaluations(
        request: Request,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[Evaluation]:
        return await _runtime(request).repository.list(
            limit=limit, offset=offset
        )

    @application.get(
        "/api/v1/evaluations/{evaluation_id}",
        response_model=Evaluation,
    )
    async def get_evaluation(
        evaluation_id: str, request: Request
    ) -> Evaluation:
        evaluation = await _runtime(request).repository.get(evaluation_id)
        if evaluation is None:
            raise HTTPException(status_code=404, detail="Evaluation not found.")
        return evaluation

    @application.get(
        "/api/v1/evaluations/{evaluation_id}/comparison",
        response_model=ComparisonScore,
    )
    async def get_comparison(
        evaluation_id: str, request: Request
    ) -> ComparisonScore:
        try:
            evaluation = await _runtime(request).repository.require(
                evaluation_id
            )
        except EvaluationNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail="Evaluation not found."
            ) from exc
        if evaluation.comparison is None:
            raise HTTPException(
                status_code=409,
                detail=f"Comparison is not ready ({evaluation.status.value}).",
            )
        return evaluation.comparison

    @application.get(
        "/api/v1/metrics", response_model=EvaluationStats
    )
    async def metrics(request: Request) -> EvaluationStats:
        values = await _runtime(request).repository.stats()
        return EvaluationStats.model_validate(values)

    return application


def _runtime(request: Request) -> Runtime:
    return request.app.state.runtime


app = create_app()
