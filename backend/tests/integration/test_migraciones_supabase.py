"""Las 3 migraciones en un entorno que se parece al del proyecto real de Supabase.

Qué añade a las demás pruebas: el arnés normal instala las migraciones sin los privilegios
por defecto que Supabase concede a `anon`, `authenticated` y `service_role` sobre todo lo
nuevo en `public`. Aquí se reinstalan las tres migraciones, dentro de la transacción de la
prueba, DESPUÉS de crear esos privilegios por defecto, y se comprueba que el resultado no
da acceso a los roles del navegador.

Es PostgreSQL local (PGlite), no el proyecto real: no verifica el estado de ningún proyecto.
"""

import re
from pathlib import Path

import psycopg
import pytest

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
FILES = sorted(MIGRATIONS.glob("2026*.sql"))
EXPECTED_ORDER = [
    "20261009212148_supabase_cane.sql",
    "20261013034510_curacion_banco.sql",
    "20261013044404_question_assets.sql",
]
CLIENT_ROLES = ("anon", "authenticated")
ALL_PRIVILEGES = "SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"


def code(path: Path) -> str:
    """El SQL sin comentarios de línea ni literales de texto."""
    lines = [line.split("--", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()]
    return re.sub(r"'(?:[^']|'')*'", "''", "\n".join(lines))


def all_code() -> str:
    return "\n".join(code(f) for f in FILES)


def declared_tables() -> list[str]:
    """Las tablas que crean los archivos (derivadas del texto, no asumidas)."""
    return re.findall(r"CREATE TABLE public\.(\w+)", all_code())


def declared_views() -> list[str]:
    return re.findall(r"CREATE VIEW public\.(\w+)", all_code())


def drop_cane(db) -> None:
    db.execute("DROP VIEW IF EXISTS public.practice_ranking")
    for table in ("attempts", "session_questions", "sessions", "question_assets",
                  "question_keys", "questions", "profiles", "teams"):
        db.execute(f"DROP TABLE IF EXISTS public.{table} CASCADE")
    db.execute("DROP SCHEMA IF EXISTS cane_private CASCADE")


@pytest.fixture
def supabase_like(db):
    """Reinstala las 3 migraciones con los privilegios por defecto de Supabase en `public`."""
    drop_cane(db)
    for kind in ("TABLES", "FUNCTIONS", "SEQUENCES"):
        db.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON {kind} "
                   "TO anon, authenticated, service_role")
    # Estrés (más estricto que Supabase): también los esquemas nuevos nacen abiertos a los
    # roles del navegador, para comprobar que la migración cierra cane_private por sí misma.
    db.execute("ALTER DEFAULT PRIVILEGES GRANT USAGE ON SCHEMAS TO anon, authenticated")
    for path in FILES:
        db.execute(path.read_text(encoding="utf-8"))
    return db


def grants(db, qualified: str) -> dict[str, set[str]]:
    rows = db.execute(
        "SELECT coalesce(r.rolname, 'PUBLIC') AS grantee, a.privilege_type "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "CROSS JOIN LATERAL aclexplode(c.relacl) a "
        "LEFT JOIN pg_roles r ON r.oid = a.grantee "
        "WHERE n.nspname || '.' || c.relname = %s", (qualified,)).fetchall()
    out: dict[str, set[str]] = {}
    for r in rows:
        out.setdefault(r["grantee"], set()).add(r["privilege_type"])
    return out


# --- qué hay en los archivos --------------------------------------------------------------------


def test_the_three_planned_migrations_come_first_in_order_and_one_is_added():
    assert [f.name for f in FILES[:3]] == EXPECTED_ORDER
    assert len(FILES) == 4  # la cuarta (service_role) se prueba en test_migracion_service_role.py


def test_the_files_declare_the_tables_we_expect_to_protect():
    assert declared_tables() == [
        "teams", "profiles", "questions", "question_keys", "sessions",
        "session_questions", "attempts", "question_assets",
    ]
    assert declared_views() == ["practice_ranking"]


def test_the_migrations_never_destroy_or_overwrite_data():
    sql = all_code()

    assert not re.search(r"\bDROP\s+(TABLE|COLUMN|SCHEMA|VIEW|TRIGGER|FUNCTION|CONSTRAINT)\b", sql, re.I)
    assert not re.search(r"\bTRUNCATE\b", sql, re.I)
    assert not re.search(r"\bDELETE\s+FROM\b", sql, re.I)
    assert not re.search(r"^\s*UPDATE\s+[\w.]+\s+SET\b", sql, re.I | re.M)  # no UPDATE de filas
    assert not re.search(r"\bINSERT\s+INTO\b", sql, re.I)  # no siembran datos
    # La única sustitución es la de la función de congelado (cuerpo, no datos).
    assert re.findall(r"CREATE OR REPLACE (?:FUNCTION|VIEW|TRIGGER)\s+([\w.]+)", sql, re.I) == [
        "cane_private.freeze_used_question"
    ]


