"""Los dos SQL de la prueba de la migración 4 (docs/prueba-migracion-4-*.sql).

Se ejecutan SOLO contra PostgreSQL local (PGlite). Aquí se comprueba que el SQL que se le dará
a una persona para pruebas_cane (a) es de solo lectura, (b) deja el rol como estaba, (c) falla
si el residuo existe y (d) pasa, con las mismas huellas que la línea base, tras la migración.
"""

import re
import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_migracion_service_role import (  # noqa: E402
    FILES, NEW, PREVIOUS, install, seed_secrets,
)

DOCS = Path(__file__).resolve().parents[3] / "docs"
BASELINE = DOCS / "prueba-migracion-4-baseline.sql"
REVOKE = DOCS / "prueba-migracion-4-revoke.sql"


def code(path: Path) -> str:
    lines = [line.split("--", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()]
    return re.sub(r"'(?:[^']|'')*'", "''", "\n".join(lines))


def run_script(db, path: Path) -> list[dict]:
    """Ejecuta un archivo de varias sentencias y devuelve las filas de la ÚLTIMA."""
    cur = db.execute(path.read_text(encoding="utf-8"))
    while cur.nextset():
        pass
    return cur.fetchall()


def table(rows: list[dict]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        out.setdefault(r["seccion"], {})[r["elemento"]] = r["valor"]
    return out


# --- son de solo lectura y no filtran nada ----------------------------------------------------


@pytest.mark.parametrize("path", [BASELINE, REVOKE], ids=["baseline", "revoke"])
def test_the_sql_never_writes(path):
    sql = code(path)

    for word in ("INSERT", "UPDATE", "DELETE", "GRANT", "REVOKE", "CREATE", "ALTER", "DROP",
                 "TRUNCATE", "COPY", "VACUUM", "REINDEX", "COMMENT"):
        assert not re.search(rf"\b{word}\b", sql, re.I), (path.name, word)


def test_the_baseline_never_changes_role_or_runs_blocks():
    sql = code(BASELINE)

    assert not re.search(r"\bSET\b|\bRESET\b|\bDO\b|\bBEGIN\b|\bCOMMIT\b", sql, re.I)
    assert sql.count(";") == 1  # una sola sentencia, solo un SELECT


def test_the_effective_test_is_scoped_and_reads_nothing():
    sql = REVOKE.read_text(encoding="utf-8")
    block = sql[sql.index("DO $prueba$"):sql.index("$prueba$;")]

    assert block.count("SET LOCAL ROLE service_role") == 1  # LOCAL: no sobrevive a la transacción
    assert not re.search(r"\bSET\s+ROLE\b", block)  # nunca SET ROLE de sesión
    assert block.count("PERFORM 1 FROM") == 2 and "LIMIT 1" in block  # no devuelve filas
    assert not re.search(r"\bSELECT\b[^;]*\bcorrect_option\b|\bdata\b\s+FROM", block, re.I)
    assert sql.count("RESET ROLE") >= 2  # dentro del bloque y después


def test_the_output_columns_cannot_carry_answers_or_bytes():
    for path in (BASELINE, REVOKE):
        sql = code(path)
        assert "correct_option" not in sql
        for forbidden in ("octet_length", "encode(", "convert_from", "access_token"):
            assert forbidden not in sql, (path.name, forbidden)
        # Ninguna columna de datos de las dos tablas se lee en el resultado: fuera del bloque DO
        # (que solo hace PERFORM 1 ... LIMIT 1) no hay ningún FROM sobre ellas.
        outside_do = re.sub(r"DO \$prueba\$.*?\$prueba\$;", "", sql, flags=re.S)
        assert not re.search(r"FROM\s+public\.question_(keys|assets)\b", outside_do, re.I), path.name


# --- comportamiento local -----------------------------------------------------------------------


@pytest.fixture
def before(db, seed):
    """Las tres migraciones previas con defaults de Supabase y datos ficticios (estado de pruebas_cane)."""
    install(db, PREVIOUS)
    seed_secrets(db, seed)
    return db


def test_the_baseline_shows_the_residue_and_runs_as_a_single_result(before):
    out = table(run_script(before, BASELINE))

    acl = out["acl_tabla"]
    assert "public.question_keys -> service_role" in acl
    assert "public.question_assets -> service_role" in acl
    assert out["rol_service_role"]["atributos"].endswith("bypassrls=true")
    effective = out["privilegios_efectivos"]
    assert "SELECT" in effective["service_role sobre public.question_keys"]
    assert effective["anon sobre public.question_keys"] == "(ninguno)"
    # El rol que hereda de service_role aparece con acceso, marcado como heredero.
    assert any(k.startswith("heredero ->") and "hereda de service_role" in v
               for k, v in out["acceso_efectivo_a_secretos"].items())
    assert set(out["huellas"]) == {"acl_resto", "acl_columnas_resto", "estructura", "efectivos_resto"}


def test_the_verification_fails_loudly_while_the_residue_exists(before):
    # La prueba efectiva lanza FALLO: aquí service_role SÍ puede consultar.
    with pytest.raises(psycopg.errors.RaiseException, match="FALLO"):
        run_script(before, REVOKE)
    before.rollback()  # la transacción abortó; no queda ningún rol cambiado
    assert before.execute("SELECT current_user AS u, session_user AS s").fetchone() == {
        "u": "postgres", "s": "postgres"}


def test_after_the_migration_everything_passes_and_the_fingerprints_match_the_baseline(before):
    baseline = table(run_script(before, BASELINE))
    before.execute(NEW[0].read_text(encoding="utf-8"))

    after = table(run_script(before, REVOKE))

    checks = after["verificaciones"]
    assert len(checks) == 8
    assert all(v.startswith("PASS") for v in checks.values()), checks
    # Todo lo demás igual: las huellas coinciden con la línea base (calculadas SIN las 2 entradas).
    assert after["huellas"] == baseline["huellas"]
    # Y las entradas de service_role sobre las 2 tablas desaparecieron del detalle.
    assert not any("service_role" in k and "question_" in k for k in after["acl_tabla"])
    assert "public.question_keys -> service_role" in baseline["acl_tabla"]
    assert after["privilegios_efectivos"]["service_role sobre public.question_keys"] == "(ninguno)"
    assert after["privilegios_columna_efectivos"]["service_role sobre public.question_assets"] == "(ninguno)"
    # service_role conserva lo que no era alcance de la migración.
    assert "SELECT" in after["privilegios_efectivos"]["service_role sobre public.questions"]
    # El rol no quedó cambiado.
    assert before.execute("SELECT current_user AS u").fetchone()["u"] == "postgres"


def test_a_partial_revoke_is_caught_by_the_catalog_checks(before):
    before.execute("REVOKE SELECT ON TABLE public.question_keys, public.question_assets FROM service_role")

    checks = table(run_script(before, REVOKE))["verificaciones"]

    assert checks[next(k for k in checks if k.startswith("V1"))] == "FAIL"  # INSERT/UPDATE/... siguen
    assert checks[next(k for k in checks if k.startswith("V3"))] == "FAIL"  # ACL directa residual


def test_inheritance_and_public_paths_are_detected(before):
    before.execute(NEW[0].read_text(encoding="utf-8"))
    before.execute("GRANT SELECT ON public.question_keys TO heredero")  # alguien hereda y accede

    checks = table(run_script(before, REVOKE))["verificaciones"]

    assert checks[next(k for k in checks if k.startswith("V5"))] == "FAIL"
    assert checks[next(k for k in checks if k.startswith("V1"))] == "PASS"  # service_role sigue sin acceso
