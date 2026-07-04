"""Background shadow task: call candidate model and update the session."""

import logging

from app.schemas.session import CandidateStatus
from app.services.base import BaseModelClient
from app.services.session_store import SessionStore

log = logging.getLogger(__name__)


async def run_shadow(
    client: BaseModelClient,
    sessions: SessionStore,
    session_id: str,
    prompt: str,
) -> None:
    """Call the candidate model and persist the result on the session."""
    try:
        result = await client.generate(prompt)
        await sessions.set_candidate(session_id, result, status=CandidateStatus.OK)
        log.info(
            "shadow completed",
            extra={
                "session_id": session_id,
                "model": result.model,
                "latency_ms": result.latency_ms,
                "total_tokens": result.usage.total_tokens if result.usage else None,
            },
        )
    except Exception as exc:
        log.exception("shadow failed", extra={"session_id": session_id})
        await sessions.set_candidate(
            session_id,
            None,
            status=CandidateStatus.FAILED,
            error=str(exc),
        )
