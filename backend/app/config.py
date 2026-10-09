import os
from dataclasses import dataclass

DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"


@dataclass(frozen=True)
class Settings:
    """Configuración leída del entorno. No abre conexiones ni exige secretos."""

    frontend_origins: tuple[str, ...]


def load_settings() -> Settings:
    raw = os.environ.get("FRONTEND_ORIGIN", "").strip() or DEFAULT_FRONTEND_ORIGIN
    origins = tuple(o.strip().rstrip("/") for o in raw.split(",") if o.strip())
    if not origins or "*" in origins:
        raise ValueError(
            "FRONTEND_ORIGIN debe listar orígenes explícitos; no se admite '*'."
        )
    return Settings(frontend_origins=origins)
