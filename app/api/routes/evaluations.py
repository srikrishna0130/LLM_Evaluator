import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.core.exceptions import ResourceNotFoundError
from app.schemas.evaluation import (
    EvaluateRequest,
    EvaluateResponse,
    EvaluationComparison,
)
from app.schemas.session import CandidateStatus, EvaluationSession
from app.services.comparison import build_comparison
from app.services.shadow import run_shadow

router = APIRouter()
log = logging.getLogger(__name__)


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate(
    body: EvaluateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> EvaluateResponse:
    """Return mock response immediately; run candidate model in background."""
    mock = await request.app.state.mock_model.generate(body.prompt)
    session_id = await request.app.state.sessions.create(body.prompt, mock)
    background_tasks.add_task(
        run_shadow,
        request.app.state.candidate_model,
        request.app.state.sessions,
        session_id,
        body.prompt,
    )
    log.info("evaluate accepted", extra={"session_id": session_id})
    return EvaluateResponse(session_id=session_id, response=mock.text)


@router.get("/evaluations", response_model=list[EvaluationSession])
async def list_evaluations(request: Request) -> list[EvaluationSession]:
    """List all stored evaluation sessions (newest first)."""
    return await request.app.state.sessions.list_all()


@router.get("/evaluations/{session_id}", response_model=EvaluationSession)
async def get_evaluation(session_id: str, request: Request) -> EvaluationSession:
    """Return a single evaluation session by id."""
    session = await request.app.state.sessions.get(session_id)
    if session is None:
        raise ResourceNotFoundError(
            f"Evaluation session '{session_id}' not found."
        )
    return session


@router.get(
    "/evaluations/{session_id}/comparison",
    response_model=EvaluationComparison,
)
async def get_evaluation_comparison(
    session_id: str,
    request: Request,
) -> EvaluationComparison:
    """Return mock-vs-candidate comparison for a finished session."""
    session = await request.app.state.sessions.get(session_id)
    if session is None:
        raise ResourceNotFoundError(
            f"Evaluation session '{session_id}' not found."
        )
    if session.candidate_status != CandidateStatus.OK:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Conflict",
                "message": (
                    f"Comparison not available while candidate_status is "
                    f"'{session.candidate_status.value}'."
                ),
                "candidate_status": session.candidate_status.value,
            },
        )
    return build_comparison(session)
