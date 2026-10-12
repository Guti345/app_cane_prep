"""B1 (server_now), B2 (GET /ranking) y B3 (GET /sessions/{id}/attempts)."""

from datetime import datetime
from uuid import uuid4

import pytest
from fakes import FakeClock, InMemoryGameRepository, build_pool
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_current_user, get_repository
from app.domain import CurrentUser, RankingRow
from app.main import create_app

ORIGIN = "http://localhost:5173"


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def repo(clock):
    return InMemoryGameRepository(clock, build_pool())


@pytest.fixture
def me():
    return CurrentUser(user_id=uuid4(), team_id=uuid4())


@pytest.fixture
def app(repo, me):
    app = create_app(Settings(frontend_origins=(ORIGIN,)))
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: me
    return app


@pytest.fixture
def api(app):
    return TestClient(app)


def start(api, **body):
    response = api.post("/sessions", json=body or {"mode": "random", "question_count": 3})
    assert response.status_code == 201, response.text
    return response.json()


def row(user_id, name, rank, seen=20, correct=18, **kwargs):
    return RankingRow(
        user_id=user_id,
        display_name=name,
        rank_position=rank,
        questions_seen=seen,
        correct_count=correct,
        accuracy_pct=kwargs.get("accuracy_pct", 90.0 if rank else None),
        avg_time_seconds=kwargs.get("avg_time_seconds", 12.5 if seen else None),
        sessions_completed=kwargs.get("sessions_completed", 2),
    )


# --- B1: server_now ---------------------------------------------------------------


def test_next_and_session_state_include_server_now(api, clock):
    session = start(api)
    assert datetime.fromisoformat(session["server_now"]) == clock.now

    clock.advance(7)
    question = api.post(f"/sessions/{session['id']}/next").json()
    assert datetime.fromisoformat(question["server_now"]) == clock.now

    clock.advance(5)
    state = api.get(f"/sessions/{session['id']}").json()
    assert datetime.fromisoformat(state["server_now"]) == clock.now


def test_server_now_lets_the_client_compute_remaining_time(api, clock):
    sid = start(api)["id"]
    question = api.post(f"/sessions/{sid}/next").json()

    remaining = (
        datetime.fromisoformat(question["deadline_at"])
        - datetime.fromisoformat(question["server_now"])
    ).total_seconds()

    assert remaining == 90


# --- B2: ranking --------------------------------------------------------------------


def test_ranking_returns_the_team_with_my_row_flagged(api, repo, me):
    other = uuid4()
    repo.ranking_by_team[me.team_id] = [
        row(other, "Ana", 1),
        row(me.user_id, "Yo", 2, correct=17),
        row(uuid4(), "Luis", None, seen=5, correct=3),
    ]

    response = api.get("/ranking")

    assert response.status_code == 200
    rows = response.json()
    assert [(r["display_name"], r["rank_position"], r["is_me"]) for r in rows] == [
        ("Ana", 1, False),
        ("Yo", 2, True),
        ("Luis", None, False),
    ]


def test_ranking_never_exposes_user_ids(api, repo, me):
    repo.ranking_by_team[me.team_id] = [row(me.user_id, "Yo", 1)]

    body = api.get("/ranking").json()

    assert set(body[0]) == {
        "display_name", "rank_position", "questions_seen", "correct_count",
        "accuracy_pct", "avg_time_seconds", "sessions_completed", "is_me",
    }


def test_ranking_is_scoped_to_the_verified_team(api, repo, me):
    other_team = uuid4()
    repo.ranking_by_team[other_team] = [row(uuid4(), "De otro equipo", 1)]
    repo.ranking_by_team[me.team_id] = [row(me.user_id, "Yo", 1)]

    names = [r["display_name"] for r in api.get("/ranking").json()]
    with_param = api.get(f"/ranking?team_id={other_team}").json()

    assert names == ["Yo"]
    assert [r["display_name"] for r in with_param] == ["Yo"]  # el parámetro no cuenta


def test_ranking_requires_authentication():
    client = TestClient(create_app(Settings(frontend_origins=(ORIGIN,))))

    assert client.get("/ranking").status_code == 503  # sin configuración


# --- B3: intentos de la sesión ---------------------------------------------------------


def test_attempts_start_empty_and_only_list_answered_positions(api):
    sid = start(api)["id"]
    api.post(f"/sessions/{sid}/next")

    assert api.get(f"/sessions/{sid}/attempts").json() == []  # la pendiente no aparece

    api.post(f"/sessions/{sid}/answer", json={"position": 1, "selected_option": "C"})
    api.post(f"/sessions/{sid}/next")  # pregunta 2 abierta, sin responder

    attempts = api.get(f"/sessions/{sid}/attempts").json()
    assert [a["position"] for a in attempts] == [1]
    assert attempts[0]["correct_option"] == "A"
    assert attempts[0]["is_correct"] is False


def test_attempts_include_timeouts_registered_by_next(api, clock):
    sid = start(api, mode="random", question_count=2)["id"]
    api.post(f"/sessions/{sid}/next")
    clock.advance(95)
    api.post(f"/sessions/{sid}/next")  # registra el timeout de la 1

    attempts = api.get(f"/sessions/{sid}/attempts").json()

    assert attempts[0]["timed_out"] is True
    assert attempts[0]["selected_option"] is None


def test_attempts_of_another_users_session_are_404(api, app):
    sid = start(api)["id"]
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(uuid4(), uuid4())

    assert api.get(f"/sessions/{sid}/attempts").status_code == 404


def test_attempts_of_unknown_session_are_404(api):
    assert api.get(f"/sessions/{uuid4()}/attempts").status_code == 404
