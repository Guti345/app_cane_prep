"""Repositorio del juego contra PostgreSQL (esquema de la migración inicial).

Reglas de diseño:
- Una conexión PostgreSQL directa y transacciones; nada de llamadas REST.
- El tiempo lo decide la base: `clock_timestamp()`, nunca el reloj de Python.
- Los triggers de la migración son la fuente de verdad (plazo de 90 s,
  evaluación, doble envío, orden de emisión). Aquí solo se orquesta.
- Nunca `SELECT *` sobre preguntas ni claves: cada consulta nombra sus columnas.
- Cada operación bloquea la fila de la sesión (`FOR UPDATE`), así que dos
  peticiones sobre la misma sesión se serializan.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

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
    SessionClosed,
    SessionNotFound,
    SessionState,
    Stage,
)

ConnectionProvider = Callable[[], AbstractContextManager[psycopg.Connection[Any]]]

POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 5
POOL_TIMEOUT_SECONDS = 10.0
AREAS: tuple[Area, ...] = (
    "microeconomia",
    "macroeconomia",
    "econometria",
    "historia_pensamiento",
)

# Última revisión activa y lista de cada pregunta fuente.
_LATEST_ACTIVE = """
    SELECT DISTINCT ON (q.bank_id, q.source_id) q.id, q.area
    FROM public.questions q
    WHERE q.active AND q.review_status = 'ready'
    ORDER BY q.bank_id, q.source_id, q.revision DESC
"""

_NOT_ANSWERED = """
    NOT EXISTS (SELECT 1 FROM public.attempts a
                WHERE a.session_id = sq.session_id AND a.position = sq.position)
"""

_STATE_SQL = f"""
    SELECT s.id, s.user_id, s.team_id, s.mode, s.area_filter, s.stage,
           s.question_count, s.status,
           (SELECT count(*) FROM public.attempts a WHERE a.session_id = s.id) AS answered_count,
           cur.position AS current_position,
           cur.deadline_at AS current_deadline_at
    FROM public.sessions s
    LEFT JOIN LATERAL (
        SELECT sq.position, sq.deadline_at
        FROM public.session_questions sq
        WHERE sq.session_id = s.id AND sq.issued_at IS NOT NULL AND {_NOT_ANSWERED}
        ORDER BY sq.position
        LIMIT 1
    ) cur ON true
    WHERE s.id = %s
"""

_ATTEMPT_SQL = """
    SELECT a.position, a.selected_option, a.is_correct, a.timed_out,
           a.time_used_ms, k.correct_option
    FROM public.attempts a
    JOIN public.session_questions sq
      ON sq.session_id = a.session_id AND sq.position = a.position
    JOIN public.question_keys k ON k.question_id = sq.question_id
    WHERE a.session_id = %s AND a.position = %s
