"""Repositorio en memoria SOLO para pruebas de la API.

Imita el contrato de `GameRepository` (plazo de 90 s, idempotencia, orden de
emisiÃ³n) para probar las rutas. No es la fuente de verdad de las reglas: esas
las impone PostgreSQL y se validan con `docs/prueba-migracion.sql`.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.domain import (
    Area,
    Attempt,
    InvalidOption,
    IssuedQuestion,
    Mode,
    NotEnoughQuestions,
    NothingPending,
    Option,
    OptionLabel,
    QuestionNotIssued,
    RankingRow,
    SessionClosed,
    SessionNotFound,
    SessionState,
    Stage,
)

AREAS: tuple[Area, ...] = (
    "microeconomia",
    "macroeconomia",
    "econometria",
    "historia_pensamiento",
)
DEADLINE = timedelta(seconds=90)


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc)

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@dataclass(frozen=True)
class FakeQuestion:
    id: UUID
    area: Area
    statement_md: str
    options: tuple[Option, ...]
    correct_option: OptionLabel
    assets: tuple[dict, ...] = ()


def build_pool(per_area: int = 20) -> list[FakeQuestion]:
    """Banco ficticio. Las claves son inventadas, solo para estas pruebas."""
    pool: list[FakeQuestion] = []
    for area in AREAS:
        for i in range(per_area):
            pool.append(
                FakeQuestion(
                    id=uuid4(),
                    area=area,
                    statement_md=f"Enunciado ficticio {area} {i + 1}",
                    options=(
                        Option(label="A", text_md="opciÃ³n a"),
                        Option(label="B", text_md="opciÃ³n b"),
                        Option(label="C", text_md="opciÃ³n c"),
                    ),
                    correct_option="A" if i % 2 == 0 else "B",
                )
            )
    return pool


@dataclass
class _Session:
    id: UUID
    user_id: UUID
    team_id: UUID
    mode: Mode
    area: Area | None
    stage: Stage | None
    question_count: int
    manifest: list[FakeQuestion]
    status: str = "active"
    issued: dict[int, tuple[datetime, datetime]] = field(default_factory=dict)
    attempts: dict[int, Attempt] = field(default_factory=dict)


class InMemoryGameRepository:
    def __init__(self, clock: FakeClock, pool: list[FakeQuestion]) -> None:
        self._clock = clock
        self._pool = pool
        self._sessions: dict[UUID, _Session] = {}
        self.ranking_by_team: dict[UUID, list[RankingRow]] = {}

    # --- helpers ---------------------------------------------------------
    def _get(self, session_id: UUID) -> _Session:
        s = self._sessions.get(session_id)
        if s is None:
            raise SessionNotFound()
        return s

    def _state(self, s: _Session) -> SessionState:
        current = next(
            (p for p in sorted(s.issued) if p not in s.attempts), None
        )
        return SessionState(
            id=s.id,
            user_id=s.user_id,
            team_id=s.team_id,
            mode=s.mode,
            area=s.area,
            stage=s.stage,
            question_count=s.question_count,
            status=s.status,  # type: ignore[arg-type]
            answered_count=len(s.attempts),
            current_position=current,
            current_deadline_at=s.issued[current][1] if current else None,
            server_now=self._clock.now,
        )

    # --- GameRepository --------------------------------------------------
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
        if mode == "area":
            manifest = [q for q in self._pool if q.area == area][:question_count]
        elif mode == "random":
            manifest = self._pool[:question_count]
        else:
            per_area = question_count // 4
            manifest = []
            for a in AREAS:
                manifest += [q for q in self._pool if q.area == a][:per_area]
        if len(manifest) < question_count:
            raise NotEnoughQuestions()
        s = _Session(
            id=uuid4(),
            user_id=user_id,
            team_id=team_id,
            mode=mode,
            area=area,
            stage=stage,
            question_count=question_count,
            manifest=manifest,
        )
        self._sessions[s.id] = s
        return self._state(s)

    def get_session(self, session_id: UUID) -> SessionState | None:
        s = self._sessions.get(session_id)
        return self._state(s) if s else None

    def issue_next_question(self, session_id: UUID) -> IssuedQuestion:
        s = self._get(session_id)
        if s.status != "active":
            raise SessionClosed()
        # Decisión: si la pregunta pendiente venció, `next` registra el timeout.
        for position, (_, deadline) in sorted(s.issued.items()):
            if position not in s.attempts and self._clock.now >= deadline:
                q = s.manifest[position - 1]
                s.attempts[position] = Attempt(position, None, False, True, 90000, q.correct_option)
        pending = next(
            (p for p in range(1, s.question_count + 1) if p not in s.attempts), None
        )
        if pending is None:
            s.status = "completed"
            raise NothingPending()
        if pending not in s.issued:
            now = self._clock.now
            s.issued[pending] = (now, now + DEADLINE)
        q = s.manifest[pending - 1]
        return IssuedQuestion(
            position=pending,
            area=q.area,
            statement_md=q.statement_md,
            options=q.options,
            deadline_at=s.issued[pending][1],
            server_now=self._clock.now,
            assets=q.assets,
        )

    def record_answer(
        self, session_id: UUID, position: int, selected_option: OptionLabel | None
    ) -> Attempt:
        s = self._get(session_id)
        if position in s.attempts:  # idempotente, incluso con la sesiÃ³n cerrada
            return s.attempts[position]
        if s.status != "active":
            raise SessionClosed()
        if position not in s.issued:
            raise QuestionNotIssued()
        issued_at, deadline = s.issued[position]
        q = s.manifest[position - 1]
        now = self._clock.now
        if now >= deadline:
            attempt = Attempt(position, None, False, True, 90000, q.correct_option)
        else:
            if selected_option not in {o.label for o in q.options}:
                raise InvalidOption()
            used_ms = int((now - issued_at).total_seconds() * 1000)
            attempt = Attempt(
                position,
                selected_option,
                selected_option == q.correct_option,
                False,
                used_ms,
                q.correct_option,
            )
        s.attempts[position] = attempt
        if len(s.attempts) == s.question_count:
            s.status = "completed"
        return attempt

    def abandon_session(self, session_id: UUID) -> SessionState:
        s = self._get(session_id)
        if s.status == "completed":
            raise SessionClosed()
        s.status = "abandoned"
        return self._state(s)

    def list_attempts(self, session_id: UUID) -> list[Attempt]:
        s = self._get(session_id)
        return [s.attempts[p] for p in sorted(s.attempts)]

    def ranking(self, team_id: UUID) -> list[RankingRow]:
        # El ranking real sale de la vista de PostgreSQL (prueba de integración);
        # aquí se inyecta para probar el contrato de la ruta.
        return list(self.ranking_by_team.get(team_id, []))
