import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    and_,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain import (
    ComparisonScore,
    Evaluation,
    EvaluationStatus,
    JobKind,
    ModelResponse,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class EvaluationRow(Base):
    __tablename__ = "evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    prompt: Mapped[str] = mapped_column(Text)
    primary_response: Mapped[dict] = mapped_column(JSON)
    candidate_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    comparison: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    comparison_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    error_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class QueueJobRow(Base):
    __tablename__ = "queue_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))
    evaluation_id: Mapped[str] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"), index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )

    __table_args__ = (
        Index("ix_queue_jobs_available", "available_at", "locked_until"),
    )


class EvaluationNotFoundError(LookupError):
    pass


class ClaimStatus(str, Enum):
    CLAIMED = "claimed"
    BUSY = "busy"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class StageClaim:
    status: ClaimStatus
    token: str | None = None


class Database:
    def __init__(self, url: str) -> None:
        connect_args = {"timeout": 30} if url.startswith("sqlite") else {}
        self.engine: AsyncEngine = create_async_engine(
            url, pool_pre_ping=True, connect_args=connect_args
        )
        self.sessions = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def create_schema(self) -> None:
        async with self.engine.connect() as connection:
            if connection.dialect.name == "sqlite":
                await connection.exec_driver_sql("BEGIN EXCLUSIVE")
            if connection.dialect.name == "postgresql":
                await connection.begin()
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(728194621)")
                )
            try:
                await connection.run_sync(Base.metadata.create_all)
            except Exception:
                await connection.rollback()
                raise
            else:
                await connection.commit()

    async def ping(self) -> None:
        async with self.sessions() as session:
            await session.execute(select(1))

    async def close(self) -> None:
        await self.engine.dispose()


