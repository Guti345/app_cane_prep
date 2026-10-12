"""Dependencias de la API. Seguras por defecto: sin configuración, nada responde."""

from fastapi import HTTPException, Request

from app.domain import CurrentUser, GameRepository
from app.supabase_auth import AuthService, AuthUnavailable, InvalidToken, NoProfile


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Falta el token de acceso",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def get_current_user(request: Request) -> CurrentUser:
    """Identidad verificada: token validado con Supabase Auth + perfil en la base.

    La identidad sale solo de aquí, nunca del cuerpo ni de la URL.
    """
    auth: AuthService | None = getattr(request.app.state, "auth", None)
    if auth is None:
        raise HTTPException(status_code=503, detail="Autenticación no configurada")
    token = _bearer_token(request)
    try:
        return auth.authenticate(token)
    except InvalidToken:
        raise HTTPException(
            status_code=401,
            detail="Token inválido o vencido",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None
    except NoProfile:
        raise HTTPException(
            status_code=403, detail="Tu usuario no tiene un perfil de equipo"
        ) from None
    except AuthUnavailable:
        raise HTTPException(
            status_code=503, detail="No se pudo verificar la sesión; intenta de nuevo"
        ) from None


def get_repository(request: Request) -> GameRepository:
    repository: GameRepository | None = getattr(request.app.state, "repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="Base de datos no configurada")
    return repository
