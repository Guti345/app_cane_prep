"""Endpoints de sesiones, preguntas y respuestas (esqueleto).

Reglas de este módulo:
- La identidad sale de `get_current_user`, nunca del cuerpo ni de la URL.
- Una sesión ajena se trata como inexistente (404): no revela que existe.
- La API no calcula tiempos ni evalúa respuestas: eso lo hace el repositorio
  (en producción, los triggers de PostgreSQL con su reloj).
- Ninguna ruta de pregunta devuelve la respuesta correcta antes de responder.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_current_user, get_repository
from app.domain import (
    Attempt,
    CurrentUser,
    GameRepository,
    InvalidOption,
    NotEnoughQuestions,
    NothingPending,
    QuestionNotIssued,
    SessionClosed,
    SessionNotFound,
    SessionState,
)
from app.schemas import (
    AnswerIn,
    AttemptOut,
    CreateSessionIn,
    OptionOut,
    QuestionOut,
    RankingRowOut,
    SessionOut,
)

router = APIRouter(prefix="/sessions", tags=["juego"])


def _owned_session(
    repo: GameRepository, session_id: UUID, user: CurrentUser
) -> SessionState:
    session = repo.get_session(session_id)
    if session is None or session.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return session


def _session_out(s: SessionState) -> SessionOut:
    return SessionOut(
        id=s.id,
        mode=s.mode,
        area=s.area,
        stage=s.stage,
        question_count=s.question_count,
        status=s.status,
        answered_count=s.answered_count,
        current_position=s.current_position,
        current_deadline_at=s.current_deadline_at,
        server_now=s.server_now,
    )


def _attempt_out(a: Attempt) -> AttemptOut:
    return AttemptOut(
        position=a.position,
        selected_option=a.selected_option,
        is_correct=a.is_correct,
        timed_out=a.timed_out,
        time_used_ms=a.time_used_ms,
        correct_option=a.correct_option,
    )


@router.post("", status_code=201, response_model=SessionOut)
def create_session(
    body: CreateSessionIn,
    user: CurrentUser = Depends(get_current_user),
    repo: GameRepository = Depends(get_repository),
) -> SessionOut:
    try:
        session = repo.create_session(
            user_id=user.user_id,
            team_id=user.team_id,
            mode=body.mode,
            area=body.area,
            stage=body.stage,
            question_count=body.resolved_question_count(),
        )
    except NotEnoughQuestions:
        raise HTTPException(
            status_code=409, detail="No hay suficientes preguntas disponibles"
        ) from None
    return _session_out(session)


@router.get("/{session_id}", response_model=SessionOut)
def get_session(
    session_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    repo: GameRepository = Depends(get_repository),
) -> SessionOut:
    return _session_out(_owned_session(repo, session_id, user))


@router.post("/{session_id}/next", response_model=QuestionOut)
def next_question(
    session_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    repo: GameRepository = Depends(get_repository),
) -> QuestionOut:
    """Emite la siguiente pregunta; si ya hay una sin responder, la repite
    con el mismo plazo (recargar no reinicia el cronómetro).

    Si la pregunta pendiente ya venció, registra su timeout y emite la
    siguiente. Si era la última, cierra la sesión y responde 409.
    """
    _owned_session(repo, session_id, user)
    try:
        q = repo.issue_next_question(session_id)
    except SessionClosed:
        raise HTTPException(status_code=409, detail="La sesión ya no está activa") from None
    except NothingPending:
        raise HTTPException(status_code=409, detail="No quedan preguntas pendientes") from None
    return QuestionOut(
        position=q.position,
        area=q.area,
        statement_md=q.statement_md,
        options=[OptionOut(label=o.label, text_md=o.text_md) for o in q.options],
        assets=list(q.assets),
        deadline_at=q.deadline_at,
        server_now=q.server_now,
    )


@router.post("/{session_id}/answer", response_model=AttemptOut)
def answer(
    session_id: UUID,
    body: AnswerIn,
    user: CurrentUser = Depends(get_current_user),
    repo: GameRepository = Depends(get_repository),
) -> AttemptOut:
    """Registra la respuesta. Reenviar la misma posición devuelve el intento
    ya guardado, sin reemplazarlo."""
    _owned_session(repo, session_id, user)
    try:
        a = repo.record_answer(session_id, body.position, body.selected_option)
    except SessionClosed:
        raise HTTPException(status_code=409, detail="La sesión ya no está activa") from None
    except QuestionNotIssued:
        raise HTTPException(status_code=409, detail="La pregunta no ha sido emitida") from None
    except InvalidOption:
        raise HTTPException(status_code=422, detail="Opción inválida para la pregunta") from None
    return _attempt_out(a)


@router.get("/{session_id}/attempts", response_model=list[AttemptOut])
def attempts(
    session_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    repo: GameRepository = Depends(get_repository),
) -> list[AttemptOut]:
    """Intentos ya cerrados de la sesión (con su clave). Solo posiciones
    respondidas: la pregunta pendiente no aparece."""
    _owned_session(repo, session_id, user)
    return [_attempt_out(a) for a in repo.list_attempts(session_id)]


@router.post("/{session_id}/abandon", response_model=SessionOut)
def abandon(
    session_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    repo: GameRepository = Depends(get_repository),
) -> SessionOut:
    _owned_session(repo, session_id, user)
    try:
        session = repo.abandon_session(session_id)
    except SessionClosed:
        raise HTTPException(status_code=409, detail="La sesión ya está completada") from None
    return _session_out(session)


ranking_router = APIRouter(tags=["juego"])


@ranking_router.get("/ranking", response_model=list[RankingRowOut])
def ranking(
    user: CurrentUser = Depends(get_current_user),
    repo: GameRepository = Depends(get_repository),
) -> list[RankingRowOut]:
    """Ranking del equipo del usuario verificado. El equipo no es un
    parámetro: sale de la identidad, así que no se puede pedir el de otro."""
    return [
        RankingRowOut(
            display_name=r.display_name,
            rank_position=r.rank_position,
            questions_seen=r.questions_seen,
            correct_count=r.correct_count,
            accuracy_pct=r.accuracy_pct,
            avg_time_seconds=r.avg_time_seconds,
            sessions_completed=r.sessions_completed,
            is_me=r.user_id == user.user_id,
        )
        for r in repo.ranking(user.team_id)
    ]


__all__ = ["router", "ranking_router"]
