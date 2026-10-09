import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.main import create_app


def make_client(*origins: str) -> TestClient:
    return TestClient(create_app(Settings(frontend_origins=origins)))


def test_health_returns_ok():
    response = make_client("http://localhost:5173").get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_cors_allows_configured_origin():
    response = make_client("http://localhost:5173").get(
        "/health", headers={"Origin": "http://localhost:5173"}
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_does_not_allow_other_origins():
    response = make_client("http://localhost:5173").get(
        "/health", headers={"Origin": "https://otro-sitio.example"}
    )

    assert "access-control-allow-origin" not in response.headers


def test_default_origin_without_env(monkeypatch):
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)

    assert load_settings().frontend_origins == ("http://localhost:5173",)


def test_origin_from_env_accepts_list_and_trims_slash(monkeypatch):
    monkeypatch.setenv(
        "FRONTEND_ORIGIN", "https://cane.netlify.app/, http://localhost:5173"
    )

    assert load_settings().frontend_origins == (
        "https://cane.netlify.app",
        "http://localhost:5173",
    )


def test_wildcard_origin_is_rejected(monkeypatch):
    monkeypatch.setenv("FRONTEND_ORIGIN", "*")

    with pytest.raises(ValueError):
        load_settings()


SUPABASE_ENV_NAMES = ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "DATABASE_URL")


def test_health_works_without_supabase_variables(monkeypatch):
    for name in SUPABASE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()
    response = TestClient(create_app(settings)).get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert settings.database_url is None


def test_empty_supabase_variables_are_treated_as_unset(monkeypatch):
    for name in SUPABASE_ENV_NAMES:
        monkeypatch.setenv(name, "  ")

    settings = load_settings()

    assert settings.supabase_url is None
    assert settings.supabase_publishable_key is None
    assert settings.database_url is None


def test_database_url_is_not_exposed_in_repr(monkeypatch):
    marker = "marcador-no-secreto-para-prueba"
    monkeypatch.setenv("DATABASE_URL", f"postgresql://usuario:{marker}@host/db")

    settings = load_settings()

    assert settings.database_url is not None
    assert marker not in repr(settings)