"""

_FINISHED = object()


def make_pool(database_url: str) -> ConnectionPool:
    """Pool sin abrir: no se conecta hasta que la aplicación arranca."""
    params = conninfo_to_dict(database_url)
    params.setdefault("sslmode", "require")
    return ConnectionPool(
        conninfo=make_conninfo(**params),
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        timeout=POOL_TIMEOUT_SECONDS,
        # Sin sentencias preparadas: compatible con el pooler en modo transacción.
        kwargs={"row_factory": dict_row, "prepare_threshold": None},
        open=False,
    )


class PostgresGameRepository:
    def __init__(self, connection: ConnectionProvider) -> None:
        self._connection = connection

    @contextmanager
    def _tx(self) -> Iterator[psycopg.Connection[Any]]:
        with self._connection() as conn:
            with conn.transaction():
                yield conn

    # --- perfiles --------------------------------------------------------
    def team_id_for_user(self, user_id: UUID) -> UUID | None:
        with self._tx() as conn:
            row = conn.execute(
                "SELECT team_id FROM public.profiles WHERE id = %s", (user_id,)
            ).fetchone()
        return row["team_id"] if row else None

    # --- sesiones --------------------------------------------------------
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
        with self._tx() as conn:
            if mode == "area":
                rows = conn.execute(
                    f"WITH latest AS ({_LATEST_ACTIVE}) "
                    "SELECT id FROM latest WHERE area = %s ORDER BY random() LIMIT %s",
                    (area, question_count),
                ).fetchall()
            elif mode == "random":
                rows = conn.execute(
                    f"WITH latest AS ({_LATEST_ACTIVE}) "
                    "SELECT id FROM latest ORDER BY random() LIMIT %s",
                    (question_count,),
                ).fetchall()
            else:  # simulacro: mismo cupo en las cuatro áreas
                rows = conn.execute(
                    f"WITH latest AS ({_LATEST_ACTIVE}), numbered AS ("
                    "  SELECT id, row_number() OVER (PARTITION BY area ORDER BY random()) AS rn"
                    "  FROM latest) "
                    "SELECT id FROM numbered WHERE rn <= %s ORDER BY random()",
                    (question_count // len(AREAS),),
                ).fetchall()
            if len(rows) < question_count:
                raise NotEnoughQuestions()

            created = conn.execute(
                "INSERT INTO public.sessions "
                "(user_id, team_id, mode, area_filter, stage, question_count) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (user_id, team_id, mode, area, stage, question_count),
            ).fetchone()
            assert created is not None
            session_id = created["id"]
            for position, row in enumerate(rows, start=1):
                conn.execute(
                    "INSERT INTO public.session_questions (session_id, position, question_id) "
                    "VALUES (%s, %s, %s)",
                    (session_id, position, row["id"]),
                )
            return self._read_state(conn, session_id)

    def get_session(self, session_id: UUID) -> SessionState | None:
        with self._tx() as conn:
            try:
                return self._read_state(conn, session_id)
            except SessionNotFound:
                return None

    def abandon_session(self, session_id: UUID) -> SessionState:
        with self._tx() as conn:
            status = self._lock(conn, session_id)
            if status == "completed":
                raise SessionClosed()
            if status == "active":
                conn.execute(
                    "UPDATE public.sessions SET status = 'abandoned' WHERE id = %s",
                    (session_id,),
                )
            return self._read_state(conn, session_id)

    # --- preguntas -------------------------------------------------------
    def issue_next_question(self, session_id: UUID) -> IssuedQuestion:
        with self._tx() as conn:
            result = self._issue(conn, session_id)
        # NothingPending se lanza fuera de la transacción: los timeouts
        # registrados y el cierre de la sesión deben confirmarse.
        if result is _FINISHED:
            raise NothingPending()
        assert isinstance(result, IssuedQuestion)
        return result

    def _issue(self, conn: psycopg.Connection[Any], session_id: UUID) -> object:
        status = self._lock(conn, session_id)
        if status != "active":
            raise SessionClosed()

        while True:
            current = conn.execute(
                "SELECT sq.position, sq.question_id, sq.deadline_at, "
                "       (clock_timestamp() >= sq.deadline_at) AS expired "
                "FROM public.session_questions sq "
                f"WHERE sq.session_id = %s AND sq.issued_at IS NOT NULL AND {_NOT_ANSWERED} "
                "ORDER BY sq.position LIMIT 1",
                (session_id,),
            ).fetchone()
            if current is None:
                break
            if not current["expired"]:
                # Recargar no renueva el plazo: se devuelve el mismo deadline.
                return self._question(conn, current)
            # Venció sin respuesta: se registra el timeout (el trigger lo evalúa).
            conn.execute(
                "INSERT INTO public.attempts (session_id, position, selected_option) "
                "VALUES (%s, %s, NULL)",
                (session_id, current["position"]),
            )

        nxt = conn.execute(
            "SELECT sq.position, sq.question_id "
            "FROM public.session_questions sq "
            f"WHERE sq.session_id = %s AND {_NOT_ANSWERED} "
            "ORDER BY sq.position LIMIT 1",
            (session_id,),
        ).fetchone()
        if nxt is None:
            conn.execute(
                "UPDATE public.sessions SET status = 'completed' WHERE id = %s",
                (session_id,),
            )
            return _FINISHED

        # Un único clock_timestamp(): issued_at y deadline_at salen del mismo instante.
        issued = conn.execute(
            "UPDATE public.session_questions "
            "SET issued_at = t.t, deadline_at = t.t + interval '90 seconds' "
            "FROM (SELECT clock_timestamp() AS t) t "
            "WHERE session_id = %s AND position = %s AND issued_at IS NULL "
            "RETURNING position, question_id, deadline_at",
            (session_id, nxt["position"]),
        ).fetchone()
        assert issued is not None
        return self._question(conn, issued)

    @staticmethod
    def _question(conn: psycopg.Connection[Any], row: dict[str, Any]) -> IssuedQuestion:
        # Columnas explícitas: la clave vive en otra tabla y no se consulta aquí.
        q = conn.execute(
            "SELECT area, statement_md, options, assets "
            "FROM public.questions WHERE id = %s",
            (row["question_id"],),
        ).fetchone()
        assert q is not None
        return IssuedQuestion(
            position=row["position"],
            area=q["area"],
            statement_md=q["statement_md"],
            options=tuple(Option(label=o["label"], text_md=o["text_md"]) for o in q["options"]),
            deadline_at=row["deadline_at"],
            assets=tuple(q["assets"]),
        )

    # --- respuestas ------------------------------------------------------
    def record_answer(
        self, session_id: UUID, position: int, selected_option: OptionLabel | None
    ) -> Attempt:
        try:
            return self._record(session_id, position, selected_option)
        except errors.UniqueViolation:
            # Carrera improbable (la sesión está bloqueada): se devuelve el guardado.
            with self._tx() as conn:
                existing = self._attempt(conn, session_id, position)
            if existing is None:
                raise
            return existing

    def _record(
        self, session_id: UUID, position: int, selected_option: OptionLabel | None
    ) -> Attempt:
        with self._tx() as conn:
            status = self._lock(conn, session_id)

            existing = self._attempt(conn, session_id, position)
            if existing is not None:  # idempotente, incluso con la sesión cerrada
                return existing
            if status != "active":
                raise SessionClosed()

            sq = conn.execute(
                "SELECT sq.question_id, sq.issued_at, "
                "       (clock_timestamp() >= sq.deadline_at) AS expired "
                "FROM public.session_questions sq "
                "WHERE sq.session_id = %s AND sq.position = %s",
                (session_id, position),
            ).fetchone()
            if sq is None or sq["issued_at"] is None:
                raise QuestionNotIssued()

            option = selected_option
            if sq["expired"]:
                option = None  # el trigger lo registra como timeout
            else:
                row = conn.execute(
                    "SELECT options FROM public.questions WHERE id = %s",
                    (sq["question_id"],),
                ).fetchone()
                assert row is not None
                labels = {o["label"] for o in row["options"]}
                if option is None or option not in labels:
                    raise InvalidOption()

            conn.execute(
                "INSERT INTO public.attempts (session_id, position, selected_option) "
                "VALUES (%s, %s, %s)",
                (session_id, position, option),
            )

            pending = conn.execute(
                "SELECT count(*) AS n FROM public.session_questions sq "
                f"WHERE sq.session_id = %s AND {_NOT_ANSWERED}",
                (session_id,),
            ).fetchone()
            assert pending is not None
            if pending["n"] == 0:
                conn.execute(
                    "UPDATE public.sessions SET status = 'completed' WHERE id = %s",
                    (session_id,),
                )

            attempt = self._attempt(conn, session_id, position)
            assert attempt is not None
            return attempt

    # --- helpers ---------------------------------------------------------
    @staticmethod
    def _lock(conn: psycopg.Connection[Any], session_id: UUID) -> str:
        row = conn.execute(
            "SELECT status FROM public.sessions WHERE id = %s FOR UPDATE",
            (session_id,),
        ).fetchone()
        if row is None:
            raise SessionNotFound()
        return row["status"]

    @staticmethod
    def _attempt(
        conn: psycopg.Connection[Any], session_id: UUID, position: int
    ) -> Attempt | None:
        row = conn.execute(_ATTEMPT_SQL, (session_id, position)).fetchone()
        if row is None:
            return None
        return Attempt(
            position=row["position"],
            selected_option=row["selected_option"],
            is_correct=row["is_correct"],
            timed_out=row["timed_out"],
            time_used_ms=row["time_used_ms"],
            correct_option=row["correct_option"],
        )

    @staticmethod
    def _read_state(conn: psycopg.Connection[Any], session_id: UUID) -> SessionState:
        row = conn.execute(_STATE_SQL, (session_id,)).fetchone()
        if row is None:
            raise SessionNotFound()
        return SessionState(
            id=row["id"],
            user_id=row["user_id"],
            team_id=row["team_id"],
            mode=row["mode"],
            area=row["area_filter"],
            stage=row["stage"],
            question_count=row["question_count"],
            status=row["status"],
            answered_count=row["answered_count"],
            current_position=row["current_position"],
            current_deadline_at=row["current_deadline_at"],
        )
