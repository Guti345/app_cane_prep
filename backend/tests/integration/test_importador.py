"""Importador del banco (scripts/importar_banco.py).

Las pruebas de plan son puras (sin base de datos); las de carga usan PGlite con
las migraciones reales. Todo con preguntas ficticias: nada depende de
private-data, salvo la prueba de lectura de lotes, que usa el esquema si existe.
"""

import json
from copy import deepcopy
from pathlib import Path

import psycopg
import pytest

OPTIONS = [{"label": c, "text_md": f"opción {c}"} for c in "ABCD"]


def q(area, number, *, status="ready", correct="A", warnings=None, assets=None, bank="cane-2026"):
    """Una pregunta ya leída de un lote (con las marcas internas que añade el lector)."""
    return {
        "id": f"{bank}-{area}-{number:03d}",
        "area": area,
        "source_number": number,
        "source_pages": [number],
        "source_year": 2026,
        "source_edition": None,
        "source_phase": None,
        "statement_md": f"Enunciado ficticio {area} {number}",
        "assets": assets or [],
        "options": deepcopy(OPTIONS),
        "correct_option": correct,
        "review_status": status,
        "warnings": warnings or [],
        "_bank_id": bank,
        "_batch": f"{area}_01",
    }


WARNING = [{"code": "other", "location": "x", "detail": "y"}]

# 10 preguntas: 5 activas, 4 inactivas, 1 descartada.
def bank():
    return [
        q("econometria", 1), q("econometria", 2), q("econometria", 3),
        q("econometria", 4, status="needs_review", correct=None, warnings=WARNING),
        q("econometria", 5),
        q("macroeconomia", 1), q("macroeconomia", 2),
        q("microeconomia", 1, status="needs_review", warnings=WARNING),
        q("microeconomia", 2, status="needs_review", warnings=WARNING),
        q("microeconomia", 3, status="needs_review", warnings=WARNING),
    ]


CURATION = {
    "verified_basis": "decision_bloque_ready_2026-10-12",
    "inactive": [
        {"reason": "sin_clave", "questions": {"econometria": [4]}},
        {"reason": "texto_dudoso", "questions": {"econometria": [5]}},
    ],
    "duplicates": [{"area": "macroeconomia", "number": 2, "of": 1}],
    "force_active": [{"area": "microeconomia", "number": 1, "note": "Confirmada por Antonio."}],
    "discarded": [{"area": "microeconomia", "number": 2, "reason": "duplicada_de", "of": 1}],
    "expected": {
        "total": 10, "active": 5, "inactive": 4, "discarded": 1,
        "inactive_by_reason": {"sin_clave": 1, "texto_dudoso": 1, "duplicada_de": 1,
                               "revisar_no_clasificada": 1},
    },
}


def plan_of(importer, questions=None, curation=None):
    return importer.build_plan(questions or bank(), curation or CURATION)


def by_number(plan, area, number):
    return next(p for p in plan if p.area == area and p.number == number)


# --- plan: clasificación -----------------------------------------------------------------


def test_default_ready_question_is_active_and_verified(importer):
    p = by_number(plan_of(importer), "econometria", 1)
    assert (p.state, p.reason, p.verified) == ("active", None, True)


def test_listed_questions_are_inactive_with_their_reason(importer):
    plan = plan_of(importer)
    # econometria 5 es ready y con clave, pero está en la lista: gana la lista.
    p = by_number(plan, "econometria", 5)
    assert (p.state, p.reason, p.verified) == ("inactive", "texto_dudoso", False)
    assert by_number(plan, "econometria", 4).reason == "sin_clave"


def test_unlisted_needs_review_is_inactive_and_reported(importer):
    plan = plan_of(importer)
    p = by_number(plan, "microeconomia", 3)
    assert (p.state, p.reason, p.verified) == ("inactive", "revisar_no_clasificada", False)
    assert [(x.area, x.number) for x in importer.summarize(plan).unclassified] == [("microeconomia", 3)]


