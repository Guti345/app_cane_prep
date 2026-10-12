"""Cuerpos de petición y respuesta de la API de juego."""

from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain import (
    MAX_QUESTIONS_PER_SESSION,
    STAGE_QUESTION_COUNT,
    Area,
    Mode,
    OptionLabel,
    SessionStatus,
    Stage,
)


class CreateSessionIn(BaseModel):
    # extra="forbid": un `user_id` u otro campo inesperado en el cuerpo da 422.
    model_config = ConfigDict(extra="forbid")

    mode: Mode
    area: Area | None = None
    stage: Stage | None = None
    question_count: int | None = Field(default=None, ge=1, le=MAX_QUESTIONS_PER_SESSION)

    @model_validator(mode="after")
    def _check_mode_fields(self) -> Self:
        if self.mode == "area":
            if self.area is None or self.stage is not None:
                raise ValueError("El modo 'area' exige area y no admite stage")
        elif self.mode == "random":
            if self.area is not None or self.stage is not None:
                raise ValueError("El modo 'random' no admite area ni stage")
        else:  # simulacro
            if self.stage is None or self.area is not None:
                raise ValueError("El modo 'simulacro' exige stage y no admite area")
            if self.question_count is not None:
                raise ValueError("En 'simulacro' el número de preguntas lo fija la fase")
        if self.mode != "simulacro" and self.question_count is None:
            raise ValueError("question_count es obligatorio salvo en 'simulacro'")
        return self

    def resolved_question_count(self) -> int:
        if self.mode == "simulacro":
            assert self.stage is not None
            return STAGE_QUESTION_COUNT[self.stage]
        assert self.question_count is not None
        return self.question_count


class SessionOut(BaseModel):
    id: UUID
    mode: Mode
    area: Area | None
    stage: Stage | None
    question_count: int
    status: SessionStatus
    answered_count: int
    current_position: int | None
    current_deadline_at: datetime | None
    server_now: datetime  # hora del servidor, para corregir el reloj del cliente


class OptionOut(BaseModel):
    label: OptionLabel
    text_md: str


class QuestionOut(BaseModel):
    """Pregunta emitida. No tiene campo de respuesta correcta."""

    position: int
    area: Area
    statement_md: str
    options: list[OptionOut]
    assets: list[dict[str, Any]]
    deadline_at: datetime
    server_now: datetime  # hora del servidor, para corregir el reloj del cliente


class AnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: int = Field(ge=1)
    # None registra el vencimiento (el cliente no respondió a tiempo).
    selected_option: OptionLabel | None = None


class AttemptOut(BaseModel):
    position: int
    selected_option: OptionLabel | None
    is_correct: bool
    timed_out: bool
    time_used_ms: int
    correct_option: OptionLabel


class RankingRowOut(BaseModel):
    """Fila del ranking del equipo. No lleva identificadores de usuario."""

    display_name: str
    rank_position: int | None  # None: aún no llega a 20 preguntas
    questions_seen: int
    correct_count: int
    accuracy_pct: float | None
    avg_time_seconds: float | None
    sessions_completed: int
    is_me: bool
