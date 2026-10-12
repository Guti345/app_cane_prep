"""Tipos y contrato de acceso a datos del juego.

Las reglas de fondo (plazo de 90 s, evaluación, doble envío, orden de
emisión) las impone la base de datos (triggers de la migración). Este módulo
solo fija el contrato que usará la API; la implementación contra PostgreSQL
llega en la parte 3.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

Mode = Literal["area", "random", "simulacro"]
Area = Literal["microeconomia", "macroeconomia", "econometria", "historia_pensamiento"]
Stage = Literal["fase_1", "fase_2", "semifinal", "final"]
OptionLabel = Literal["A", "B", "C", "D", "E"]
SessionStatus = Literal["active", "completed", "abandoned"]

# Preguntas por fase de simulacro. Propuesta basada en el reglamento de 2025;
# la migración la exige con un CHECK. Faltan las reglas de 2026.
STAGE_QUESTION_COUNT: dict[Stage, int] = {
    "fase_1": 16,
    "fase_2": 12,
    "semifinal": 8,
    "final": 4,
}

# Tope provisional para sesiones de área/aleatorias. No es una regla acordada.
MAX_QUESTIONS_PER_SESSION = 50


@dataclass(frozen=True)
class Option:
    label: OptionLabel
    text_md: str


@dataclass(frozen=True)
class IssuedQuestion:
    """Lo único que el navegador recibe de una pregunta antes de responder.

    No hay campo para la clave: no puede serializarse por descuido.
    """

    position: int
    area: Area
    statement_md: str
    options: tuple[Option, ...]
    deadline_at: datetime
    # Hora del servidor (la de la base) al responder: permite al cliente
    # corregir el desfase de su reloj al mostrar la cuenta atrás.
    server_now: datetime
    assets: tuple[dict[str, Any], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Attempt:
    """Resultado final de una pregunta. Aquí sí se revela la respuesta correcta."""

    position: int
    selected_option: OptionLabel | None
    is_correct: bool
    timed_out: bool
    time_used_ms: int
    correct_option: OptionLabel


@dataclass(frozen=True)
class SessionState:
    id: UUID
    user_id: UUID
    team_id: UUID
    mode: Mode
    area: Area | None
    stage: Stage | None
    question_count: int
    status: SessionStatus
    answered_count: int
    current_position: int | None
    current_deadline_at: datetime | None
    server_now: datetime


@dataclass(frozen=True)
class RankingRow:
    """Fila de `practice_ranking`. `user_id` es interno: no se serializa."""

    user_id: UUID
    display_name: str
    rank_position: int | None  # None si tiene menos de 20 preguntas
    questions_seen: int
    correct_count: int
    accuracy_pct: float | None
    avg_time_seconds: float | None
    sessions_completed: int


@dataclass(frozen=True)
class CurrentUser:
    """Identidad ya verificada por el backend. Nunca viene del cuerpo de la petición."""

    user_id: UUID
    team_id: UUID


class GameError(Exception):
    """Base de los errores de dominio que la API traduce a HTTP."""


class SessionNotFound(GameError):
    pass


class SessionClosed(GameError):
    """La sesión ya no admite cambios (completada o abandonada)."""


class NothingPending(GameError):
    """No quedan preguntas por emitir."""


class QuestionNotIssued(GameError):
    pass


class InvalidOption(GameError):
    pass


class NotEnoughQuestions(GameError):
    pass


class GameRepository(Protocol):
    """Acceso a datos del juego. Cada método es una operación atómica."""

    def create_session(
        self,
        *,
        user_id: UUID,
        team_id: UUID,
        mode: Mode,
        area: Area | None,
        stage: Stage | None,
        question_count: int,
    ) -> SessionState:
        """Crea la sesión y su manifiesto completo. `NotEnoughQuestions` si falta banco."""

    def get_session(self, session_id: UUID) -> SessionState | None: ...

    def issue_next_question(self, session_id: UUID) -> IssuedQuestion:
        """Emite la siguiente pregunta, o devuelve la ya emitida sin responder.

        Idempotente: repetir la llamada (p. ej. al recargar) conserva el mismo
        `deadline_at`; nunca lo renueva.
        """

    def record_answer(
        self, session_id: UUID, position: int, selected_option: OptionLabel | None
    ) -> Attempt:
        """Registra la respuesta (o el vencimiento si `selected_option` es None).

        Idempotente: si ya existe un intento para la posición, lo devuelve.
        """

    def abandon_session(self, session_id: UUID) -> SessionState: ...

    def list_attempts(self, session_id: UUID) -> list[Attempt]:
        """Intentos ya cerrados de la sesión, por posición. Solo posiciones
        respondidas: la clave de una pregunta abierta nunca sale por aquí."""

    def ranking(self, team_id: UUID) -> list[RankingRow]:
        """Filas del ranking del equipo, por puesto (sin puesto al final)."""
