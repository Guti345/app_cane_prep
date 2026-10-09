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
