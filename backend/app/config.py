import os
from dataclasses import dataclass, field

DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"
DOCS_ENV = "ENABLE_API_DOCS"
_TRUTHY = {"1", "true", "yes", "si", "sí", "on"}


@dataclass(frozen=True)
class Settings:
    """Configuración leída del entorno. No abre conexiones ni exige secretos.

    Las variables de Supabase son opcionales: `/health` no las necesita. Sin
    ellas, las rutas de juego responden 503. `SUPABASE_URL` y
    `SUPABASE_PUBLISHABLE_KEY` sirven para validar el token del usuario;
    `DATABASE_URL` (privada) para el acceso a PostgreSQL.

    `docs_enabled` publica `/docs`, `/redoc` y `/openapi.json`. Por defecto
    están apagadas; se encienden solo con `ENABLE_API_DOCS=1` (desarrollo).
    Apagarlas no sustituye la autenticación ni el control de acceso.
    """

    frontend_origins: tuple[str, ...]
    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    # Privada: repr=False evita que aparezca en logs o trazas.
    database_url: str | None = field(default=None, repr=False)
    docs_enabled: bool = False


def _optional(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def load_settings() -> Settings:
    raw = os.environ.get("FRONTEND_ORIGIN", "").strip() or DEFAULT_FRONTEND_ORIGIN
    origins = tuple(o.strip().rstrip("/") for o in raw.split(",") if o.strip())
    if not origins or "*" in origins:
        raise ValueError(
            "FRONTEND_ORIGIN debe listar orígenes explícitos; no se admite '*'."
        )
    return Settings(
        frontend_origins=origins,
        supabase_url=_optional("SUPABASE_URL"),
        supabase_publishable_key=_optional("SUPABASE_PUBLISHABLE_KEY"),
        database_url=_optional("DATABASE_URL"),
        docs_enabled=(_optional(DOCS_ENV) or "").lower() in _TRUTHY,
    )
