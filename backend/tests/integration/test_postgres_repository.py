"""El repositorio real contra la migración real (PostgreSQL local, sin Supabase)."""

from uuid import uuid4

import pytest

from app.domain import (
    InvalidOption,
    NotEnoughQuestions,
    NothingPending,
    QuestionNotIssued,
    SessionClosed,
    SessionNotFound,
)


@pytest.fixture
def world(seed):
    team = seed.team()
    return {"team": team, "user": seed.user(team)}


def make_session(repo, world, **kwargs):
    params = {"mode": "random", "area": None, "stage": None, "question_count": 3}
    params.update(kwargs)
    return repo.create_session(user_id=world["user"], team_id=world["team"], **params)


# --- perfiles ----------------------------------------------------------------------


def test_team_lookup_returns_team_or_none(repo, world):
    assert repo.team_id_for_user(world["user"]) == world["team"]
    assert repo.team_id_for_user(uuid4()) is None


# --- crear sesiones ------------------------------------------------------------------


def test_area_session_builds_a_complete_unissued_manifest(repo, seed, world, db):
    seed.bank(per_area=5)

    session = make_session(repo, world, mode="area", area="econometria", question_count=3)

    rows = db.execute(
        "SELECT sq.position, sq.issued_at, sq.deadline_at, q.area "
        "FROM public.session_questions sq JOIN public.questions q ON q.id = sq.question_id "
        "WHERE sq.session_id = %s ORDER BY sq.position",
        (session.id,),
    ).fetchall()
    assert [r["position"] for r in rows] == [1, 2, 3]
    assert {r["area"] for r in rows} == {"econometria"}
    assert all(r["issued_at"] is None and r["deadline_at"] is None for r in rows)
    assert (session.user_id, session.team_id) == (world["user"], world["team"])
    assert session.status == "active"
    assert session.answered_count == 0


def test_simulacro_takes_equal_share_from_each_area(repo, seed, world, db):
    seed.bank(per_area=3)

    session = make_session(repo, world, mode="simulacro", stage="final", question_count=4)

    areas = [
        r["area"]
        for r in db.execute(
            "SELECT q.area FROM public.session_questions sq "
            "JOIN public.questions q ON q.id = sq.question_id WHERE sq.session_id = %s",
            (session.id,),
        ).fetchall()
    ]
    assert sorted(areas) == sorted(["microeconomia", "macroeconomia", "econometria", "historia_pensamiento"])


def test_not_enough_questions_leaves_no_session_behind(repo, seed, world, db):
    seed.bank(per_area=2)

    with pytest.raises(NotEnoughQuestions):
        make_session(repo, world, mode="area", area="econometria", question_count=5)

    assert db.execute("SELECT count(*) AS n FROM public.sessions").fetchone()["n"] == 0


def test_simulacro_needs_every_area_covered(repo, seed, world):
    for _ in range(4):
        seed.question("microeconomia")  # solo una área tiene preguntas

    with pytest.raises(NotEnoughQuestions):
        make_session(repo, world, mode="simulacro", stage="final", question_count=4)


def test_inactive_and_unready_questions_are_never_served(repo, seed, world):
    for _ in range(2):
        seed.question("econometria")
    for _ in range(5):
        seed.question("econometria", active=False)  # lista pero desactivada
    for _ in range(5):
        seed.question("econometria", ready=False)  # sin revisar

    with pytest.raises(NotEnoughQuestions):
        make_session(repo, world, mode="area", area="econometria", question_count=3)


def test_only_the_latest_active_revision_is_served(repo, seed, world, db):
    seed.question("econometria", source_id="p1", revision=1)
    latest = seed.question("econometria", source_id="p1", revision=2)

    session = make_session(repo, world, mode="area", area="econometria", question_count=1)

    served = db.execute(
        "SELECT question_id FROM public.session_questions WHERE session_id = %s",
        (session.id,),
    ).fetchone()["question_id"]
    assert served == latest


# --- emitir ---------------------------------------------------------------------------


@pytest.fixture
def started(repo, seed, world):
    seed.bank(per_area=5)
    return make_session(repo, world, mode="random", question_count=3)


def test_issue_sets_a_90_second_deadline_from_a_single_instant(repo, started, db):
    question = repo.issue_next_question(started.id)

    row = db.execute(
        "SELECT issued_at, deadline_at FROM public.session_questions "
        "WHERE session_id = %s AND position = 1",
        (started.id,),
    ).fetchone()
    assert (row["deadline_at"] - row["issued_at"]).total_seconds() == 90
    assert question.deadline_at == row["deadline_at"]
    assert question.position == 1