def test_the_only_objects_outside_the_application_that_they_need_exist_in_supabase():
    sql = all_code()
    schemas = set(re.findall(
        # Nombres de esquema (>= 4 letras): los alias de tabla de las consultas son más cortos.
        r"\b(?:REFERENCES|FROM|JOIN|TABLE|ON|FUNCTION|SCHEMA)\s+(?:IF NOT EXISTS\s+)?(\w{4,})\.\w+", sql))
    roles = set(re.findall(r"\bFROM\s+((?:PUBLIC|anon|authenticated|service_role)(?:\s*,\s*\w+)*)", sql))

    assert schemas <= {"public", "cane_private", "auth"}  # auth.users; nada de `extensions`
    assert "auth" in schemas
    # Solo se nombran los roles `anon`/`authenticated` (y PUBLIC): existen en todo proyecto Supabase.
    first_three = "\n".join(code(f) for f in FILES[:3])
    named = set(re.findall(r"\b(anon|authenticated|service_role)\b", first_three))
    assert named == {"anon", "authenticated"}, named
    # Solo la cuarta migración nombra a service_role (para quitarle dos tablas).
    assert set(re.findall(r"\b(anon|authenticated|service_role)\b", code(FILES[3]))) == {"service_role"}
    assert roles  # hay REVOKE ... FROM
    # No usan funciones de pgcrypto: la extensión es innecesaria (gen_random_uuid es nativa).
    assert not re.search(r"\b(digest|crypt|gen_salt|hmac|pgp_\w+|encrypt|decrypt)\s*\(", sql, re.I)


# --- el resultado, con los privilegios por defecto de Supabase ----------------------------------


def test_the_emulated_supabase_defaults_would_expose_a_new_table(supabase_like):
    """Control: sin REVOKE, una tabla nueva en public sí quedaría abierta a anon."""
    supabase_like.execute("CREATE TABLE public.tabla_de_control (id int)")

    assert "SELECT" in grants(supabase_like, "public.tabla_de_control").get("anon", set())


def test_rls_is_enabled_on_every_table_the_migrations_create(supabase_like):
    for table in declared_tables():
        row = supabase_like.execute(
            "SELECT relrowsecurity FROM pg_class WHERE oid = to_regclass(%s)", (f"public.{table}",)
        ).fetchone()
        assert row["relrowsecurity"] is True, table


def test_no_client_role_has_any_privilege_on_tables_or_the_view(supabase_like):
    for relation in declared_tables() + declared_views():
        granted = grants(supabase_like, f"public.{relation}")
        for role in (*CLIENT_ROLES, "PUBLIC"):
            assert granted.get(role, set()) == set(), (relation, role, granted.get(role))


