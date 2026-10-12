from uuid import UUID, uuid4

import pytest
from fakes import FakeClock, InMemoryGameRepository, build_pool
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_current_user, get_repository
from app.domain import CurrentUser
from app.main import create_app

ORIGIN = "http://localhost:5173"


def find_keys(value, key):
    """True si `key` aparece en cualquier nivel de un JSON."""
    if isinstance(value, dict):
        return key in value or any(find_keys(v, key) for v in value.values())
    if isinstance(value, list):
        return any(find_keys(v, key) for v in value)
    return False


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def app(clock):
    app = create_app(Settings(frontend_origins=(ORIGIN,)))
    app.dependency_overrides[get_repository] = lambda: InMemoryGameRepository(
        clock, build_pool()
    )
    return app


@pytest.fixture
def repo(clock):
    return InMemoryGameRepository(clock, build_pool())


@pytest.fixture
def user_a():
    return CurrentUser(user_id=uuid4(), team_id=uuid4())


@pytest.fixture
def user_b():
    return CurrentUser(user_id=uuid4(), team_id=uuid4())


@pytest.fixture
def api(app, repo, user_a):
    """Cliente autenticado como user_a, con un repositorio compartido."""
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: user_a
    return TestClient(app)


def as_user(app, user):
    app.dependency_overrides[get_current_user] = lambda: user


def new_session(api, **body):
    body = body or {"mode": "random", "question_count": 3}
    response = api.post("/sessions", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- seguro por defecto ------------------------------------------------------


def test_game_routes_are_unavailable_without_configuration():
    client = TestClient(create_app(Settings(frontend_origins=(ORIGIN,))))
    sid = uuid4()

    responses = [
        client.post("/sessions", json={"mode": "random", "question_count": 1}),
        client.get(f"/sessions/{sid}"),
        client.post(f"/sessions/{sid}/next"),
        client.post(f"/sessions/{sid}/answer", json={"position": 1}),
        client.post(f"/sessions/{sid}/abandon"),
    ]

    assert [r.status_code for r in responses] == [503] * 5


def test_health_still_works_without_auth_or_database():
    client = TestClient(create_app(Settings(frontend_origins=(ORIGIN,))))

    assert client.get("/health").json() == {"ok": True}


def test_cors_preflight_allows_post_from_configured_origin(app):
    response = TestClient(app).options(
        "/sessions",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN


# --- crear sesión --------------------------------------------------------------


def test_create_session_returns_state(api):
    session = new_session(api, mode="area", area="econometria", question_count=3)

    assert session["status"] == "active"
    assert session["area"] == "econometria"
    assert session["question_count"] == 3
    assert session["answered_count"] == 0
    assert session["current_position"] is None
    assert "user_id" not in session


def test_simulacro_question_count_comes_from_stage(api):
    session = new_session(api, mode="simulacro", stage="final")

    assert session["question_count"] == 4


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "area", "question_count": 3},  # falta area
        {"mode": "area", "area": "econometria"},  # falta question_count
        {"mode": "random", "area": "econometria", "question_count": 3},
        {"mode": "simulacro"},  # falta stage
        {"mode": "simulacro", "stage": "final", "question_count": 9},
        {"mode": "random", "question_count": 0},
        {"mode": "random", "question_count": 1000},
        {"mode": "otro", "question_count": 3},
    ],
)
def test_invalid_session_requests_are_rejected(api, body):
    assert api.post("/sessions", json=body).status_code == 422


def test_client_cannot_choose_user_id(api, user_b):
    response = api.post(
        "/sessions",
        json={"mode": "random", "question_count": 2, "user_id": str(user_b.user_id)},
    )

    assert response.status_code == 422


def test_session_belongs_to_authenticated_user(api, repo, user_a):
    session = new_session(api)

    assert repo.get_session(UUID(session["id"])).user_id == user_a.user_id


def test_not_enough_questions_is_conflict(api):
    response = api.post("/sessions", json={"mode": "area", "area": "econometria", "question_count": 50})

    assert response.status_code == 409


# --- emitir preguntas ------------------------------------------------------------


def test_next_returns_question_without_correct_option(api):
    sid = new_session(api)["id"]

    response = api.post(f"/sessions/{sid}/next")

    assert response.status_code == 200
    question = response.json()
    assert question["position"] == 1
    assert not find_keys(question, "correct_option")
    assert set(question) == {
        "position", "area", "statement_md", "options", "assets", "deadline_at",
        "server_now",
    }


def test_reload_does_not_restart_the_timer(api, clock):
    sid = new_session(api)["id"]
    first = api.post(f"/sessions/{sid}/next").json()

    clock.advance(30)
    again = api.post(f"/sessions/{sid}/next").json()

    assert again["position"] == first["position"]
    assert again["deadline_at"] == first["deadline_at"]


def test_session_state_exposes_current_deadline_without_answer(api, clock):
    sid = new_session(api)["id"]
    question = api.post(f"/sessions/{sid}/next").json()
    clock.advance(10)

    state = api.get(f"/sessions/{sid}").json()

    assert state["current_position"] == 1
    assert state["current_deadline_at"] == question["deadline_at"]
    assert not find_keys(state, "correct_option")


def test_next_does_not_advance_until_current_is_answered(api):
    sid = new_session(api)["id"]
    api.post(f"/sessions/{sid}/next")

    assert api.post(f"/sessions/{sid}/next").json()["position"] == 1


