"""Cuarta migración: retirar a service_role el acceso a question_keys y question_assets.

TODO es local (PGlite): una base descartable dentro de la transacción de cada prueba. No se
conecta a Supabase ni a ningún servicio. PGlite es PostgreSQL en WASM, no el motor de
Supabase (PostgreSQL 17 con sus roles y extensiones propios); lo que aquí se verifica es la
migración y su efecto con privilegios por defecto emulados, no el estado del proyecto real.

Qué se comprueba con el catálogo y qué con consultas reales:
- catálogo: `relacl`/`attacl` y las funciones `has_table_privilege`/`has_column_privilege`
  (que ya consideran propiedad, PUBLIC y herencia de membresías);
- consultas reales: `SET LOCAL ROLE service_role` y SELECT/INSERT/UPDATE/DELETE/TRUNCATE.
  REFERENCES y TRIGGER no se pueden ejercitar con una consulta sin crear objetos como ese
  rol: solo se comprueban por catálogo.
"""

import hashlib
import re
import sys
from pathlib import Path

import psycopg
import pytest

MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
FILES = sorted(MIGRATIONS.glob("2026*.sql"))
PREVIOUS = FILES[:3]
NEW = FILES[3:]

# SHA-256 del contenido con saltos de línea normalizados a LF (no depende de autocrlf).
PINNED = {
    "20261009212148_supabase_cane.sql":
        "dc7e92cdfb3887af1c349f9fed15d9e5f3716f881577b188e2a8fa43480c9831",
    "20261013034510_curacion_banco.sql":
        "c9eefbb20ed7046a832319b2de4e7e9d304a28076024990a0eb3c7747f4929ea",
    "20261013044404_question_assets.sql":
        "ab262f6bf57ec53c4b697d179ebbf0d2bfde6cdf011d183cd3ff12aae86e1a51",
}
TABLES = ("question_keys", "question_assets")
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
PNG = b"\x89PNG\r\n\x1a\n" + b"figura-ficticia-secreta"

# Mismo asistente que ya usan las pruebas del importador: PGlite desincroniza la conexión
# compartida si el cliente captura un RAISE de trigger de UPDATE; se captura en el servidor.
sys.path.insert(0, str(Path(__file__).parent))
from test_importador import expect_error_in_server  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def code(path: Path) -> str:
    lines = [line.split("--", 1)[0] for line in path.read_text(encoding="utf-8").splitlines()]
    return "\n".join(lines)


# --- instalación -----------------------------------------------------------------------------


def drop_cane(db) -> None:
    db.execute("DROP VIEW IF EXISTS public.practice_ranking")
    for table in ("attempts", "session_questions", "sessions", "question_assets",
                  "question_keys", "questions", "profiles", "teams"):
        db.execute(f"DROP TABLE IF EXISTS public.{table} CASCADE")
    db.execute("DROP SCHEMA IF EXISTS cane_private CASCADE")


def supabase_environment(db) -> None:
    """Privilegios por defecto amplios en public, service_role con BYPASSRLS y roles de apoyo."""
    for kind in ("TABLES", "FUNCTIONS", "SEQUENCES"):
        db.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON {kind} "
                   "TO anon, authenticated, service_role")
    db.execute("ALTER ROLE service_role BYPASSRLS")
    # authenticator (como PostgREST): NOINHERIT, pero puede cambiar a los tres roles.
    db.execute("CREATE ROLE authenticator NOLOGIN NOINHERIT")
    db.execute("GRANT anon, authenticated, service_role TO authenticator")
    # Un rol que SÍ hereda de service_role: si el REVOKE no fuera efectivo, lo vería.
    db.execute("CREATE ROLE heredero NOLOGIN INHERIT")
    db.execute("GRANT service_role TO heredero")


def install(db, files) -> None:
    drop_cane(db)
    supabase_environment(db)
    for path in files:
        db.execute(path.read_text(encoding="utf-8"))


def seed_secrets(db, seed) -> dict:
    """Una pregunta con clave y una figura, ficticias, para que 'sin acceso' no sea 'vacío'."""
    qid = seed.question("econometria", active=True, correct="C")
    db.execute(
        "INSERT INTO public.question_assets (question_id, ref, mime_type, sha256, data) "
        "VALUES (%s, 'assets/fig-01.png', 'image/png', %s, %s)", (qid, "b" * 64, PNG))
    return {"question_id": qid}


# --- observación -------------------------------------------------------------------------------


