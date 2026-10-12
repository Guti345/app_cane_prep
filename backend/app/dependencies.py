"""Dependencias de la API. Seguras por defecto: nada está conectado todavía."""

from fastapi import HTTPException

from app.domain import CurrentUser, GameRepository


def get_current_user() -> CurrentUser:
    """Identidad verificada del usuario. SIN IMPLEMENTAR.

    La parte 3 debe validar el token de Supabase y cargar el perfil y equipo
    desde la base de datos. Hasta entonces, todo endpoint de juego responde
    501: no existe un modo "sin autenticación" ni una identidad simulada.
    Las pruebas la sustituyen con `app.dependency_overrides`.
    """
    raise HTTPException(status_code=501, detail="Autenticación no implementada")


def get_repository() -> GameRepository:
    """Acceso a datos del juego. SIN IMPLEMENTAR (no hay conexión a la base)."""
    raise HTTPException(status_code=501, detail="Base de datos no conectada")
