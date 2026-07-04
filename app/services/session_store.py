"""In-memory evaluation session store for the shadow-model POC.

Sessions are keyed by ``session_id`` and hold the prompt, mock response,
candidate response (once the background shadow completes), and status.
Protected by an ``asyncio.Lock`` for safe concurrent updates from multiple
background tasks. Swappable for Postgres in production.
"""

import asyncio
import uuid
from datetime import datetime, timezone

from app.core.exceptions import ResourceNotFoundError
from app.schemas.model import ModelGenerationResponse
from app.schemas.session import CandidateStatus, EvaluationSession


class SessionStore:
    """Thread-safe (async) in-memory store for evaluation sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, EvaluationSession] = {}
        self._lock = asyncio.Lock()

    async def create(self, prompt: str, mock: ModelGenerationResponse) -> str:
        """Create a session with ``candidate_status: pending`` and return its id."""
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        record = EvaluationSession(
            session_id=session_id,
            prompt=prompt,
            mock=mock,
            candidate=None,
            candidate_status=CandidateStatus.PENDING,
            error=None,
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._sessions[session_id] = record
        return session_id

    async def get(self, session_id: str) -> EvaluationSession | None:
        """Return a copy of the session, or ``None`` if unknown."""
        async with self._lock:
            record = self._sessions.get(session_id)
            return record.model_copy() if record is not None else None

    async def set_candidate(
        self,
        session_id: str,
        candidate: ModelGenerationResponse | None,
        *,
        status: CandidateStatus,
        error: str | None = None,
    ) -> None:
        """Write the shadow candidate result and update status."""
        async with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                raise ResourceNotFoundError(
                    f"Evaluation session '{session_id}' not found."
                )
            updated = record.model_copy(
                update={
                    "candidate": candidate,
                    "candidate_status": status,
                    "error": error,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self._sessions[session_id] = updated
