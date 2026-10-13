"""Figuras de las preguntas: GET /sessions/{id}/questions/{position}/assets/{name}.

Con el repositorio en memoria; la consulta real contra PostgreSQL está en
tests/integration/test_importador.py y test_postgres_repository.py.
"""

from dataclasses import replace
from uuid import uuid4

import pytest
from fakes import FakeClock, InMemoryGameRepository, build_pool
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_current_user, get_repository
from app.domain import CurrentUser
from app.main import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"figura-ficticia"
REF_NAME = "figura-ficticia-fig-01.png"


def pool_with_figures():
    pool = build_pool(per_area=5)
    return [
        replace(
            q,
            assets=(
                {"ref": f"assets/{REF_NAME}", "kind": "figure", "alt": "Una figura",
                 "source_page": 1, "status": "available"},
            ),
            asset_data={f"assets/{REF_NAME}": PNG},
        )
        for q in pool
    ]


@pytest.fixture
def repo():
    return InMemoryGameRepository(FakeClock(), pool_with_figures())


@pytest.fixture
def user():
    return CurrentUser(user_id=uuid4(), team_id=uuid4())


@pytest.fixture
def app(repo, user):
    app = create_app(Settings(frontend_origins=("http://localhost:5173",)))
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_current_user] = lambda: user
    return app


@pytest.fixture
def api(app):
    return TestClient(app)


def start_session(api, count=3):
    r = api.post("/sessions", json={"mode": "random", "question_count": count})
    assert r.status_code == 201
    return r.json()["id"]


def url(session_id, position=1, name=REF_NAME):
    return f"/sessions/{session_id}/questions/{position}/assets/{name}"


def test_question_lists_its_figures_and_the_endpoint_serves_the_bytes(api):
    sid = start_session(api)
    question = api.post(f"/sessions/{sid}/next").json()

    assert [a["ref"] for a in question["assets"]] == [f"assets/{REF_NAME}"]
    response = api.get(url(sid, question["position"]))

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"].startswith("private")
    assert response.headers["etag"].startswith('"') and len(response.headers["etag"]) == 66


def test_a_figure_of_a_question_not_yet_issued_is_not_available(api):
    sid = start_session(api, count=3)
    api.post(f"/sessions/{sid}/next")  # solo la posición 1 está emitida

    assert api.get(url(sid, 1)).status_code == 200
    assert api.get(url(sid, 2)).status_code == 404
    assert api.get(url(sid, 3)).status_code == 404


def test_another_users_session_looks_nonexistent(api, app):
    sid = start_session(api)
    api.post(f"/sessions/{sid}/next")
    intruder = CurrentUser(user_id=uuid4(), team_id=uuid4())
    app.dependency_overrides[get_current_user] = lambda: intruder

    assert api.get(url(sid, 1)).status_code == 404


def test_unknown_figure_and_unknown_session_are_404(api):
    sid = start_session(api)
    api.post(f"/sessions/{sid}/next")

    assert api.get(url(sid, 1, "otra-figura.png")).status_code == 404
    assert api.get(url(uuid4(), 1)).status_code == 404


@pytest.mark.parametrize(
    "name",
    ["figura.svg", "FIGURA.png", "figura.png%00.png", "a b.png", "figura.PNG", "%2e%2e", "figura",
     "figura.png.exe"],
)
def test_names_outside_the_closed_pattern_are_rejected_by_validation(api, name):
    sid = start_session(api)
    api.post(f"/sessions/{sid}/next")

    # 422: ni siquiera llega a buscarse; la validación del patrón corta antes.
    assert api.get(url(sid, 1, name)).status_code == 422


@pytest.mark.parametrize("name", ["..%2F..%2Fsecreto.png", "a%2Fb.png", "%2e%2e%2fx.png"])
def test_names_with_path_separators_never_match_a_route(api, name):
    sid = start_session(api)
    api.post(f"/sessions/{sid}/next")

    assert api.get(url(sid, 1, name)).status_code == 404


def test_position_must_be_positive(api):
    sid = start_session(api)
    api.post(f"/sessions/{sid}/next")

    assert api.get(url(sid, 0)).status_code == 422
    assert api.get(url(sid, -1)).status_code == 422


def test_the_response_never_carries_the_answer(api):
    sid = start_session(api)
    api.post(f"/sessions/{sid}/next")
    response = api.get(url(sid, 1))

    assert b"correct" not in response.content
    assert not any("correct" in k.lower() for k in response.headers)


def test_without_configuration_the_figure_route_is_unavailable():
    client = TestClient(create_app(Settings(frontend_origins=("http://localhost:5173",))))

    assert client.get(url(uuid4(), 1)).status_code == 503