def test_issued_question_has_no_correct_option(repo, started):
    question = repo.issue_next_question(started.id)

    assert not hasattr(question, "correct_option")
    assert {o.label for o in question.options} == {"A", "B", "C"}


def test_issuing_again_returns_the_same_deadline(repo, started):
    first = repo.issue_next_question(started.id)
    second = repo.issue_next_question(started.id)

    assert (second.position, second.deadline_at) == (first.position, first.deadline_at)


def test_state_reports_the_pending_question(repo, started):
    question = repo.issue_next_question(started.id)

    state = repo.get_session(started.id)

    assert state.current_position == 1
    assert state.current_deadline_at == question.deadline_at
    assert state.answered_count == 0


def test_unknown_session(repo):
    assert repo.get_session(uuid4()) is None
    with pytest.raises(SessionNotFound):
        repo.issue_next_question(uuid4())


# --- responder --------------------------------------------------------------------------


def test_correct_answer_is_graded_by_the_database(repo, started):
    repo.issue_next_question(started.id)

    attempt = repo.record_answer(started.id, 1, "A")

    assert (attempt.is_correct, attempt.timed_out, attempt.correct_option) == (True, False, "A")
    assert 0 <= attempt.time_used_ms < 5000


def test_wrong_answer_reveals_the_key_only_after_answering(repo, started):
    repo.issue_next_question(started.id)

    attempt = repo.record_answer(started.id, 1, "C")

    assert attempt.is_correct is False
    assert attempt.correct_option == "A"


def test_resubmitting_returns_the_stored_attempt(repo, started):
    repo.issue_next_question(started.id)
    first = repo.record_answer(started.id, 1, "C")

    second = repo.record_answer(started.id, 1, "A")

    assert second == first
    assert second.selected_option == "C"


def test_answer_for_a_question_not_issued(repo, started):
    repo.issue_next_question(started.id)

    with pytest.raises(QuestionNotIssued):
        repo.record_answer(started.id, 2, "A")


@pytest.mark.parametrize("option", ["E", None])
def test_option_outside_the_question_is_rejected_before_the_deadline(repo, started, option):
    repo.issue_next_question(started.id)

    with pytest.raises(InvalidOption):
        repo.record_answer(started.id, 1, option)


def test_answer_after_the_deadline_is_a_timeout(repo, started, seed):
    repo.issue_next_question(started.id)
    seed.age_question(started.id, 1, 100)

    attempt = repo.record_answer(started.id, 1, "A")

    assert (attempt.timed_out, attempt.is_correct, attempt.selected_option) == (True, False, None)
    assert attempt.time_used_ms == 90000


def test_session_completes_after_the_last_answer(repo, started):
    for position in (1, 2, 3):
        repo.issue_next_question(started.id)
        repo.record_answer(started.id, position, "A")

    state = repo.get_session(started.id)

    assert (state.status, state.answered_count) == ("completed", 3)
    with pytest.raises(SessionClosed):
        repo.issue_next_question(started.id)


def test_closed_session_rejects_new_answers_but_returns_stored_ones(repo, started):
    repo.issue_next_question(started.id)
    stored = repo.record_answer(started.id, 1, "A")
    repo.abandon_session(started.id)

    assert repo.record_answer(started.id, 1, "B") == stored
    with pytest.raises(SessionClosed):
        repo.record_answer(started.id, 2, "A")


# --- decisión: next registra el timeout ----------------------------------------------------


def test_next_registers_the_timeout_and_issues_the_following_question(repo, started, seed, db):
    repo.issue_next_question(started.id)
    seed.age_question(started.id, 1, 100)

    following = repo.issue_next_question(started.id)

    assert following.position == 2
    first = db.execute(
        "SELECT timed_out, is_correct, selected_option, time_used_ms FROM public.attempts "
        "WHERE session_id = %s AND position = 1",
        (started.id,),
    ).fetchone()
    assert (first["timed_out"], first["is_correct"], first["selected_option"]) == (True, False, None)
    assert first["time_used_ms"] == 90000
    # La nueva pregunta tiene su propio plazo, en el futuro.
    assert db.execute("SELECT %s > clock_timestamp() AS ok", (following.deadline_at,)).fetchone()["ok"]


def test_next_does_not_register_a_timeout_before_the_deadline(repo, started, db):
    repo.issue_next_question(started.id)

    again = repo.issue_next_question(started.id)

    assert again.position == 1
    assert db.execute("SELECT count(*) AS n FROM public.attempts").fetchone()["n"] == 0