def test_duplicate_is_inactive_and_points_to_the_kept_question(importer):
    p = by_number(plan_of(importer), "macroeconomia", 2)
    assert (p.state, p.reason, p.duplicate_of) == ("inactive", "duplicada_de", "cane-2026-macroeconomia-001")


def test_duplicate_that_is_already_listed_keeps_its_reason_and_records_the_parent(importer):
    questions = bank() + [q("macroeconomia", 3, status="needs_review", warnings=WARNING)]
    curation = deepcopy(CURATION)
    curation["inactive"].append({"reason": "texto_dudoso", "questions": {"macroeconomia": [3]}})
    curation["duplicates"].append({"area": "macroeconomia", "number": 3, "of": 1})
    curation["expected"] = {**curation["expected"], "total": 11, "inactive": 5,
                            "inactive_by_reason": {**curation["expected"]["inactive_by_reason"],
                                                   "texto_dudoso": 2}}
    p = by_number(plan_of(importer, questions, curation), "macroeconomia", 3)
    assert (p.reason, p.duplicate_of) == ("texto_dudoso", "cane-2026-macroeconomia-001")


def test_forced_active_overrides_needs_review_and_keeps_the_original_warnings(importer):
    p = by_number(plan_of(importer), "microeconomia", 1)
    assert (p.state, p.review_status, p.warnings, p.verified) == ("active", "ready", [], True)
    assert "Confirmada por Antonio." in p.note and "needs_review" in p.note and '"code": "other"' in p.note


def test_discarded_keeps_a_trace_of_what_it_duplicates(importer):
    p = by_number(plan_of(importer), "microeconomia", 2)
    assert (p.state, p.reason, p.duplicate_of, p.verified) == (
        "discarded", "duplicada_de", "cane-2026-microeconomia-001", False)


def test_summary_matches_expected_counts(importer):
    summary = importer.summarize(plan_of(importer))
    assert importer.check_expected(summary, CURATION["expected"]) == []
    assert dict(summary.by_state) == {"active": 5, "inactive": 4, "discarded": 1}


def test_expected_mismatch_is_reported_not_hidden(importer):
    expected = {**CURATION["expected"], "active": 6}
    diffs = importer.check_expected(importer.summarize(plan_of(importer)), expected)
    assert diffs == ["active: esperado 6, resultado 5"]


# --- plan: errores -------------------------------------------------------------------------


def test_listed_question_missing_from_the_batches_is_a_clear_error(importer):
    curation = deepcopy(CURATION)
    curation["inactive"][0]["questions"]["econometria"].append(99)
    with pytest.raises(importer.ImportPlanError) as exc:
        plan_of(importer, curation=curation)
    assert any("econometria 99 no existe" in p for p in exc.value.problems)


def test_duplicates_must_share_the_key_and_keep_the_lower_number(importer):
    questions = bank()
    questions[6]["correct_option"] = "B"  # macroeconomia 2 con otra clave
    with pytest.raises(importer.ImportPlanError) as exc:
        plan_of(importer, questions)
    assert any("no comparten clave" in p for p in exc.value.problems)

    curation = deepcopy(CURATION)
    curation["duplicates"] = [{"area": "macroeconomia", "number": 1, "of": 2}]
    with pytest.raises(importer.ImportPlanError) as exc:
        plan_of(importer, curation=curation)
    assert any("número menor" in p for p in exc.value.problems)


def test_question_listed_twice_or_forced_and_inactive_is_rejected(importer):
    curation = deepcopy(CURATION)
    curation["inactive"].append({"reason": "texto_dudoso", "questions": {"econometria": [4]}})
    curation["inactive"].append({"reason": "texto_dudoso", "questions": {"microeconomia": [1]}})
    with pytest.raises(importer.ImportPlanError) as exc:
        plan_of(importer, curation=curation)
    text = "\n".join(exc.value.problems)
    assert "econometria 4: aparece en dos listas" in text
    assert "microeconomia 1: está en force_active y en una lista" in text


