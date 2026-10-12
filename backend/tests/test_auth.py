from uuid import UUID, uuid4

import httpx
import pytest
from fakes import FakeClock, InMemoryGameRepository, build_pool
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain import CurrentUser
from app.main import create_app
from app.supabase_auth import (
    AuthService,
    AuthUnavailable,
    InvalidToken,
    NoProfile,
    SupabaseTokenVerifier,
)

SUPABASE_URL = "https://proyecto-ficticio.supabase.co"
PUBLISHABLE_KEY = "clave-publicable-ficticia"
ORIGIN = "http://localhost:5173"


def verifier_with(handler) -> SupabaseTokenVerifier:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return SupabaseTokenVerifier(SUPABASE_URL, PUBLISHABLE_KEY, client=client)


# --- verificador de tokens ------------------------------------------------------


def test_verifier_returns_user_id_and_sends_expected_request():
    user_id = uuid4()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["apikey"] = request.headers.get("apikey")
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": str(user_id), "email": "x@example.org"})

    assert verifier_with(handler).verify("token-de-prueba") == user_id
    assert seen == {
        "url": f"{SUPABASE_URL}/auth/v1/user",
        "apikey": PUBLISHABLE_KEY,
        "authorization": "Bearer token-de-prueba",
    }


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_verifier_rejects_tokens_that_auth_refuses(status):
    verifier = verifier_with(lambda request: httpx.Response(status, json={}))

    with pytest.raises(InvalidToken):
        verifier.verify("token")


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_verifier_reports_auth_outages_separately(status):
    verifier = verifier_with(lambda request: httpx.Response(status))

    with pytest.raises(AuthUnavailable):
        verifier.verify("token")


def test_verifier_reports_network_errors_as_unavailable():
    def handler(request):
        raise httpx.ConnectError("sin red")

    with pytest.raises(AuthUnavailable):
        verifier_with(handler).verify("token")


@pytest.mark.parametrize("body", [{}, {"id": "no-es-uuid"}, {"id": None}])
def test_verifier_rejects_unexpected_payloads(body):
    verifier = verifier_with(lambda request: httpx.Response(200, json=body))

    with pytest.raises(AuthUnavailable):
        verifier.verify("token")


@pytest.mark.parametrize("token", ["", "con espacio", "x" * 5000])
def test_verifier_does_not_call_auth_for_malformed_tokens(token):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": str(uuid4())})

    with pytest.raises(InvalidToken):
        verifier_with(handler).verify(token)
    assert calls == []


# --- servicio: token + perfil ---------------------------------------------------


class StaticVerifier:
    def __init__(self, user_id=None, error=None):
        self.user_id, self.error = user_id, error

    def verify(self, token):
        if self.error:
            raise self.error
        return self.user_id


class StaticProfiles:
    def __init__(self, teams):
        self.teams = teams

    def team_id_for_user(self, user_id):
        return self.teams.get(user_id)


def test_service_returns_user_with_team_from_profile():
    user_id, team_id = uuid4(), uuid4()
    service = AuthService(StaticVerifier(user_id), StaticProfiles({user_id: team_id}))

    assert service.authenticate("t") == CurrentUser(user_id=user_id, team_id=team_id)


def test_service_requires_a_profile():
    service = AuthService(StaticVerifier(uuid4()), StaticProfiles({}))

    with pytest.raises(NoProfile):
        service.authenticate("t")


# --- dependencia HTTP --------------------------------------------------------------


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def team_id():
    return uuid4()


def build_client(verifier, profiles, repo=None) -> TestClient:
    clock = FakeClock()
    app = create_app(
        Settings(frontend_origins=(ORIGIN,)),
        auth=AuthService(verifier, profiles),
        repository=repo or InMemoryGameRepository(clock, build_pool()),
    )
    return TestClient(app)


def bearer(token="token-valido"):
    return {"Authorization": f"Bearer {token}"}


def test_valid_token_and_profile_can_create_a_session(user_id, team_id):
    client = build_client(StaticVerifier(user_id), StaticProfiles({user_id: team_id}))

    response = client.post(
        "/sessions", json={"mode": "random", "question_count": 2}, headers=bearer()
    )

    assert response.status_code == 201


def test_session_is_bound_to_the_verified_identity(user_id, team_id):
    repo = InMemoryGameRepository(FakeClock(), build_pool())
    client = build_client(StaticVerifier(user_id), StaticProfiles({user_id: team_id}), repo)

    created = client.post(
        "/sessions", json={"mode": "random", "question_count": 2}, headers=bearer()
    ).json()

    stored = repo.get_session(UUID(created["id"]))
    assert (stored.user_id, stored.team_id) == (user_id, team_id)


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": ""}, {"Authorization": "Bearer"}, {"Authorization": "Basic abc"}],
)
def test_missing_or_wrong_authorization_header_is_401(headers, user_id, team_id):
    client = build_client(StaticVerifier(user_id), StaticProfiles({user_id: team_id}))

    response = client.post("/sessions", json={"mode": "random", "question_count": 1}, headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_token_is_401(team_id):
    client = build_client(StaticVerifier(error=InvalidToken()), StaticProfiles({}))

    response = client.get(f"/sessions/{uuid4()}", headers=bearer("malo"))

    assert response.status_code == 401


def test_user_without_profile_is_403(user_id):
    client = build_client(StaticVerifier(user_id), StaticProfiles({}))

    response = client.get(f"/sessions/{uuid4()}", headers=bearer())

    assert response.status_code == 403


def test_auth_outage_is_503_not_401(user_id):
    client = build_client(StaticVerifier(error=AuthUnavailable()), StaticProfiles({}))

    response = client.get(f"/sessions/{uuid4()}", headers=bearer())

    assert response.status_code == 503


def test_user_id_in_body_or_query_never_sets_identity(user_id, team_id):
    other = uuid4()
    client = build_client(StaticVerifier(user_id), StaticProfiles({user_id: team_id}))

    response = client.post(
        f"/sessions?user_id={other}",
        json={"mode": "random", "question_count": 1, "user_id": str(other)},
        headers=bearer(),
    )

    assert response.status_code == 422


def test_health_does_not_need_a_token():
    client = build_client(StaticVerifier(error=InvalidToken()), StaticProfiles({}))

    assert client.get("/health").json() == {"ok": True}


# --- configuración -----------------------------------------------------------------


def test_app_builds_without_connecting_when_configured():
    # Crear la app (y TestClient sin lifespan) no abre conexiones ni llama a Auth.
    settings = Settings(
        frontend_origins=(ORIGIN,),
        supabase_url=SUPABASE_URL,
        supabase_publishable_key=PUBLISHABLE_KEY,
        database_url="postgresql://usuario:clave@127.0.0.1:1/inexistente",
    )

    client = TestClient(create_app(settings))

    assert client.get("/health").json() == {"ok": True}
    assert client.post(
        "/sessions", json={"mode": "random", "question_count": 1}
    ).status_code == 401  # configurada: exige token antes de tocar la base


def test_database_outage_is_503():
    import psycopg

    class BrokenRepository(InMemoryGameRepository):
        def get_session(self, session_id):
            raise psycopg.OperationalError("sin conexión")

    user_id, team_id = uuid4(), uuid4()
    repo = BrokenRepository(FakeClock(), build_pool())
    client = build_client(StaticVerifier(user_id), StaticProfiles({user_id: team_id}), repo)

    response = client.get(f"/sessions/{uuid4()}", headers=bearer())

    assert response.status_code == 503
    assert "clave" not in response.text.lower()
