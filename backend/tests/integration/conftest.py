"""Arnés de integración: PostgreSQL local (PGlite) con la migración REAL.

Qué es: un PostgreSQL de verdad (WASM) que corre en un proceso Node, en
memoria, solo durante la prueba. No toca Supabase ni ningún proyecto remoto.
Qué no es: Supabase. Se simulan solo sus piezas externas a la migración:
los roles `anon`, `authenticated`, `service_role` y la tabla `auth.users`.

Cada prueba corre dentro de una transacción que se revierte al terminar.
Instalación (una vez):  cd backend/tests/integration/pglite && npm install
"""

import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.postgres import PostgresGameRepository

HERE = Path(__file__).resolve().parent
PGLITE_DIR = HERE / "pglite"
SERVER = PGLITE_DIR / "node_modules" / "@electric-sql" / "pglite-socket" / "dist" / "scripts" / "server.js"
MIGRATIONS = HERE.parents[2] / "supabase" / "migrations"

AREAS = ("microeconomia", "macroeconomia", "econometria", "historia_pensamiento")
OPTIONS = [
    {"label": "A", "text_md": "opción a"},
    {"label": "B", "text_md": "opción b"},
    {"label": "C", "text_md": "opción c"},
]

SUPABASE_STUBS = """
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN;
CREATE SCHEMA auth;
CREATE TABLE auth.users (id uuid PRIMARY KEY);
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _connect(port: int, **kwargs) -> psycopg.Connection:
    return psycopg.connect(
        host="127.0.0.1",
        port=port,
        user="postgres",
        dbname="postgres",
        sslmode="disable",
        # PGlite acepta el socket antes de terminar de inicializar: el primer
        # intento puede quedarse esperando, así que se acota y se reintenta.
        connect_timeout=5,
        row_factory=dict_row,
        prepare_threshold=None,
        **kwargs,
    )


@pytest.fixture(scope="session")
def pg_server() -> Iterator[int]:
    node = shutil.which("node")
    if node is None or not SERVER.exists():
        pytest.skip(
            "PGlite no instalado: cd backend/tests/integration/pglite && npm install"
        )
    port = _free_port()
    proc = subprocess.Popen(
        [node, str(SERVER), "--db=memory://", f"--port={port}",
         "--host=127.0.0.1", "--extensions=pgcrypto"],
        cwd=PGLITE_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                _connect(port, autocommit=True).close()
                break
            except psycopg.OperationalError:
                if proc.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("El servidor PGlite no arrancó")
                time.sleep(0.5)
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def pg_conn(pg_server: int) -> Iterator[psycopg.Connection]:
    files = sorted(MIGRATIONS.glob("*_supabase_cane.sql"))
    assert len(files) == 1, f"Se esperaba una migración supabase_cane, hay {len(files)}"
    conn = _connect(pg_server, autocommit=True)
    conn.execute(SUPABASE_STUBS)
    conn.execute(files[0].read_text(encoding="utf-8"))  # la migración, sin modificar
    conn.autocommit = False
    yield conn
    conn.close()


@pytest.fixture
def db(pg_conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    # Con triggers diferidos evaluados al instante, como lo harían al confirmar.
    pg_conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
    yield pg_conn
    pg_conn.rollback()


@pytest.fixture
def repo(db: psycopg.Connection) -> PostgresGameRepository:
    @contextmanager
    def provider() -> Iterator[psycopg.Connection]:
        yield db  # la misma conexión; las transacciones del repo son savepoints

    return PostgresGameRepository(provider)


# --- datos de prueba (ficticios) ---------------------------------------------------


class Seeder:
    def __init__(self, db: psycopg.Connection) -> None:
        self.db = db
        self._n = 0

    def team(self) -> UUID:
        return self.db.execute(
            "INSERT INTO public.teams(name) VALUES ('Equipo de prueba') RETURNING id"
        ).fetchone()["id"]

    def user(self, team_id: UUID) -> UUID:
        user_id = uuid4()
        self.db.execute("INSERT INTO auth.users(id) VALUES (%s)", (user_id,))
        self.db.execute(
            "INSERT INTO public.profiles(id, team_id, display_name) VALUES (%s, %s, 'Integrante')",
            (user_id, team_id),
        )
        return user_id

    def question(
        self,
        area: str,
        *,
        source_id: str | None = None,
        revision: int = 1,
        active: bool = True,
        ready: bool = True,
        correct: str = "A",
    ) -> UUID:
        self._n += 1
        source_id = source_id or f"q{self._n}"
        qid = self.db.execute(
            "INSERT INTO public.questions "
            "(bank_id, source_id, revision, area, source_number, source_pages, statement_md, options) "
            "VALUES ('prueba', %s, %s, %s, %s, ARRAY[1], %s, %s::jsonb) RETURNING id",
            (source_id, revision, area, self._n, f"Enunciado ficticio {source_id}",
             Jsonb(OPTIONS)),
        ).fetchone()["id"]
        self.db.execute(
            "INSERT INTO public.question_keys(question_id, correct_option, verified_at) "
            "VALUES (%s, %s, now())",
            (qid, correct),
        )
        if ready:
            self.db.execute(
                "UPDATE public.questions SET review_status = 'ready', active = %s WHERE id = %s",
                (active, qid),
            )
        return qid

    def bank(self, per_area: int) -> None:
        for area in AREAS:
            for _ in range(per_area):
                self.question(area)

    def age_question(self, session_id: UUID, position: int, seconds: int) -> None:
        """Simula que pasaron `seconds` desde la emisión (adelanta emisión y plazo)."""
        self.db.execute("SET LOCAL session_replication_role = replica")
        self.db.execute(
            "UPDATE public.session_questions "
            "SET issued_at = issued_at - make_interval(secs => %s), "
            "    deadline_at = deadline_at - make_interval(secs => %s) "
            "WHERE session_id = %s AND position = %s",
            (seconds, seconds, session_id, position),
        )
        self.db.execute("SET LOCAL session_replication_role = origin")


@pytest.fixture
def seed(db: psycopg.Connection) -> Seeder:
    return Seeder(db)
