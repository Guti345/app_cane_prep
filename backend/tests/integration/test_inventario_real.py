"""Los dos SQL de inventario del proyecto real: solo lectura, y robustos si no hay nada.

Se ejecutan contra el PostgreSQL local (PGlite) con las migraciones reales. Nada de esto
toca Supabase: es la comprobación de que el SQL que se le dará a una persona para el
proyecto real no escribe, no falla cuando el proyecto está vacío o a medias, y distingue
"NO EXISTE" de "existe pero no se puede leer".
"""

import re
from collections import defaultdict
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[3] / "docs"
STAGE_1 = DOCS / "inventario-real-1-catalogo.sql"
STAGE_2 = DOCS / "inventario-real-2-conteos.sql"

TABLES = (
    "teams", "profiles", "questions", "question_keys", "sessions",
    "session_questions", "attempts", "question_assets", "practice_ranking",
)
FUNCTIONS = (
    "limit_team_size", "valid_options", "valid_pages", "check_question_key",
    "freeze_used_question", "validate_session_question", "grade_attempt",
    "reject_attempt_update", "finish_session",
)
TRIGGERS = (
    "profiles_limit", "questions_key_check", "keys_question_check", "questions_freeze",
    "keys_freeze", "session_questions_guard", "attempts_grade", "attempts_immutable",
    "sessions_finish", "question_assets_freeze",
)
INDEXES = ("questions_pool", "sessions_person", "attempts_session")
COLUMNS = (
    "questions.discarded", "questions.review_reason", "questions.duplicate_of",
    "questions.review_note", "question_keys.verified_basis",
)


