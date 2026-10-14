"""Operación en producción: documentación apagada por defecto y registros sin secretos."""

import logging
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import errors
from psycopg_pool import PoolTimeout

from app.config import Settings, load_settings
from app.dependencies import get_current_user, get_repository
from app.domain import CurrentUser
from app.main import create_app

ORIGIN = "http://localhost:5173"
DOC_PATHS = ("/docs", "/redoc", "/openapi.json")

# Texto típico de un fallo de libpq: nombra el host y el usuario del destino.
LEAKY = (
    'connection failed: connection to server at "db.hostsecreto.example" (10.9.8.7), '
    'port 5432 failed: FATAL: password authentication failed for user "postgres.refsecreta"'
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("ENABLE_API_DOCS", raising=False)


# --- documentación de la API ------------------------------------------------


def test_api_docs_are_off_by_default():
    assert load_settings().docs_enabled is False
    client = TestClient(create_app(Settings(frontend_origins=(ORIGIN,))))

    for path in DOC_PATHS:
        assert client.get(path).status_code == 404, path
    assert client.get("/health").json() == {"ok": True}  # el resto sigue igual


@pytest.mark.parametrize("value", ["", "0", "false", "no", "nunca"])
def test_a_falsy_value_keeps_the_docs_off(monkeypatch, value):
    monkeypatch.setenv("ENABLE_API_DOCS", value)

    assert load_settings().docs_enabled is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes "])
def test_the_docs_need_an_explicit_opt_in(monkeypatch, value):
    monkeypatch.setenv("ENABLE_API_DOCS", value)
    settings = load_settings()
    client = TestClient(create_app(settings))

    assert settings.docs_enabled is True
    for path in DOC_PATHS:
        assert client.get(path).status_code == 200, path


def test_turning_the_docs_off_does_not_replace_authentication():
    """Sin documentación, las rutas de juego siguen exigiendo token."""
    app = create_app(Settings(frontend_origins=(ORIGIN,)))

    response = TestClient(app).post("/sessions", json={"mode": "random", "question_count": 1})

    assert response.status_code in (401, 503)  # nunca 2xx sin identidad


# --- registros de errores de base de datos -------------------------------------


class BrokenRepository:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def get_session(self, session_id):
        raise self._error


def failing_client(error: Exception) -> TestClient:
    app = create_app(Settings(frontend_origins=(ORIGIN,)))
    app.dependency_overrides[get_repository] = lambda: BrokenRepository(error)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=uuid4(), team_id=uuid4()
    )
    return TestClient(app)


def test_a_database_failure_logs_the_exception_name_and_sqlstate_only(caplog):
    caplog.set_level(logging.WARNING)
    client = failing_client(errors.InvalidPassword(LEAKY))

    response = client.get(f"/sessions/{uuid4()}")

    assert response.status_code == 503
    assert response.json() == {"detail": "Base de datos no disponible"}
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "InvalidPassword" in logged and "28P01" in logged
    for leak in ("hostsecreto", "10.9.8.7", "refsecreta", "password authentication"):
        assert leak not in logged


def test_a_pool_timeout_is_identified_by_its_name(caplog):
    caplog.set_level(logging.WARNING)
    client = failing_client(PoolTimeout(LEAKY))

    assert client.get(f"/sessions/{uuid4()}").status_code == 503

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "PoolTimeout" in logged
    assert "hostsecreto" not in logged


def test_the_pool_log_never_carries_the_connection_error_message(caplog):
    """El pool de psycopg registra `error connecting in ...: <mensaje completo>`."""
    create_app(Settings(frontend_origins=(ORIGIN,)))  # instala el filtro
    caplog.set_level(logging.WARNING)

    logging.getLogger("psycopg.pool").warning(
        "error connecting in %r: %s", "pool-1", psycopg.OperationalError(LEAKY)
    )

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "error connecting in 'pool-1': OperationalError" in logged
    for leak in ("hostsecreto", "10.9.8.7", "refsecreta"):
        assert leak not in logged


# --- todas las rutas de log: sin mensaje original, SQL, parámetros ni credenciales --------------

# Un error realista de PostgreSQL: SQL, valores de parámetros (DETAIL) y host en el mensaje.
LEAKY_SQL = (
    'relation "tabla_secreta" does not exist\n'
    'LINE 1: SELECT * FROM "tabla_secreta" WHERE token = \'eyJtokensecreto\'\n'
    "DETAIL: Key (clave)=(valor-secreto) conflicts; host db.hostsecreto.example"
)
LEAKS = ("tabla_secreta", "eyJtokensecreto", "valor-secreto", "hostsecreto", "refsecreta", "SELECT *")
RELEVANT_LOGGERS = (
    "psycopg", "psycopg.pool", "psycopg_pool.sched", "psycopg_pool.sched_async", "uvicorn.error",
)


@pytest.mark.parametrize("name", RELEVANT_LOGGERS)
def test_every_relevant_logger_drops_the_exception_text(caplog, name):
    create_app(Settings(frontend_origins=(ORIGIN,)))  # instala los filtros
    caplog.set_level(logging.DEBUG)
    log = logging.getLogger(name)

    try:
        raise errors.UndefinedTable(LEAKY_SQL)
    except errors.UndefinedTable:
        log.exception("falló la tarea")  # con traceback (como uvicorn o logger.exception)
    log.warning("error: %s: %s", "OperationalError", psycopg.OperationalError(LEAKY))  # como argumento

    text = caplog.text
    assert "UndefinedTable" in text and "42P01" in text  # clase y SQLSTATE sí
    assert "test_every_relevant_logger_drops_the_exception_text" in text  # la pila sí (solo código)
    assert "Traceback (most recent call last)" not in text
    for leak in LEAKS:
        assert leak not in text, leak


def test_a_non_connection_database_error_returns_500_and_logs_only_the_class(caplog):
    caplog.set_level(logging.DEBUG)
    client = failing_client(errors.UndefinedTable(LEAKY_SQL))

    response = client.get(f"/sessions/{uuid4()}")

    assert response.status_code == 500
    assert response.json() == {"detail": "Error interno"}  # tampoco al cliente
    text = caplog.text
    assert "UndefinedTable" in text
    for leak in LEAKS:
        assert leak not in text, leak
    assert "tabla_secreta" not in response.text


def test_the_log_filter_is_installed_on_every_relevant_logger():
    from app.main import SAFE_LOG_LOGGERS, SafeLogFilter

    create_app(Settings(frontend_origins=(ORIGIN,)))

    assert set(SAFE_LOG_LOGGERS) == set(RELEVANT_LOGGERS)
    for name in RELEVANT_LOGGERS:
        filters = logging.getLogger(name).filters
        assert sum(isinstance(f, SafeLogFilter) for f in filters) == 1, name  # sin duplicarse