def test_question_keys_is_closed_in_every_way(supabase_like):
    """(ii) La clave de respuesta vive en public: privilegios, RLS y vistas."""
    db = supabase_like
    assert grants(db, "public.question_keys").get("anon", set()) == set()
    assert grants(db, "public.question_keys").get("authenticated", set()) == set()
    assert db.execute("SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                      "WHERE oid = 'public.question_keys'::regclass").fetchone()["relrowsecurity"]
    # Ninguna vista o función de public expone correct_option.
    exposing = db.execute(
        "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind IN ('v','m') "
        "AND pg_get_viewdef(c.oid) ILIKE '%correct_option%'").fetchall()
    assert exposing == []
    functions_in_public = db.execute(
        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.prosrc ILIKE '%correct_option%'").fetchall()
    assert functions_in_public == []
    # Ni siquiera un rol con permiso concedido por error la lee (ver la prueba de GRANT erróneo).


def test_cane_private_is_closed_to_the_browser_roles(supabase_like):
    """(i) El esquema privado y sus funciones."""
    db = supabase_like
    for role in CLIENT_ROLES:
        assert db.execute("SELECT has_schema_privilege(%s, 'cane_private', 'USAGE') AS ok", (role,)
                          ).fetchone()["ok"] is False
        assert db.execute("SELECT has_schema_privilege(%s, 'cane_private', 'CREATE') AS ok", (role,)
                          ).fetchone()["ok"] is False
    functions = db.execute(
        "SELECT p.oid, p.proname, p.prosecdef, p.proconfig, p.proacl "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'cane_private'").fetchall()
    assert len(functions) == 9
    for fn in functions:
        for role in CLIENT_ROLES:
            assert db.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE') AS ok",
                              (role, fn["oid"])).fetchone()["ok"] is False, (fn["proname"], role)
        # Ni PUBLIC (grantee 0) conserva EXECUTE.
        publics = db.execute("SELECT 1 FROM aclexplode(%s::aclitem[]) a WHERE a.grantee = 0",
                             (fn["proacl"],)).fetchall() if fn["proacl"] else [1]
        assert publics == [], fn["proname"]
        # Todas fijan search_path (y ninguna es SECURITY DEFINER: se ejecutan con el rol que dispara).
        assert any(str(c).startswith("search_path=") for c in (fn["proconfig"] or [])), fn["proname"]
        assert fn["prosecdef"] is False, fn["proname"]


def test_service_role_keeps_only_what_the_fourth_migration_did_not_take_away(supabase_like):
    """Los privilegios por defecto de Supabase le dan acceso a service_role; la 4.ª migración
    se lo quita SOLO en las dos tablas secretas (antes este test documentaba el residuo con True).

    El resto de las tablas y la vista conservan el acceso por defecto: es el alcance previsto
    (ver test_migracion_service_role.py para la verificación detallada). En el proyecto real
    ese rol (con BYPASSRLS) solo lo usa quien tenga la clave secreta; el frontend no la lleva.
    """
    def can_read(table: str) -> bool:
        return supabase_like.execute(
            "SELECT has_table_privilege('service_role', %s, 'SELECT') AS ok", (f"public.{table}",)
        ).fetchone()["ok"]

    assert can_read("question_keys") is False
    assert can_read("question_assets") is False
    assert can_read("questions") is True  # fuera del alcance de la 4.ª migración


def test_a_mistaken_grant_still_leaves_the_browser_roles_with_zero_rows(supabase_like, seed):
    """RLS activado sin políticas: denegar por defecto aunque alguien conceda privilegios."""
    db = supabase_like
    team = seed.team()
    seed.user(team)
    seed.question("econometria", active=True)
    db.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated")  # el error

    totals = {t: db.execute(f"SELECT count(*) AS n FROM public.{t}").fetchone()["n"]
              for t in ("teams", "profiles", "questions", "question_keys")}
    assert all(n >= 1 for n in totals.values()), totals  # hay datos que proteger

    for role in CLIENT_ROLES:
        db.execute(f"SET LOCAL ROLE {role}")
        try:
            for table in declared_tables() + declared_views():
                n = db.execute(f"SELECT count(*) AS n FROM public.{table}").fetchone()["n"]
                assert n == 0, (role, table, n)  # ve 0 filas: ni claves, ni sesiones, ni ranking
            with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
                db.execute("INSERT INTO public.teams(name) VALUES ('intruso')")
            assert db.execute("UPDATE public.question_keys SET correct_option = 'B'").rowcount == 0
            assert db.execute("DELETE FROM public.attempts").rowcount == 0
        finally:
            db.execute("RESET ROLE")
    # Y los datos siguen intactos para el rol propietario.
    assert db.execute("SELECT count(*) AS n FROM public.question_keys").fetchone()["n"] >= 1
    assert db.execute("SELECT correct_option FROM public.question_keys").fetchone()["correct_option"] == "A"


def test_the_ranking_view_does_not_bypass_the_tables_it_reads(supabase_like):
    options = supabase_like.execute(
        "SELECT reloptions FROM pg_class WHERE oid = 'public.practice_ranking'::regclass").fetchone()
    assert "security_invoker=true" in options["reloptions"]


def test_the_migrations_define_no_row_policies_the_scoping_is_done_by_the_api(supabase_like):
    """Hallazgo de diseño (no es un fallo): no hay políticas; el alcance por equipo lo aplica
    el backend (`WHERE team_id = ...`). La seguridad del navegador es REVOKE + RLS sin políticas."""
    policies = supabase_like.execute(
        "SELECT count(*) AS n FROM pg_policies WHERE schemaname IN ('public', 'cane_private')"
    ).fetchone()["n"]

    assert policies == 0


def test_reapplying_a_migration_fails_without_touching_the_data(supabase_like, seed):
    db = supabase_like
    seed.team()
    seed.question("macroeconomia", active=True)
    before = db.execute("SELECT (SELECT count(*) FROM public.teams) AS t, "
                        "(SELECT count(*) FROM public.questions) AS q").fetchone()

    for path in FILES[:3]:  # cada una por separado, en su propio savepoint
        with pytest.raises(psycopg.Error), db.transaction():
            db.execute(path.read_text(encoding="utf-8"))
    # La 4.ª es un REVOKE: repetirla no falla ni cambia nada (idempotente).
    db.execute(FILES[3].read_text(encoding="utf-8"))

    after = db.execute("SELECT (SELECT count(*) FROM public.teams) AS t, "
                       "(SELECT count(*) FROM public.questions) AS q").fetchone()
    assert before == after
