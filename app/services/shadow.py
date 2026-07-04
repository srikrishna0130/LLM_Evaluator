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
    session = await sessions.get(session_id)
    mock = session.mock if session is not None else None

    try:
        result = await client.generate(prompt)
        await sessions.set_candidate(session_id, result, status=CandidateStatus.OK)

        usage = result.usage
        log.info(
            "shadow completed session_id=%s model=%s latency_ms=%s "
            "prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            session_id,
            result.model,
            result.latency_ms,
            usage.prompt_tokens if usage else None,
            usage.completion_tokens if usage else None,
            usage.total_tokens if usage else None,
        )

        if mock is not None and result.text != mock.text:
            log.warning(
                "shadow output mismatch session_id=%s mock_json=%s candidate_json=%s",
                session_id,
                mock.model_dump_json(),
                result.model_dump_json(),
            )
    except Exception as exc:
        log.exception(
            "shadow failed session_id=%s error=%s",
            session_id,
            exc,
        )
        await sessions.set_candidate(
            session_id,
            None,
            status=CandidateStatus.FAILED,
            error=str(exc),
        )
