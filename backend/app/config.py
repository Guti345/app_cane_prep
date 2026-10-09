import os
from dataclasses import dataclass, field

DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"


@dataclass(frozen=True)
class Settings:
    """Configuración leída del entorno. No abre conexiones ni exige secretos.

    Las variables de Supabase son opcionales y todavía no las usa ningún
    endpoint: solo fijan el nombre que leerá el código cuando exista.
    """

    frontend_origins: tuple[str, ...]
    supabase_url: str | None = None
    supabase_publishable_key: str | None = None
    # Privada: repr=False evita que aparezca en logs o trazas.
    database_url: str | None = field(default=None, repr=False)


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
    )