def effective_table_privileges(db, role: str, table: str) -> dict[str, bool]:
    return {p: db.execute("SELECT has_table_privilege(%s, %s, %s) AS ok",
                          (role, f"public.{table}", p)).fetchone()["ok"] for p in PRIVILEGES}


def effective_column_privileges(db, role: str, table: str) -> dict[str, bool]:
    columns = [r["attname"] for r in db.execute(
        "SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass AND attnum > 0 "
        "AND NOT attisdropped", (f"public.{table}",)).fetchall()]
    return {f"{c}:{p}": db.execute("SELECT has_column_privilege(%s, %s, %s, %s) AS ok",
                                   (role, f"public.{table}", c, p)).fetchone()["ok"]
            for c in columns for p in COLUMN_PRIVILEGES}


def acl_entries(db) -> set[tuple]:
    """Todas las ACL de relaciones, columnas, funciones y esquemas de la aplicación."""
    rows = db.execute("""
        SELECT 'tabla' AS kind, n.nspname || '.' || c.relname AS obj,
               coalesce(r.rolname, 'PUBLIC') AS grantee, a.privilege_type AS priv
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(c.relacl) a LEFT JOIN pg_roles r ON r.oid = a.grantee
        WHERE n.nspname IN ('public', 'cane_private')
        UNION ALL
        SELECT 'columna', n.nspname || '.' || c.relname || '.' || at.attname,
               coalesce(r.rolname, 'PUBLIC'), a.privilege_type
        FROM pg_attribute at JOIN pg_class c ON c.oid = at.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(at.attacl) a LEFT JOIN pg_roles r ON r.oid = a.grantee
        WHERE n.nspname IN ('public', 'cane_private') AND at.attacl IS NOT NULL
        UNION ALL
        SELECT 'funcion', n.nspname || '.' || p.proname, coalesce(r.rolname, 'PUBLIC'), a.privilege_type
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        CROSS JOIN LATERAL aclexplode(p.proacl) a LEFT JOIN pg_roles r ON r.oid = a.grantee
        WHERE n.nspname IN ('public', 'cane_private')
        UNION ALL
        SELECT 'esquema', n.nspname, coalesce(r.rolname, 'PUBLIC'), a.privilege_type
        FROM pg_namespace n CROSS JOIN LATERAL aclexplode(n.nspacl) a
        LEFT JOIN pg_roles r ON r.oid = a.grantee
        WHERE n.nspname IN ('public', 'cane_private')
    """).fetchall()
    return {(r["kind"], r["obj"], r["grantee"], r["priv"]) for r in rows}


