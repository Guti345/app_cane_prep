import logging
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from app.config import Settings, load_settings
from app.domain import GameRepository, SessionNotFound
from app.postgres import PostgresGameRepository, make_pool
from app.routes_game import ranking_router, router as game_router
from app.supabase_auth import AuthService, SupabaseTokenVerifier

logger = logging.getLogger("uvicorn.error")


def describe_db_error(error: BaseException) -> str:
    """Nombre de la excepción y su SQLSTATE, sin mensaje.

    El mensaje de libpq/psycopg puede incluir el host, el usuario o la base del
    destino; la clase y el SQLSTATE (código de 5 caracteres) bastan para
    distinguir credenciales, conexión o pool sin exponerlos.
    """
    name = type(error).__name__
    sqlstate = getattr(error, "sqlstate", None)
    return f"{name} (sqlstate={sqlstate})" if sqlstate else name


class SafeLogFilter(logging.Filter):
    """Quita de un registro todo texto de una excepción: queda la clase y el SQLSTATE.

    Los mensajes de psycopg/libpq pueden incluir el host, el usuario, un fragmento del SQL
    o valores de parámetros (`DETAIL: Key (...)=(...)`). Se hace en el propio registro para
    cubrir las dos formas en que llegan a los logs:

    - como argumento (`"error connecting in %r: %s", name, ex`): cada excepción se sustituye
      por su clase y SQLSTATE;
    - como traceback (`logger.exception(...)` o el que imprime uvicorn): se sustituye por
      las líneas de código de la pila (sin mensaje ni valores de variables).

    Un filtro de logger solo actúa sobre los registros que emite ese logger, no los de sus
    hijos: por eso se instala en cada logger relevante (`SAFE_LOG_LOGGERS`).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                describe_db_error(a) if isinstance(a, BaseException) else a
                for a in record.args
            )
        error = record.exc_info[1] if record.exc_info else None
        if error is not None:
            frames = "".join(traceback.format_tb(record.exc_info[2]))  # type: ignore[index]
            record.msg = f"{record.getMessage()} [{describe_db_error(error)}]\n{frames}".rstrip()
            record.args = None
            record.exc_info = None
            record.exc_text = None
        return True


# Loggers por los que psycopg, su pool y uvicorn pueden escribir texto de una excepción.
SAFE_LOG_LOGGERS = (
    "psycopg",
    "psycopg.pool",
    "psycopg_pool.sched",
    "psycopg_pool.sched_async",
    "uvicorn.error",
)


def _quiet_pool_logs() -> None:
    for name in SAFE_LOG_LOGGERS:
        target = logging.getLogger(name)
        if not any(isinstance(f, SafeLogFilter) for f in target.filters):
            target.addFilter(SafeLogFilter())


def create_app(
    settings: Settings | None = None,
    *,
    auth: AuthService | None = None,
    repository: GameRepository | None = None,
) -> FastAPI:
    """Construye la aplicación.

    Sin `DATABASE_URL` (o sin variables de Supabase) las rutas de juego
    responden 503. Nada se conecta al importar ni al crear la app: el pool de
    conexiones solo se abre cuando la aplicación arranca.
    """
    settings = settings or load_settings()
    _quiet_pool_logs()

    pool = None
    if repository is None and settings.database_url:
        pool = make_pool(settings.database_url)
        postgres = PostgresGameRepository(pool.connection)
        repository = postgres
        if auth is None and settings.supabase_url and settings.supabase_publishable_key:
            auth = AuthService(
                SupabaseTokenVerifier(
                    settings.supabase_url, settings.supabase_publishable_key
                ),
                postgres,
            )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if pool is not None:
            pool.open(wait=False)  # no bloquea ni falla si la base no responde
        yield
        if pool is not None:
            pool.close()

    app = FastAPI(
        title="CANE Prep API",
        lifespan=lifespan,
        # Sin documentación pública salvo opt-in explícito (ENABLE_API_DOCS).
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.auth = auth
    app.state.repository = repository

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.frontend_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(PoolTimeout)
    async def database_unavailable(_: Request, error: Exception) -> JSONResponse:
        logger.warning("Base de datos no disponible: %s", describe_db_error(error))
        return JSONResponse(
            status_code=503, content={"detail": "Base de datos no disponible"}
        )

    @app.exception_handler(psycopg.Error)
    async def database_error(_: Request, error: Exception) -> JSONResponse:
        # Cualquier otro error de psycopg (SQL, datos, integridad): un fallo del servidor.
        # Sin esta rama, uvicorn imprimiría el traceback con el mensaje completo.
        logger.error("Error de base de datos: %s", describe_db_error(error))
        return JSONResponse(status_code=500, content={"detail": "Error interno"})

    @app.exception_handler(SessionNotFound)
    async def session_not_found(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Sesión no encontrada"})

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(game_router)
    app.include_router(ranking_router)

    return app


app = create_app()
