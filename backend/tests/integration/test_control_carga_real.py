"""docs/control-carga-real.sql: de solo lectura, solo agregados y correcto sobre una carga local."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_importador import CURATION, bank, plan_of, with_figure  # noqa: E402

SQL = Path(__file__).resolve().parents[3] / "docs" / "control-carga-real.sql"


def code() -> str:
    lines = [line.split("--", 1)[0] for line in SQL.read_text(encoding="utf-8").splitlines()]
    return re.sub(r"'(?:[^']|'')*'", "''", "\n".join(lines))


def run(db) -> dict[str, dict[str, str]]:
    db.execute("SET LOCAL transaction_read_only = on")  # cualquier escritura fallaría
    out: dict[str, dict[str, str]] = {}
    for r in db.execute(SQL.read_text(encoding="utf-8")).fetchall():
        out.setdefault(r["seccion"], {})[r["elemento"]] = r["valor"]
    return out


def test_it_is_one_read_only_select_that_returns_only_aggregates():
    sql = code()

    assert sql.strip().upper().startswith("SELECT") and sql.count(";") == 1
    for word in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "GRANT",
                 "REVOKE", "SET", "DO", "COPY"):
        assert not re.search(rf"\b{word}\b", sql, re.I), word
    # Ninguna columna de contenido se devuelve; correct_option solo se usa como IS [NOT] NULL.
    for column in ("statement_md", "options", "display_name", "email", "raw_user_meta"):
        assert not re.search(rf"\b{column}\b", sql, re.I), column
    for use in re.finditer(r"\bcorrect_option\b(?!\s+IS\s+(?:NOT\s+)?NULL)", sql, re.I):
        pytest.fail(f"correct_option se usa más allá de IS [NOT] NULL: {sql[use.start():use.start() + 40]}")
    # `data` solo dentro de octet_length(...): nunca los bytes.
    assert not re.search(r"\bdata\b(?!\))", sql.replace("octet_length(data)", ""), re.I)


def test_on_an_empty_database_everything_is_zero(db):
    out = run(db)

    assert out["preguntas"]["total"].startswith("0 ")
    assert out["claves"]["filas en question_keys"].startswith("0 ")
    assert out["figuras"]["bytes (suma)"].startswith("0 ")
    for key in ("sesiones", "intentos", "posiciones de sesion"):
        assert out["juego"][key].startswith("0 ")
    assert out["auth"]["cuentas (solo el total)"].startswith("0 ")


def test_after_a_local_load_the_counts_match_the_plan(db, importer, tmp_path):
    db.execute("SET CONSTRAINTS ALL DEFERRED")
    plan = with_figure(importer, tmp_path)
    importer.apply_plan(db, plan, CURATION["verified_basis"])

    out = run(db)

    assert out["preguntas"]["total"].startswith(f"{len(bank())} ")
    assert out["preguntas"]["activas"].startswith("5 ")
    assert out["preguntas"]["inactivas (no descartadas)"].startswith("4 ")
    assert out["preguntas"]["descartadas"].startswith("1 ")
    assert out["claves"]["filas en question_keys"].startswith(f"{len(bank())} ")
    assert out["claves"]["activas con clave nula o sin verified_at"].startswith("0 ")
    assert out["claves"]["activas sin verified_basis"].startswith("0 ")
    assert out["claves"]["no activas con verified_at"].startswith("0 ")
    assert out["claves_verified_basis"][CURATION["verified_basis"]] == "5"
    assert out["claves_verified_basis"]["(nulo)"] == str(len(bank()) - 5)
    assert out["motivos"]["no activas sin review_reason"].startswith("0 ")
    assert out["duplicadas"]["con duplicate_of"].startswith("2 ")  # duplicada + descartada
    assert out["figuras"]["filas en question_assets"].startswith("1 ")
    assert out["figuras"]["preguntas con figura"].startswith("1 ")
    assert out["preguntas"]["bank_id distintos"] == "cane-2026"
    # Y NO hay nada de juego: la carga del banco no copia sesiones, intentos ni equipos.
    for key in ("sesiones", "intentos", "posiciones de sesion"):
        assert out["juego"][key].startswith("0 ")
    assert out["equipos"]["equipos"].startswith("0 ") and out["equipos"]["perfiles"].startswith("0 ")


def test_a_trial_run_leaves_the_control_at_zero(db, importer, tmp_path):
    db.execute("SET CONSTRAINTS ALL DEFERRED")
    plan = with_figure(importer, tmp_path)
    result = importer.apply_plan(db, plan, CURATION["verified_basis"], dry_run=True)

    out = run(db)

    assert result.rolled_back is True
    assert out["preguntas"]["total"].startswith("0 ")
    assert out["claves"]["filas en question_keys"].startswith("0 ")
    assert out["figuras"]["filas en question_assets"].startswith("0 ")