def test_active_without_verified_at_fails_validation(importer):
    plan = plan_of(importer)
    broken = [p if p is not plan[0] else importer.Planned(
        q=p.q, state="active", reason=None, duplicate_of=None, note=None,
        review_status="ready", warnings=[], verified=False) for p in plan]
    with pytest.raises(importer.ImportPlanError) as exc:
        importer.validate_plan(broken)
    assert any("activa sin verified_at" in p for p in exc.value.problems)


def test_inactive_without_reason_fails_validation(importer):
    plan = plan_of(importer)
    p = by_number(plan, "econometria", 5)
    broken = [x if x is not p else importer.Planned(
        q=p.q, state="inactive", reason=None, duplicate_of=None, note=None,
        review_status=p.review_status, warnings=p.warnings, verified=False) for x in plan]
    with pytest.raises(importer.ImportPlanError) as exc:
        importer.validate_plan(broken)
    assert any("inactive sin motivo" in p for p in exc.value.problems)


# --- destino: protección ---------------------------------------------------------------------


def test_target_guard(importer):
    assert importer.check_target("postgresql://postgres:x@127.0.0.1:5432/postgres", False) == "local"
    assert importer.check_target("postgresql://postgres:x@db.otroproyecto.supabase.co/postgres", True) == "remoto"
    with pytest.raises(SystemExit) as exc:
        importer.check_target("postgresql://postgres:secreto@db.otroproyecto.supabase.co/postgres", False)
    assert "secreto" not in str(exc.value)  # nunca devuelve credenciales
    ref = importer.BLOCKED_PROJECT_REFS[0]
    for dsn in (f"postgresql://postgres:x@db.{ref}.supabase.co/postgres",
                f"postgresql://postgres.{ref}:x@aws-0-eu.pooler.supabase.com/postgres"):
        with pytest.raises(SystemExit, match="proyecto real"):
            importer.check_target(dsn, True)  # ni siquiera con --remoto


# --- lectura de lotes ----------------------------------------------------------------------------


@pytest.fixture
def schema(importer):
    if not importer.DEFAULT_SCHEMA.exists():
        pytest.skip("private-data/esquema_preguntas_schema.json no existe en esta máquina")
    return json.loads(importer.DEFAULT_SCHEMA.read_text(encoding="utf-8"))


def write_batch(root: Path, name: str, questions: list[dict], assets: dict[str, bytes] | None = None):
    clean = [{k: v for k, v in x.items() if not k.startswith("_")} for x in questions]
    folder = root / name
    (folder / "assets").mkdir(parents=True)
    (folder / f"{name}.json").write_text(json.dumps({
        "schema_version": "1.0", "bank_id": "cane-2026",
        "questions": clean, "pending_questions": [],
    }), encoding="utf-8")
    for fname, data in (assets or {}).items():
        (folder / "assets" / fname).write_bytes(data)


def test_batches_are_read_and_problems_are_collected(importer, schema, tmp_path):
    ok = q("econometria", 1)
    with_asset = q("econometria", 2, assets=[{
        "ref": "assets/cane-2026-econometria-002-fig-01.png", "kind": "figure",
        "alt": "figura", "source_page": 1, "status": "available"}])
    write_batch(tmp_path, "econometria_01", [ok, with_asset],
                {"cane-2026-econometria-002-fig-01.png": b"png"})
    questions, pending, problems = importer.load_batches(tmp_path, schema)
    assert (len(questions), pending, problems) == (2, 0, [])

    # el archivo del recurso falta, el id se repite en otro lote y la clave no es una opción
    bad = q("econometria", 3, correct="E")
    write_batch(tmp_path, "econometria_02", [with_asset, bad])
    _, _, problems = importer.load_batches(tmp_path, schema)
    text = "\n".join(problems)
    assert "falta el archivo del recurso" in text
    assert "id repetido" in text
    assert "la clave E no está entre las opciones" in text