def test_next_registers_an_expired_question_as_timeout_and_moves_on(api, clock):
    sid = new_session(api, mode="random", question_count=2)["id"]
    first = api.post(f"/sessions/{sid}/next").json()
    clock.advance(91)

    second = api.post(f"/sessions/{sid}/next").json()

    assert second["position"] == 2
    assert second["deadline_at"] > first["deadline_at"]
    state = api.get(f"/sessions/{sid}").json()
    assert state["answered_count"] == 1
    # El intento 1 quedó como timeout: reenviar devuelve ese resultado.
    attempt = api.post(
        f"/sessions/{sid}/answer", json={"position": 1, "selected_option": "A"}
    ).json()
    assert attempt["timed_out"] is True


def test_next_after_the_last_expired_question_completes_the_session(api, clock):
    sid = new_session(api, mode="random", question_count=1)["id"]
    api.post(f"/sessions/{sid}/next")
    clock.advance(91)

    response = api.post(f"/sessions/{sid}/next")

    assert response.status_code == 409
    assert api.get(f"/sessions/{sid}").json()["status"] == "completed"


# --- responder ---------------------------------------------------------------------


def test_correct_answer_reveals_correct_option_after_answering(api):
    sid = new_session(api)["id"]
    api.post(f"/sessions/{sid}/next")

    response = api.post(f"/sessions/{sid}/answer", json={"position": 1, "selected_option": "A"})

    assert response.status_code == 200
    attempt = response.json()
    assert attempt["is_correct"] is True
    assert attempt["timed_out"] is False
    assert attempt["correct_option"] == "A"


def test_wrong_answer_is_marked_and_shows_correct_option(api):
    sid = new_session(api)["id"]
    api.post(f"/sessions/{sid}/next")

    attempt = api.post(
        f"/sessions/{sid}/answer", json={"position": 1, "selected_option": "C"}
    ).json()

    assert attempt["is_correct"] is False
    assert attempt["correct_option"] == "A"


def test_resubmitting_returns_the_stored_attempt(api):
    sid = new_session(api)["id"]
    api.post(f"/sessions/{sid}/next")
    first = api.post(f"/sessions/{sid}/answer", json={"position": 1, "selected_option": "C"})

    second = api.post(f"/sessions/{sid}/answer", json={"position": 1, "selected_option": "A"})

    assert second.status_code == 200
    assert second.json() == first.json()
    assert second.json()["selected_option"] == "C"


def test_answer_after_deadline_is_a_timeout(api, clock):
    sid = new_session(api)["id"]
    api.post(f"/sessions/{sid}/next")
    clock.advance(91)

    attempt = api.post(
        f"/sessions/{sid}/answer", json={"position": 1, "selected_option": "A"}
    ).json()

    assert attempt["timed_out"] is True
    assert attempt["is_correct"] is False
    assert attempt["selected_option"] is None
    assert attempt["time_used_ms"] == 90000


def test_null_option_after_deadline_registers_timeout(api, clock):
    sid = new_session(api)["id"]
    api.post(f"/sessions/{sid}/next")
    clock.advance(90)

    attempt = api.post(f"/sessions/{sid}/answer", json={"position": 1}).json()

    assert attempt["timed_out"] is True


def test_answering_a_question_that_was_not_issued_is_conflict(api):
    sid = new_session(api)["id"]

    response = api.post(f"/sessions/{sid}/answer", json={"position": 2, "selected_option": "A"})

    assert response.status_code == 409


def test_option_outside_the_question_is_rejected(api):
    sid = new_session(api)["id"]
    api.post(f"/sessions/{sid}/next")

    response = api.post(f"/sessions/{sid}/answer", json={"position": 1, "selected_option": "E"})

    assert response.status_code == 422


def test_unknown_option_label_is_rejected_by_schema(api):
    sid = new_session(api)["id"]
    api.post(f"/sessions/{sid}/next")

    response = api.post(f"/sessions/{sid}/answer", json={"position": 1, "selected_option": "Z"})

    assert response.status_code == 422


def test_session_completes_after_last_answer(api):
    sid = new_session(api, mode="random", question_count=2)["id"]
    for position in (1, 2):
        api.post(f"/sessions/{sid}/next")
        api.post(f"/sessions/{sid}/answer", json={"position": position, "selected_option": "A"})

    state = api.get(f"/sessions/{sid}").json()

    assert state["status"] == "completed"
    assert state["answered_count"] == 2
    assert api.post(f"/sessions/{sid}/next").status_code == 409


# --- abandonar -----------------------------------------------------------------------


def test_abandon_closes_the_session(api):
    sid = new_session(api)["id"]

    assert api.post(f"/sessions/{sid}/abandon").json()["status"] == "abandoned"
    assert api.post(f"/sessions/{sid}/next").status_code == 409


def test_cannot_abandon_a_completed_session(api):
    sid = new_session(api, mode="random", question_count=1)["id"]
    api.post(f"/sessions/{sid}/next")
    api.post(f"/sessions/{sid}/answer", json={"position": 1, "selected_option": "A"})

    assert api.post(f"/sessions/{sid}/abandon").status_code == 409


# --- sesiones ajenas -------------------------------------------------------------------


def test_other_users_session_looks_nonexistent(api, app, user_b):
    sid = new_session(api)["id"]
    api.post(f"/sessions/{sid}/next")
    as_user(app, user_b)

    responses = [
        api.get(f"/sessions/{sid}"),
        api.post(f"/sessions/{sid}/next"),
        api.post(f"/sessions/{sid}/answer", json={"position": 1, "selected_option": "A"}),
        api.post(f"/sessions/{sid}/abandon"),
    ]

    assert [r.status_code for r in responses] == [404] * 4


def test_unknown_session_is_404(api):
    assert api.get(f"/sessions/{uuid4()}").status_code == 404