def test_next_after_the_last_timeout_completes_the_session(repo, seed, world, db):
    seed.bank(per_area=1)
    session = make_session(repo, world, mode="random", question_count=1)
    repo.issue_next_question(session.id)
    seed.age_question(session.id, 1, 100)

    with pytest.raises(NothingPending):
        repo.issue_next_question(session.id)

    # El timeout y el cierre se confirmaron aunque se lanzó NothingPending.
    state = repo.get_session(session.id)
    assert (state.status, state.answered_count) == ("completed", 1)
    assert db.execute(
        "SELECT timed_out FROM public.attempts WHERE session_id = %s", (session.id,)
    ).fetchone()["timed_out"] is True


# --- abandonar ---------------------------------------------------------------------------


def test_abandon_is_idempotent_and_blocks_further_play(repo, started):
    first = repo.abandon_session(started.id)
    again = repo.abandon_session(started.id)

    assert first.status == again.status == "abandoned"
    with pytest.raises(SessionClosed):
        repo.issue_next_question(started.id)


def test_a_completed_session_cannot_be_abandoned(repo, seed, world):
    seed.bank(per_area=1)
    session = make_session(repo, world, mode="random", question_count=1)
    repo.issue_next_question(session.id)
    repo.record_answer(session.id, 1, "A")

    with pytest.raises(SessionClosed):
        repo.abandon_session(session.id)


# --- B1: hora del servidor --------------------------------------------------------------------


def test_server_now_comes_from_the_database_clock(repo, started, db):
    question = repo.issue_next_question(started.id)

    # server_now sale de la base, justo después de emitir: queda ~90 s de plazo.
    remaining = (question.deadline_at - question.server_now).total_seconds()
    assert 85 < remaining <= 90

    state = repo.get_session(started.id)
    assert state.server_now >= question.server_now


# --- B3: intentos de la sesión --------------------------------------------------------------------


def test_list_attempts_returns_only_closed_positions_with_their_key(repo, started):
    repo.issue_next_question(started.id)
    assert repo.list_attempts(started.id) == []  # la pendiente no aparece

    repo.record_answer(started.id, 1, "C")
    repo.issue_next_question(started.id)  # pregunta 2 abierta

    attempts = repo.list_attempts(started.id)

    assert [a.position for a in attempts] == [1]
    assert (attempts[0].is_correct, attempts[0].correct_option) == (False, "A")


def test_list_attempts_includes_timeouts_registered_by_next(repo, started, seed):
    repo.issue_next_question(started.id)
    seed.age_question(started.id, 1, 100)
    repo.issue_next_question(started.id)

    attempts = repo.list_attempts(started.id)

    assert (attempts[0].timed_out, attempts[0].selected_option) == (True, None)


# --- B2: ranking del equipo -----------------------------------------------------------------------


def test_ranking_lists_only_the_team_ordered_with_unranked_last(repo, seed, world):
    seed.bank(per_area=5)
    teammate = seed.user(world["team"])
    other_team = seed.team()
    seed.user(other_team)  # alguien de otro equipo: no debe aparecer

    # world["user"] completa 20 preguntas; el compañero no responde nada.
    session = make_session(repo, world, mode="random", question_count=20)
    for position in range(1, 21):
        repo.issue_next_question(session.id)
        repo.record_answer(session.id, position, "A")

    rows = repo.ranking(world["team"])

    assert [r.user_id for r in rows] == [world["user"], teammate]
    assert (rows[0].rank_position, rows[0].questions_seen, rows[0].correct_count) == (1, 20, 20)
    assert rows[0].accuracy_pct == 100.0
    assert rows[1].rank_position is None
    assert (rows[1].questions_seen, rows[1].accuracy_pct) == (0, None)
    assert repo.ranking(uuid4()) == []


# --- extremo a extremo con el ranking --------------------------------------------------------


def test_twenty_answers_through_the_repository_reach_the_ranking(repo, seed, world, db):
    seed.bank(per_area=5)
    session = make_session(repo, world, mode="random", question_count=20)

    for position in range(1, 21):
        repo.issue_next_question(session.id)
        repo.record_answer(session.id, position, "A")

    row = db.execute(
        "SELECT rank_position, questions_seen, correct_count FROM public.practice_ranking "
        "WHERE user_id = %s",
        (world["user"],),
    ).fetchone()
    assert (row["rank_position"], row["questions_seen"], row["correct_count"]) == (1, 20, 20)