def test_no_batches_is_an_error_not_a_silent_empty_import(importer, schema, tmp_path):
    _, _, problems = importer.load_batches(tmp_path, schema)
    assert problems and "No hay lotes" in problems[0]


# --- carga en PostgreSQL (migraciones reales) ---------------------------------------------------------


@pytest.fixture
def loader(db, importer):
    # Como en producción: los triggers de clave/verificación se evalúan al final.
    db.execute("SET CONSTRAINTS ALL DEFERRED")

    def run(plan=None, **kwargs):
        return importer.apply_plan(
            db, plan or plan_of(importer), CURATION["verified_basis"], **kwargs
        )

    return run


def rows(db):
    return {r["source_id"]: r for r in db.execute(
        "SELECT q.*, k.correct_option AS key, k.verified_at, k.verified_basis "
        "FROM public.questions q JOIN public.question_keys k ON k.question_id = q.id "
        "WHERE q.bank_id = 'cane-2026'").fetchall()}


def test_load_inserts_questions_and_keys_with_the_planned_state(loader, db):
    result = loader()
    assert (result.before["total"], result.after["total"], result.inserted) == (0, 10, 10)
    assert (result.after["active"], result.after["inactive"], result.after["discarded"]) == (5, 4, 1)

    got = rows(db)
    assert len(got) == 10  # una fila de clave por pregunta
    active = got["cane-2026-econometria-001"]
    assert active["active"] and active["key"] == "A"
    assert active["verified_at"] is not None
    assert active["verified_basis"] == "decision_bloque_ready_2026-10-12"
    # sin clave: la fila existe con clave nula y sin verificación
    no_key = got["cane-2026-econometria-004"]
    assert (no_key["active"], no_key["key"], no_key["verified_at"]) == (False, None, None)
    assert no_key["review_reason"] == "sin_clave" and no_key["review_status"] == "needs_review"
    # inactiva con clave: la clave se conserva, pero no queda verificada
    dudosa = got["cane-2026-econometria-005"]
    assert (dudosa["active"], dudosa["key"], dudosa["verified_at"]) == (False, "A", None)
    # activada a mano: ready y sin avisos en la base; los avisos de origen quedan en la nota
    forced = got["cane-2026-microeconomia-001"]
    assert forced["active"] and forced["review_status"] == "ready" and forced["warnings"] == []
    assert "Confirmada por Antonio." in forced["review_note"]
    # descartada
    dropped = got["cane-2026-microeconomia-002"]
    assert (dropped["discarded"], dropped["active"]) == (True, False)
    assert dropped["duplicate_of"] == "cane-2026-microeconomia-001"
    # toda activa lleva verificación; ninguna no activa la lleva
    assert all((r["verified_at"] is not None) == r["active"] for r in got.values())
    # todas las activas con la misma marca de tiempo (la del import)
    assert len({r["verified_at"] for r in got.values() if r["active"]}) == 1


