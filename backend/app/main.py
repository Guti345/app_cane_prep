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

    app = FastAPI(title="CANE Prep API", lifespan=lifespan)
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
    async def database_unavailable(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=503, content={"detail": "Base de datos no disponible"}
        )

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