def code_of(path: Path) -> str:
    """El SQL sin comentarios ni literales de texto (para analizarlo como código)."""
    lines = [line.split("--", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()]
    return re.sub(r"'(?:[^']|'')*'", "''", "\n".join(lines))


def run_sql(db, sql: str):
    # Cualquier escritura fallaría con "cannot execute ... in a read-only transaction".
    db.execute("SET LOCAL transaction_read_only = on")
    return db.execute(sql).fetchall()


def stage1(db):
    """Ejecuta la etapa 1 y devuelve {seccion: {elemento: valor}}."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for r in run_sql(db, STAGE_1.read_text(encoding="utf-8")):
        out[r["seccion"]][r["elemento"]] = r["valor"]
    return out


def drop_cane(db) -> None:
    """Vacía el esquema dentro de la transacción de la prueba (se revierte al terminar)."""
    db.execute("DROP VIEW public.practice_ranking")
    for table in ("attempts", "session_questions", "sessions", "question_assets",
                  "question_keys", "questions", "profiles", "teams"):
        db.execute(f"DROP TABLE public.{table} CASCADE")
    db.execute("DROP SCHEMA cane_private CASCADE")


# --- las dos etapas: solo lectura -----------------------------------------------------------


def test_stage1_is_a_single_read_only_catalog_select():
    sql = code_of(STAGE_1)

    assert re.match(r"\s*(WITH|SELECT)\b", sql, re.IGNORECASE)
    assert sql.count(";") == 1 and sql.strip().endswith(";")  # una sola sentencia
    for word in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
                 "GRANT", "REVOKE", "COPY", "DO", "CALL", "EXECUTE", "SET", "COMMENT",
                 "REINDEX", "VACUUM", "LOCK", "REFRESH", "NOTIFY", "PREPARE"):
        assert not re.search(rf"\b{word}\b", sql, re.IGNORECASE), word


def test_stage1_never_reads_a_table_of_the_application_or_of_auth():
    """Solo catálogo: ninguna relación de CANE ni de Auth aparece tras FROM/JOIN."""
    sql = code_of(STAGE_1)
    relations = re.findall(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", sql, re.IGNORECASE)

    assert relations, "no se detectó ninguna relación"
    for name in relations:
        assert name.startswith("pg_") or "." not in name, name  # CTE, alias o catálogo
        assert not re.match(r"(public|cane_private|auth|storage|supabase_migrations)\.", name), name
    for forbidden in ("auth.users", "public.", "cane_private.", "to_regclass", "query_to_xml",
                      "dblink", "pg_read_file", "current_setting"):
        assert forbidden not in sql, forbidden


def test_stage1_returns_only_metadata():
    sql = code_of(STAGE_1)

    for column in ("correct_option", "statement_md", "display_name", "email", "password",
                   "encrypted_password", "raw_user_meta", "access_token", "api_key"):
        assert column not in sql, column


def test_stage2_blocks_are_independent_read_only_selects():
    blocks = stage2_blocks()

    assert len(blocks) == 12
    for number, (requires, sql) in blocks.items():
        code = re.sub(r"'(?:[^']|'')*'", "''", sql)
        assert code.strip().upper().startswith("SELECT"), number
        assert code.count(";") == 1 and code.strip().endswith(";"), number
        for word in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "SET"):
            assert not re.search(rf"\b{word}\b", code, re.IGNORECASE), (number, word)
        # Cada bloque nombra en "requiere" TODAS las relaciones que lee, y nada más.
        read = set(re.findall(r"\b(?:FROM|JOIN)\s+((?:public|auth|supabase_migrations)\.\w+)", code))
        named = {r for r in requires if re.fullmatch(r"[a-z_]+\.[a-z_]+", r)}
        assert read == named, (number, read, requires)


def test_stage2_never_lists_people_or_content():
    sql = code_of(STAGE_2)

    for column in ("email", "display_name", "statement_md", "correct_option", "options",
                   "raw_user_meta", "encrypted_password", "user_id"):
        assert not re.search(rf"\b{column}\b", sql, re.IGNORECASE), column
    # El recuento de Auth es solo agregado.
    assert re.search(r"SELECT\s+count\(\*\)::bigint AS cuentas_auth FROM auth\.users;", sql)


def stage2_blocks() -> dict[int, tuple[list[str], str]]:
    text = STAGE_2.read_text(encoding="utf-8")
    pattern = re.compile(r"-- BLOQUE (\d+) \(requiere: ([^)]*)\)\n(.*?;)", re.DOTALL)
    blocks = {}
    for match in pattern.finditer(text):
        requires = [r.strip() for r in re.split(r",| y ", match.group(2)) if r.strip()]
        blocks[int(match.group(1))] = (requires, match.group(3))
    return blocks


def test_a_write_is_refused_in_the_read_only_mode_the_tests_use(db):
    """Control del método: confirma que `run_sql` realmente impediría una escritura."""
    db.execute("SET LOCAL transaction_read_only = on")

    with pytest.raises(Exception, match="read-only"):
        db.execute("CREATE TABLE public.no_deberia_crearse (id int)")


# --- etapa 1: instalación completa ------------------------------------------------------------


def test_stage1_sees_every_expected_object_after_the_migrations(db):
    out = stage1(db)

    for name in TABLES:
        assert out["relaciones_esperadas"][f"public.{name}"].startswith("existe;"), name
    for name in FUNCTIONS:
        assert out["funciones_esperadas"][f"cane_private.{name}"] == "existe", name
    for name in COLUMNS:
        assert out["columnas_esperadas"][f"public.{name}"] == "existe", name
    for name in INDEXES:
        assert out["indices_esperados"][f"public.{name}"] == "existe", name
    triggers = {k.split(" / ")[1]: v for k, v in out["triggers_esperados"].items()}
    assert set(triggers) == set(TRIGGERS) and set(triggers.values()) == {"existe"}
    assert out["resumen"]["relaciones de CANE presentes"] == "9 de 9"
    assert out["resumen"]["columnas de la 2.ª migración presentes"] == "5 de 5"
    assert out["resumen"]["funciones de cane_private presentes"] == "9 de 9"
    assert out["resumen"]["triggers presentes"] == "10 de 10"
    assert out["resumen"]["índices presentes"] == "3 de 3"
    assert out["resumen"]["objetos AJENOS en public/cane_private"] == "0"
    assert "ajenos" not in out


def test_stage1_reports_rls_grants_and_read_access(db):
    out = stage1(db)

    for name in TABLES[:-1]:  # las 8 tablas
        assert "rls=true" in out["tablas"][f"public.{name}"], name
    assert out["permisos_tablas"]["public.question_keys"] == "(sin permisos para anon/authenticated/PUBLIC)"
    assert out["permisos_tablas"]["public.question_assets"] == "(sin permisos para anon/authenticated/PUBLIC)"
    assert "security_invoker" in out["tablas"]["public.practice_ranking"]
    assert out["relaciones_esperadas"]["auth.users"].endswith("lectura_con_el_rol_actual=true")
    assert out["permisos_esquemas"]["cane_private -> anon"] == "USAGE=false"
    assert out["esquemas"]["public"].startswith("APLICACION")
    assert out["esquemas"]["auth"].startswith("INTERNO")


# --- etapa 1: vacía, a medias y con objetos ajenos --------------------------------------------


def test_stage1_on_an_empty_project_says_does_not_exist_instead_of_failing(db):
    drop_cane(db)

    out = stage1(db)

    for name in TABLES:
        assert out["relaciones_esperadas"][f"public.{name}"] == "NO EXISTE", name
    assert set(out["funciones_esperadas"].values()) == {"NO EXISTE"}
    assert set(out["columnas_esperadas"].values()) == {"NO EXISTE"}
    assert set(out["triggers_esperados"].values()) == {"NO EXISTE"}
    assert out["relaciones_esperadas"]["supabase_migrations.schema_migrations"] == "NO EXISTE"
    assert out["resumen"]["relaciones de CANE presentes"] == "0 de 9"
    assert out["resumen"]["esquema cane_private"] == "NO EXISTE"
    assert out["resumen"]["objetos AJENOS en public/cane_private"] == "0"
    assert not any(k.startswith("public.") for k in out.get("tablas", {}))


def test_stage1_distinguishes_a_partial_install_from_a_missing_one(db):
    # Falta la 3.ª migración (figuras) y la columna que añade la 2.ª a las claves.
    db.execute("DROP TABLE public.question_assets")
    db.execute("ALTER TABLE public.question_keys DROP COLUMN verified_basis")

    out = stage1(db)

    assert out["relaciones_esperadas"]["public.question_assets"] == "NO EXISTE"
    assert out["relaciones_esperadas"]["public.questions"].startswith("existe;")
    assert out["columnas_esperadas"]["public.question_keys.verified_basis"] == "NO EXISTE"
    assert out["columnas_esperadas"]["public.questions.discarded"] == "existe"
    assert out["triggers_esperados"]["public.question_assets / question_assets_freeze"] == "NO EXISTE"
    assert out["resumen"]["relaciones de CANE presentes"] == "8 de 9"
    assert out["resumen"]["columnas de la 2.ª migración presentes"] == "4 de 5"
    assert out["resumen"]["triggers presentes"] == "9 de 10"


def test_stage1_flags_objects_that_are_not_part_of_cane_but_not_supabase_internals(db):
    db.execute("CREATE TABLE public.tabla_ajena (id int)")
    db.execute("CREATE FUNCTION public.funcion_ajena() RETURNS int LANGUAGE sql AS 'SELECT 1'")
    db.execute("CREATE TYPE public.tipo_ajeno AS ENUM ('a')")
    db.execute("CREATE SEQUENCE public.secuencia_ajena")
    db.execute("GRANT SELECT ON public.tabla_ajena TO anon")

    out = stage1(db)

    assert out["ajenos"]["relacion public.tabla_ajena"] == "tipo=tabla"
    assert out["ajenos"]["relacion public.secuencia_ajena"] == "tipo=secuencia"
    assert "funcion public.funcion_ajena()" in out["ajenos"]
    assert "tipo public.tipo_ajeno" in out["ajenos"]
    assert out["resumen"]["objetos AJENOS en public/cane_private"] == "4"
    assert "rls=false" in out["tablas"]["public.tabla_ajena"]
    assert "anon:SELECT" in out["permisos_tablas"]["public.tabla_ajena"]
    # Los objetos de CANE y los internos de Supabase no se marcan como ajenos.
    assert not any("questions" in k or "auth" in k for k in out["ajenos"])


def test_stage1_flags_an_unexpected_schema_but_not_the_known_internal_ones(db):
    db.execute("CREATE SCHEMA esquema_desconocido")

    out = stage1(db)

    assert out["esquemas"]["esquema_desconocido"].startswith("OTRO")
    assert out["esquemas"]["auth"].startswith("INTERNO")
    assert out["esquemas"]["cane_private"].startswith("APLICACION")


def test_stage1_reports_existing_but_unreadable_differently_from_missing(db):
    """Un rol sin permiso no ve 'NO EXISTE': ve que existe pero no se puede leer."""
    db.execute("CREATE ROLE sin_permisos NOLOGIN")
    db.execute("SET LOCAL ROLE sin_permisos")

    out = stage1(db)

    assert out["relaciones_esperadas"]["public.questions"] == "existe; tipo=tabla; lectura_con_el_rol_actual=false"
    assert out["relaciones_esperadas"]["public.teams"].endswith("lectura_con_el_rol_actual=false")
    assert out["resumen"]["relaciones de CANE presentes"] == "9 de 9"  # existe aunque no se lea


def test_stage1_exposes_only_the_data_api_schemas_setting_of_the_authenticator(db):
    db.execute("CREATE ROLE authenticator NOLOGIN")
    db.execute("ALTER ROLE authenticator SET pgrst.db_schemas = 'public,graphql_public'")
    db.execute("ALTER ROLE authenticator SET statement_timeout = '8s'")
    db.execute("ALTER ROLE authenticator SET pgrst.jwt_secret = 'no-debe-aparecer'")

    out = stage1(db)

    assert out["data_api"]["authenticator: pgrst.db_schemas"] == "pgrst.db_schemas=public,graphql_public"
    everything = " ".join(v for sec in out.values() for v in sec.values())
    assert "no-debe-aparecer" not in everything and "statement_timeout" not in everything


# --- etapa 2: bloques independientes ---------------------------------------------------------------


def test_stage2_each_block_runs_alone_and_returns_only_aggregates(db, seed):
    db.execute("CREATE SCHEMA supabase_migrations")
    db.execute("CREATE TABLE supabase_migrations.schema_migrations (version text)")
    db.execute("INSERT INTO supabase_migrations.schema_migrations VALUES ('20261009212148')")
    seed.team()
    seed.question("econometria", active=True)
    seed.question("macroeconomia", active=False)

    results = {n: run_sql(db, sql) for n, (_, sql) in stage2_blocks().items()}

    assert results[2][0]["versiones"] == "20261009212148"
    assert results[3][0]["equipos"] == 1
    assert results[5][0]["preguntas"] == 2 and results[5][0]["activas"] == 1
    assert results[6][0] == {"activas": 1, "inactivas": 1, "descartadas": 0}
    assert results[7][0]["claves"] == 2
    assert results[8][0]["activas_sin_clave_verificada"] == 0
    for number, rows in results.items():
        for row in rows:  # solo números y etiquetas de estado/versión: nada de texto libre
            for value in row.values():
                assert isinstance(value, int) or number in (2, 10), (number, value)


def test_stage2_a_partial_install_only_breaks_the_blocks_that_were_not_confirmed(db):
    blocks = stage2_blocks()
    db.execute("DROP TABLE public.question_assets")
    db.execute("ALTER TABLE public.questions DROP COLUMN discarded CASCADE")

    ok = {}
    for number, (_, sql) in blocks.items():
        db.execute("SAVEPOINT b")
        try:
            run_sql(db, sql)
            ok[number] = True
        except Exception:
            ok[number] = False
        db.execute("ROLLBACK TO SAVEPOINT b")

    assert ok[9] is False  # question_assets: la etapa 1 diría NO EXISTE
    assert ok[6] is False  # requiere la columna de la 2.ª migración
    assert ok[5] and ok[7] and ok[11] and ok[12]  # el resto sigue siendo válido por separado