def test_questions_table_has_no_answer_column(db):
    cols = {r["column_name"] for r in db.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'questions'").fetchall()}
    assert not {c for c in cols if "correct" in c or c in {"key", "answer"}}


def test_rerun_inserts_nothing_and_changes_nothing(loader, db):
    loader()
    before = rows(db)
    result = loader()
    assert (result.inserted, result.existing_skipped) == (0, 10)
    assert result.state_differs == [] and result.content_drift == []
    assert rows(db) == before


def test_rerun_respects_manual_changes_made_in_supabase(loader, db, importer):
    loader()
    # Antonio desactiva una activa y activa (con su verificación) una inactiva.
    db.execute("UPDATE public.questions SET active = false, review_reason = 'revisado' "
               "WHERE source_id = 'cane-2026-econometria-001'")
    db.execute("UPDATE public.question_keys SET verified_at = now() "
               "WHERE question_id = (SELECT id FROM public.questions WHERE source_id = 'cane-2026-econometria-005')")
    db.execute("UPDATE public.questions SET active = true "
               "WHERE source_id = 'cane-2026-econometria-005'")
    snapshot = rows(db)

    result = loader()

    assert result.inserted == 0 and result.forced == []
    assert sorted(result.state_differs) == [
        "cane-2026-econometria-001: base=inactive, plan=active",
        "cane-2026-econometria-005: base=active, plan=inactive",
    ]
    assert rows(db) == snapshot  # el importador no pisó nada


def test_force_state_reapplies_the_plan_to_existing_questions(loader, db):
    loader()
    db.execute("UPDATE public.questions SET active = false WHERE source_id = 'cane-2026-econometria-001'")
    result = loader(force_state=True)
    assert result.forced == ["cane-2026-econometria-001"]
    assert rows(db)["cane-2026-econometria-001"]["active"] is True


def test_changed_content_is_reported_and_never_overwritten(loader, db, importer):
    loader()
    edited = bank()
    edited[0]["statement_md"] = "Enunciado corregido en el archivo"
    result = loader(plan_of(importer, edited))
    assert result.content_drift == ["cane-2026-econometria-001"]
    assert rows(db)["cane-2026-econometria-001"]["statement_md"] == "Enunciado ficticio econometria 1"


def test_trial_run_reverts_everything(loader, db):
    result = loader(dry_run=True)
    assert result.rolled_back and result.after["total"] == 10
    assert db.execute("SELECT count(*) AS n FROM public.questions WHERE bank_id = 'cane-2026'").fetchone()["n"] == 0


def test_database_rejects_an_active_question_without_verified_at(loader, db, importer):
    """Aunque el plan se saltara la validación, la base (regla D5) lo impide y no queda nada."""
    plan = plan_of(importer)
    first = plan[0]
    plan[0] = importer.Planned(q=first.q, state="active", reason=None, duplicate_of=None,
                               note=None, review_status="ready", warnings=[], verified=False)
    with pytest.raises(psycopg.errors.RaiseException, match="verified_at"):
        loader(plan)
    assert db.execute("SELECT count(*) AS n FROM public.questions WHERE bank_id = 'cane-2026'").fetchone()["n"] == 0


def test_a_question_cannot_be_discarded_and_active(loader, db):
    loader()
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE public.questions SET active = true "
                   "WHERE source_id = 'cane-2026-microeconomia-002'")


def expect_error_in_server(db, statement: str, contains: str) -> None:
    """Ejecuta `statement` y exige que falle con `contains`, capturando el error EN el servidor.

    PGlite deja sin respuesta el ROLLBACK de un savepoint cuando el cliente captura
    un RAISE EXCEPTION de un trigger de UPDATE y desincroniza la conexión compartida.
    Capturarlo en un bloque DO evita ese error de protocolo; el resultado es el mismo.
    """
    db.execute(
        "DO $t$ BEGIN " + statement + "; RAISE EXCEPTION 'NO_FALLO'; "
        "EXCEPTION WHEN raise_exception THEN "
        "IF SQLERRM NOT LIKE '%" + contains + "%' THEN RAISE; END IF; END $t$"
    )


def test_editorial_state_can_change_on_a_used_question_but_content_cannot(db, seed, repo):
    team = seed.team()
    user = seed.user(team)
    seed.bank(1)
    repo.create_session(user_id=user, team_id=team, mode="random", area=None, stage=None,
                        question_count=3)
    used = db.execute("SELECT question_id FROM public.session_questions LIMIT 1").fetchone()["question_id"]

    db.execute("UPDATE public.questions SET discarded = false, review_reason = 'revisada', "
               "review_note = 'nota', duplicate_of = 'otra' WHERE id = %s", (used,))
    expect_error_in_server(
        db, f"UPDATE public.questions SET statement_md = 'otro' WHERE id = '{used}'", "Versión usada"
    )
    # y la clave tampoco se puede cambiar
    expect_error_in_server(
        db, f"UPDATE public.question_keys SET correct_option = 'B' WHERE question_id = '{used}'",
        "Versión usada",
    )
