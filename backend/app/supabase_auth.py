"""Autenticación: validación del token con Supabase Auth y carga del perfil.

El navegador envía `Authorization: Bearer <access_token>`. El backend no
confía en el token por su forma: se lo pregunta a Supabase Auth
(`GET /auth/v1/user`, el equivalente de `get_user`), que rechaza tokens
vencidos, revocados o de usuarios bloqueados. Después exige un perfil con
equipo en `public.profiles`: tener cuenta en Auth no basta para jugar.
"""

from typing import Protocol
from uuid import UUID

import httpx

from app.domain import CurrentUser

REQUEST_TIMEOUT_SECONDS = 5.0
MAX_TOKEN_LENGTH = 4096


class InvalidToken(Exception):
    """El token falta, está mal formado, venció o fue revocado."""


class AuthUnavailable(Exception):
    """No se pudo comprobar el token (Supabase Auth no respondió bien)."""


class NoProfile(Exception):
    """El usuario existe en Auth pero no tiene perfil/equipo en la base."""


class TokenVerifier(Protocol):
    def verify(self, token: str) -> UUID: ...


class ProfileLookup(Protocol):
    def team_id_for_user(self, user_id: UUID) -> UUID | None: ...


class SupabaseTokenVerifier:
    def __init__(
        self,
        supabase_url: str,
        publishable_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        self._user_url = supabase_url.rstrip("/") + "/auth/v1/user"
        self._publishable_key = publishable_key
        self._client = client or httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)

    def verify(self, token: str) -> UUID:
        if not token or len(token) > MAX_TOKEN_LENGTH or any(c.isspace() for c in token):
            raise InvalidToken()
        try:
            response = self._client.get(
                self._user_url,
                headers={
                    # La clave publicable identifica al proyecto; no autoriza datos.
                    "apikey": self._publishable_key,
                    "Authorization": f"Bearer {token}",
                },
            )
        except httpx.HTTPError:
            raise AuthUnavailable() from None

        if response.status_code == 200:
            try:
                return UUID(str(response.json()["id"]))
            except (ValueError, KeyError, TypeError):
                raise AuthUnavailable() from None
        # Cualquier 4xx (salvo límite de tasa) es un token que no vale.
        if 400 <= response.status_code < 500 and response.status_code != 429:
            raise InvalidToken()
        raise AuthUnavailable()


class AuthService:
    def __init__(self, verifier: TokenVerifier, profiles: ProfileLookup) -> None:
        self._verifier = verifier
        self._profiles = profiles

    def authenticate(self, token: str) -> CurrentUser:
        user_id = self._verifier.verify(token)
        team_id = self._profiles.team_id_for_user(user_id)
        if team_id is None:
            raise NoProfile()
        return CurrentUser(user_id=user_id, team_id=team_id)