class EvaluationRepository:
    def __init__(self, database: Database) -> None:
        self._sessions = database.sessions

    async def create(self, prompt: str, primary: ModelResponse) -> Evaluation:
        now = utc_now()
        row = EvaluationRow(
            id=str(uuid.uuid4()),
            prompt=prompt,
            primary_response=primary.model_dump(mode="json"),
            status=EvaluationStatus.QUEUED.value,
            created_at=now,
            updated_at=now,
        )
        async with self._sessions() as session:
            session.add(row)
            session.add(
                QueueJobRow(
                    kind="shadow",
                    evaluation_id=row.id,
                )
            )
            await session.commit()
        return self._to_domain(row)

    async def get(self, evaluation_id: str) -> Evaluation | None:
        async with self._sessions() as session:
            row = await session.get(EvaluationRow, evaluation_id)
            return self._to_domain(row) if row else None

    async def require(self, evaluation_id: str) -> Evaluation:
        evaluation = await self.get(evaluation_id)
        if evaluation is None:
            raise EvaluationNotFoundError(evaluation_id)
        return evaluation

    async def list(self, *, limit: int, offset: int) -> list[Evaluation]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(EvaluationRow)
                    .order_by(EvaluationRow.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return [self._to_domain(row) for row in rows]

    async def claim_stage(
        self,
        evaluation_id: str,
        kind: JobKind,
        *,
        lease_seconds: int,
    ) -> StageClaim:
        expected, running = self._stage_statuses(kind)
        token = str(uuid.uuid4())
        now = utc_now()
        stale_before = now - timedelta(seconds=lease_seconds)
        async with self._sessions() as session:
            result = await session.execute(
                update(EvaluationRow)
                .where(
                    EvaluationRow.id == evaluation_id,
                    or_(
                        EvaluationRow.status == expected.value,
                        and_(
                            EvaluationRow.status == running.value,
                            EvaluationRow.updated_at <= stale_before,
                        ),
                    ),
                )
                .values(
                    status=running.value,
                    stage_token=token,
                    updated_at=now,
                )
            )
            await session.commit()
            if result.rowcount == 1:
                return StageClaim(ClaimStatus.CLAIMED, token)
            current = (
                await session.execute(
                    select(EvaluationRow.status).where(
                        EvaluationRow.id == evaluation_id
                    )
                )
            ).one_or_none()
            if current is None:
                raise EvaluationNotFoundError(evaluation_id)
            current_status = EvaluationStatus(current.status)
            if self._stage_is_busy(kind, current_status):
                return StageClaim(ClaimStatus.BUSY)
            return StageClaim(ClaimStatus.TERMINAL)

    async def save_candidate(
        self,
        evaluation_id: str,
        candidate: ModelResponse,
        *,
        token: str,
    ) -> bool:
        async with self._sessions() as session:
            result = await session.execute(
                update(EvaluationRow)
                .where(
                    EvaluationRow.id == evaluation_id,
                    EvaluationRow.status
                    == EvaluationStatus.SHADOW_RUNNING.value,
                    EvaluationRow.stage_token == token,
                )
                .values(
                    candidate_response=candidate.model_dump(mode="json"),
                    status=EvaluationStatus.SCORE_QUEUED.value,
                    stage_token=None,
                    error_stage=None,
                    error=None,
                    updated_at=utc_now(),
                )
            )
            if result.rowcount == 1:
                session.add(
                    QueueJobRow(
                        kind=JobKind.SCORE.value,
                        evaluation_id=evaluation_id,
                    )
                )
            await session.commit()
            return result.rowcount == 1

    async def save_score(
        self,
        evaluation_id: str,
        comparison: ComparisonScore,
        *,
        token: str,
    ) -> bool:
        async with self._sessions() as session:
            result = await session.execute(
                update(EvaluationRow)
                .where(
                    EvaluationRow.id == evaluation_id,
                    EvaluationRow.status == EvaluationStatus.SCORING.value,
                    EvaluationRow.stage_token == token,
                )
                .values(
                    comparison=comparison.model_dump(mode="json"),
                    comparison_score=comparison.score,
                    status=EvaluationStatus.COMPLETE.value,
                    stage_token=None,
                    error_stage=None,
                    error=None,
                    updated_at=utc_now(),
                )
            )
            await session.commit()
            return result.rowcount == 1

    async def release_stage(
        self, evaluation_id: str, kind: JobKind, *, token: str
    ) -> bool:
        expected, running = self._stage_statuses(kind)
        async with self._sessions() as session:
            result = await session.execute(
                update(EvaluationRow)
                .where(
                    EvaluationRow.id == evaluation_id,
                    EvaluationRow.status == running.value,
                    EvaluationRow.stage_token == token,
                )
                .values(
                    status=expected.value,
                    stage_token=None,
                    updated_at=utc_now(),
                )
            )
            await session.commit()
            return result.rowcount == 1

    async def fail_stage(
        self,
        evaluation_id: str,
        kind: JobKind,
        *,
        token: str,
        error: str,
    ) -> bool:
        _, running = self._stage_statuses(kind)
        async with self._sessions() as session:
            result = await session.execute(
                update(EvaluationRow)
                .where(
                    EvaluationRow.id == evaluation_id,
                    EvaluationRow.status == running.value,
                    EvaluationRow.stage_token == token,
                )
                .values(
                    status=EvaluationStatus.FAILED.value,
                    stage_token=None,
                    error_stage=kind.value,
                    error=error,
                    updated_at=utc_now(),
                )
            )
            await session.commit()
            return result.rowcount == 1

    async def stats(self) -> dict[str, int | float | None]:
        async with self._sessions() as session:
            total, completed, failed, average = (
                await session.execute(
                    select(
                        func.count(EvaluationRow.id),
                        func.count(EvaluationRow.id).filter(
                            EvaluationRow.status
                            == EvaluationStatus.COMPLETE.value
                        ),
                        func.count(EvaluationRow.id).filter(
                            EvaluationRow.status
                            == EvaluationStatus.FAILED.value
                        ),
                        func.avg(EvaluationRow.comparison_score),
                    )
                )
            ).one()
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "average_score": round(average, 2) if average is not None else None,
        }

    @staticmethod
    def _stage_statuses(
        kind: JobKind,
    ) -> tuple[EvaluationStatus, EvaluationStatus]:
        if kind == JobKind.SHADOW:
            return (
                EvaluationStatus.QUEUED,
                EvaluationStatus.SHADOW_RUNNING,
            )
        return (
            EvaluationStatus.SCORE_QUEUED,
            EvaluationStatus.SCORING,
        )

    @staticmethod
    def _stage_is_busy(
        kind: JobKind, status: EvaluationStatus
    ) -> bool:
        if kind == JobKind.SHADOW:
            return status in {
                EvaluationStatus.QUEUED,
                EvaluationStatus.SHADOW_RUNNING,
            }
        return status not in {
            EvaluationStatus.COMPLETE,
            EvaluationStatus.FAILED,
        }

    @staticmethod
    def _to_domain(row: EvaluationRow) -> Evaluation:
        return Evaluation(
            id=row.id,
            prompt=row.prompt,
            primary=ModelResponse.model_validate(row.primary_response),
            candidate=(
                ModelResponse.model_validate(row.candidate_response)
                if row.candidate_response
                else None
            ),
            comparison=(
                ComparisonScore.model_validate(row.comparison)
                if row.comparison
                else None
            ),
            status=EvaluationStatus(row.status),
            error_stage=row.error_stage,
            error=row.error,
            created_at=EvaluationRepository._with_timezone(row.created_at),
            updated_at=EvaluationRepository._with_timezone(row.updated_at),
        )

    @staticmethod
    def _with_timezone(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