def structure(db) -> dict:
    """Lo que la migración NO debe tocar: RLS, funciones, triggers, índices, propietarios."""
    return {
        "rls": {r["relname"]: (r["relrowsecurity"], r["relforcerowsecurity"], r["relowner"])
                for r in db.execute(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "pg_get_userbyid(c.relowner) AS relowner FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v')").fetchall()},
        "functions": {r["f"]: r["h"] for r in db.execute(
            "SELECT p.oid::regprocedure::text AS f, md5(p.prosrc || coalesce(p.proconfig::text, '')) AS h "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'cane_private'").fetchall()},
        "triggers": sorted(r["t"] for r in db.execute(
            "SELECT c.relname || '.' || g.tgname AS t FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND NOT g.tgisinternal").fetchall()),
        "policies": db.execute("SELECT count(*) AS n FROM pg_policies").fetchone()["n"],
    }


def counts(db) -> dict:
    return db.execute(
        "SELECT (SELECT count(*) FROM public.teams) AS teams, (SELECT count(*) FROM public.profiles) AS profiles, "
        "(SELECT count(*) FROM public.questions) AS questions, "
        "(SELECT count(*) FROM public.question_keys) AS keys, "
        "(SELECT count(*) FROM public.question_assets) AS assets, "
        "(SELECT count(*) FROM public.sessions) AS sessions, "
        "(SELECT count(*) FROM public.session_questions) AS positions, "
        "(SELECT count(*) FROM public.attempts) AS attempts").fetchone()


def as_role(db, role: str):
    """Contexto: ejecuta como `role` y SIEMPRE vuelve al propietario."""

    class _Ctx:
        def __enter__(self):
            db.execute(f"SET LOCAL ROLE {role}")
            who = db.execute("SELECT current_user AS cu, session_user AS su").fetchone()
            assert who["cu"] == role  # el contexto no conserva por error al propietario
            return who

        def __exit__(self, *exc):
            db.execute("RESET ROLE")
            assert db.execute("SELECT current_user AS cu").fetchone()["cu"] == "postgres"
            return False

    return _Ctx()


def denied(db, sql: str):
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute(sql)


# --- la migración y las tres anteriores --------------------------------------------------------


def test_the_three_previous_migrations_are_byte_for_byte_unchanged():
    assert [p.name for p in PREVIOUS] == list(PINNED)
    for path in PREVIOUS:
        assert sha(path) == PINNED[path.name], path.name


def test_the_new_migration_is_one_extra_file_sorted_after_the_previous_ones():
    assert len(FILES) == 4 and len(NEW) == 1
    assert re.fullmatch(r"\d{14}_[a-z_]+\.sql", NEW[0].name)
    assert NEW[0].name.split("_")[0] > PREVIOUS[-1].name.split("_")[0]
    assert len({p.name.split("_")[0] for p in FILES}) == 4  # sin colisión de versión


def test_the_new_migration_is_exactly_one_revoke_on_the_two_tables():
    statements = [s.strip() for s in code(NEW[0]).split(";") if s.strip()]

    assert len(statements) == 1
    assert re.fullmatch(
        r"REVOKE ALL PRIVILEGES ON TABLE public\.question_keys, public\.question_assets FROM service_role",
        " ".join(statements[0].split()))
    # Nada más: ni GRANT, ni defaults, ni políticas, ni propietarios, ni datos.
    for word in ("GRANT", "DEFAULT", "POLICY", "OWNER", "ALTER", "DROP", "DELETE", "UPDATE",
                 "INSERT", "TRUNCATE", "CREATE"):
        assert not re.search(rf"\b{word}\b", code(NEW[0]), re.I), word


# --- antes: el residuo existe --------------------------------------------------------------------


def test_before_the_change_service_role_can_read_the_keys_and_the_figure_bytes(db, seed):
    install(db, PREVIOUS)
    seed_secrets(db, seed)

    for table in TABLES:  # catálogo
        assert all(effective_table_privileges(db, "service_role", table).values()), table
    assert db.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'service_role'").fetchone()["rolbypassrls"]
    with as_role(db, "service_role"):  # consultas reales
        assert db.execute("SELECT correct_option FROM public.question_keys").fetchone()["correct_option"] == "C"
        assert bytes(db.execute("SELECT data FROM public.question_assets").fetchone()["data"]) == PNG
    # Y el rol con herencia la ve por membresía.
    assert effective_table_privileges(db, "heredero", "question_keys")["SELECT"] is True


# --- después, instalación desde cero ----------------------------------------------------------------


@pytest.fixture
def fresh(db, seed):
    install(db, FILES)
    return seed_secrets(db, seed)


def test_after_a_clean_install_service_role_has_no_privilege_on_the_two_tables(db, fresh):
    for table in TABLES:
        assert not any(effective_table_privileges(db, "service_role", table).values()), table
        assert not any(effective_column_privileges(db, "service_role", table).values()), table
    # Catálogo: ninguna entrada de ACL de tabla ni de columna para service_role en ellas.
    leftovers = [e for e in acl_entries(db)
                 if e[2] == "service_role" and e[1] in {f"public.{t}" for t in TABLES}
                 or (e[0] == "columna" and e[2] == "service_role"
                     and e[1].rsplit(".", 1)[0] in {f"public.{t}" for t in TABLES})]
    assert leftovers == []


def test_after_the_change_heredity_and_membership_do_not_restore_access(db, fresh):
    # Rol que hereda de service_role.
    assert not any(effective_table_privileges(db, "heredero", "question_keys").values())
    assert not any(effective_table_privileges(db, "heredero", "question_assets").values())
    # PostgREST: authenticator es NOINHERIT; aun cambiando a service_role no gana nada.
    assert not any(effective_table_privileges(db, "authenticator", "question_keys").values())
    assert db.execute("SELECT pg_has_role('authenticator', 'service_role', 'MEMBER') AS m").fetchone()["m"]
    db.execute("SET LOCAL ROLE authenticator")
    db.execute("SET LOCAL ROLE service_role")  # cambio permitido por la membresía
    denied(db, "SELECT correct_option FROM public.question_keys")
    db.execute("RESET ROLE")
    # PUBLIC tampoco.
    assert not [e for e in acl_entries(db) if e[2] == "PUBLIC" and e[1].startswith("public.question_")]


def test_after_the_change_service_role_cannot_read_or_modify_the_two_tables(db, fresh):
    owner = db.execute("SELECT current_user AS cu, session_user AS su").fetchone()
    assert owner["cu"] == "postgres"  # antes de cambiar de rol, el contexto es el propietario
    # El propietario SÍ ve los datos: la tabla no está vacía, así que "denegado" no es "vacío".
    assert db.execute("SELECT count(*) AS n FROM public.question_keys").fetchone()["n"] == 1
    assert db.execute("SELECT count(*) AS n FROM public.question_assets").fetchone()["n"] == 1

    with as_role(db, "service_role") as who:
        assert who["cu"] == "service_role"
        # BYPASSRLS no es un permiso de tabla: sigue vigente y aun así no basta.
        assert db.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone()["rolbypassrls"]
        denied(db, "SELECT correct_option FROM public.question_keys")
        denied(db, "SELECT count(*) FROM public.question_keys")
        denied(db, "SELECT data FROM public.question_assets")
        denied(db, "SELECT octet_length(data) FROM public.question_assets")
        denied(db, "INSERT INTO public.question_keys(question_id, correct_option) "
                   "SELECT id, 'A' FROM public.questions")
        denied(db, "UPDATE public.question_keys SET correct_option = 'A'")
        denied(db, "DELETE FROM public.question_keys")
        denied(db, "TRUNCATE public.question_keys")
        denied(db, "UPDATE public.question_assets SET ref = 'assets/otro.png'")
        denied(db, "DELETE FROM public.question_assets")
        denied(db, "TRUNCATE public.question_assets")
    # Nada cambió.
    assert db.execute("SELECT correct_option FROM public.question_keys").fetchone()["correct_option"] == "C"


def test_after_the_change_the_browser_roles_still_have_nothing(db, fresh):
    for role in ("anon", "authenticated"):
        for table in TABLES:
            assert not any(effective_table_privileges(db, role, table).values()), (role, table)
        with as_role(db, role):
            denied(db, "SELECT * FROM public.question_keys")
            denied(db, "SELECT * FROM public.question_assets")
    assert not any(effective_table_privileges(db, "PUBLIC" if False else "anon", "questions").values())


def test_the_other_service_role_privileges_are_left_exactly_as_they_were(db, seed):
    """La migración solo quita service_role de las dos tablas: nada se añade ni se quita más."""
    install(db, PREVIOUS)
    before = acl_entries(db)
    db.execute(NEW[0].read_text(encoding="utf-8"))
    after = acl_entries(db)

    removed = before - after
    assert after - before == set()  # no concede nada nuevo (ni a anon/authenticated/PUBLIC)
    assert removed
    for kind, obj, grantee, _priv in removed:
        assert kind == "tabla" and grantee == "service_role"
        assert obj in {f"public.{t}" for t in TABLES}, obj
    # Y service_role conserva el acceso a las demás tablas por los defaults (alcance previsto).
    for table in ("questions", "sessions", "attempts"):
        assert effective_table_privileges(db, "service_role", table)["SELECT"] is True, table


def test_the_new_migration_is_idempotent_and_does_not_touch_data(db, fresh):
    before = counts(db)
    for _ in range(2):
        db.execute(NEW[0].read_text(encoding="utf-8"))

    assert counts(db) == before
    assert not any(effective_table_privileges(db, "service_role", "question_keys").values())


# --- actualización: base con las tres anteriores y datos ---------------------------------------------


def test_updating_a_database_with_data_applies_only_the_new_migration(db, seed, repo):
    install(db, PREVIOUS)
    team = seed.team()
    user = seed.user(team)
    seed.bank(3)
    seed_secrets(db, seed)
    session = repo.create_session(user_id=user, team_id=team, mode="random", area=None,
                                  stage=None, question_count=3)
    first = repo.issue_next_question(session.id)
    repo.record_answer(session.id, first.position, "A")  # un intento ya registrado
    data_before, structure_before = counts(db), structure(db)
    acl_before = acl_entries(db)

    db.execute(NEW[0].read_text(encoding="utf-8"))  # SOLO la nueva

    assert counts(db) == data_before  # datos intactos
    assert structure(db) == structure_before  # RLS, funciones, triggers, propietarios, políticas
    changed = acl_before ^ acl_entries(db)
    assert changed and all(e[2] == "service_role" and e[1] in {f"public.{t}" for t in TABLES}
                           for e in changed)
    assert not any(effective_table_privileges(db, "service_role", t)["SELECT"] for t in TABLES)
    # Los permisos de los roles del navegador no cambiaron.
    assert not any(effective_table_privileges(db, "anon", "question_keys").values())
    assert not any(effective_table_privileges(db, "authenticated", "question_assets").values())

    # El backend (rol propietario) sigue leyendo claves y figuras y emitiendo y calificando:
    second = repo.issue_next_question(session.id)
    attempt = repo.record_answer(session.id, second.position, "B")
    assert attempt.correct_option in "ABCDE" and attempt.position == second.position
    assert len(repo.list_attempts(session.id)) == 2
    manifest = db.execute("SELECT question_id FROM public.session_questions WHERE session_id = %s "
                          "AND position = %s", (session.id, second.position)).fetchone()
    db.execute("INSERT INTO public.question_assets (question_id, ref, mime_type, sha256, data) "
               "VALUES (%s, 'assets/post-01.png', 'image/png', %s, %s)",
               (manifest["question_id"], "c" * 64, PNG))
    served = repo.get_question_asset(session.id, second.position, "assets/post-01.png")
    assert served is not None and served.data == PNG
    # La restricción de versiones usadas sigue vigente.
    expect_error_in_server(
        db, f"UPDATE public.questions SET statement_md = 'cambiado' WHERE id = '{manifest['question_id']}'",
        "Versión usada")


def test_the_importer_still_loads_questions_keys_and_figures_after_the_change(db, importer, tmp_path):
    """El importador usa el rol propietario: carga preguntas, claves y figuras con la 4.ª aplicada."""
    from test_importador import CURATION, bank, plan_of, with_figure  # noqa: PLC0415

    install(db, FILES)
    # Como en producción, los triggers de clave se evalúan al final.
    db.execute("SET CONSTRAINTS ALL DEFERRED")
    plan = with_figure(importer, tmp_path)

    result = importer.apply_plan(db, plan, CURATION["verified_basis"])

    assert result.inserted == len(bank()) and result.assets_inserted == 1
    row = db.execute("SELECT count(*) AS k, count(*) FILTER (WHERE verified_at IS NOT NULL) AS v "
                     "FROM public.question_keys").fetchone()
    assert row["k"] == len(bank()) and row["v"] == 5  # las 5 activas, con verified_at
    assert db.execute("SELECT count(*) AS n FROM public.question_assets").fetchone()["n"] == 1
    # Y service_role sigue sin poder leer lo recién cargado.
    with as_role(db, "service_role"):
        denied(db, "SELECT * FROM public.question_keys")
        denied(db, "SELECT data FROM public.question_assets")
    assert plan_of(importer)  # el plan sin figura también se construye (sanidad del helper)


# --- vías que la migración NO cierra (hallazgos documentados, fuera de su alcance) --------------------


def test_residual_path_service_role_can_still_infer_keys_from_attempts(db, seed, repo):
    """La migración protege las DOS tablas, no la información derivada.

    `attempts` guarda `is_correct` y `selected_option`; con `session_questions` se deduce la
    clave de las preguntas ya respondidas. service_role conserva SELECT sobre esas tablas por
    los privilegios por defecto. Esto NO lo corrige la 4.ª migración (otro alcance); si se
    decide cerrar, será otra migración y esta prueba pasa a negar el acceso.
    """
    install(db, FILES)
    team = seed.team()
    user = seed.user(team)
    seed.bank(2)
    session = repo.create_session(user_id=user, team_id=team, mode="random", area=None,
                                  stage=None, question_count=3)
    first = repo.issue_next_question(session.id)
    repo.record_answer(session.id, first.position, "A")

    with as_role(db, "service_role"):
        rows = db.execute(
            "SELECT a.selected_option, a.is_correct FROM public.attempts a "
            "JOIN public.session_questions sq ON sq.session_id = a.session_id AND sq.position = a.position"
        ).fetchall()
        denied(db, "SELECT correct_option FROM public.question_keys")  # la tabla directa, no

    assert len(rows) == 1 and rows[0]["is_correct"] is True  # la clave de esa pregunta es "A"


def test_service_role_has_no_access_to_the_private_schema_in_the_emulation(db, fresh):
    # Con los defaults emulados (solo public). En el real no está verificado.
    assert db.execute("SELECT has_schema_privilege('service_role', 'cane_private', 'USAGE') AS ok"
                      ).fetchone()["ok"] is False
