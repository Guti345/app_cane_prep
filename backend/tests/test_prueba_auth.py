"""scripts/prueba_auth.py y scripts/backend_pruebas.py: sin red real, sin contraseña real.

Todo se prueba con mocks: ninguna prueba inicia sesión ni toca Supabase, y los valores que
parecen claves o tokens son cadenas ficticias.
"""

import base64
import importlib.util
import io
import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prueba_auth.py"
ROOT = SCRIPT.parents[1]
REAL_RUN = subprocess.run  # los de verdad, antes de que `no_subprocess` los bloquee
REAL_POPEN = subprocess.Popen

TEST_REF = "yqhtmrlwxgvxyiekzscb"
REAL_REF = "lzzyuxploolyqgitjtdu"
PUBLIC_KEY = "sb_publishable_CLAVE_FICTICIA_DE_PRUEBA"
OTHER_KEY = "sb_publishable_OTRA_CLAVE_FICTICIA"
SECRET_KEY = "sb_secret_CLAVE_SECRETA_FICTICIA"
TOKEN = "eyJ-token-ficticio-que-nunca-debe-imprimirse"
PASSWORD = "contrasena-ficticia-no-imprimir"


def jwt(**claims) -> str:
    def part(value: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'HS256'})}.{part(claims)}.firma-ficticia"


@pytest.fixture(scope="module")
def pa():
    spec = importlib.util.spec_from_file_location("prueba_auth", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["prueba_auth"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_subprocess(monkeypatch):
    """El camino normal nunca debe lanzar un proceso (ni `npx`)."""

    def boom(*args, **kwargs):
        raise AssertionError(f"Se intentó ejecutar un proceso: {args!r}")

    monkeypatch.setattr(subprocess, "Popen", boom)
    monkeypatch.setattr(subprocess, "run", boom)


@pytest.fixture
def root(tmp_path):
    """Un 'repositorio' vacío con las carpetas que usa el script."""
    (tmp_path / "frontend").mkdir()
    (tmp_path / "private-data").mkdir()
    return tmp_path


def write_env(path: Path, **values: str) -> None:
    path.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n", encoding="utf-8")


def frontend_env(root: Path, url: str | None = None, key: str = PUBLIC_KEY) -> None:
    write_env(
        root / "frontend" / ".env",
        VITE_API_URL="http://localhost:8000",
        VITE_SUPABASE_URL=url or f"https://{TEST_REF}.supabase.co",
        VITE_SUPABASE_PUBLISHABLE_KEY=key,
    )


class Response:
    def __init__(self, body: bytes = b"{}", status: int = 200):
        self._body, self.status = body, status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """urlopen simulado: registra las peticiones y responde según un guion."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[tuple[str, str, dict, float | None]] = []

    def __call__(self, request, timeout=None):
        self.requests.append(
            (request.full_url, request.get_method(), dict(request.header_items()), timeout)
        )
        outcome = self.outcomes.pop(0) if self.outcomes else Response()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def http_error(code: int, body: bytes = b"{}") -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "msg", {}, io.BytesIO(body))  # type: ignore[arg-type]


# --- partes sin red (ya existían) ---------------------------------------------------------------


def test_refuses_the_real_project(pa):
    with pytest.raises(SystemExit, match="proyecto real"):
        pa.supabase_url(pa.BLOCKED_REFS[0])


def test_url_points_to_the_test_project_by_default(pa):
    assert pa.supabase_url() == f"https://{pa.TEST_REF}.supabase.co"


def test_only_the_public_key_is_picked(pa):
    keys = [
        {"name": "service_role", "api_key": "SECRETA"},
        {"name": "default", "api_key": "SECRETA2"},
        {"name": "anon", "api_key": "PUBLICA"},
    ]
    assert pa.pick_publishable_key(keys) == "PUBLICA"
    assert pa.pick_publishable_key([keys[0], keys[1]]) is None
    assert pa.pick_publishable_key([{"name": "anon", "api_key": ""}]) is None


def test_token_file_is_ignored_by_git(pa, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", REAL_POPEN)  # esta consulta a git sí es real y local
    rel = pa.TOKEN_FILE.relative_to(pa.ROOT)
    result = REAL_RUN(["git", "check-ignore", "-q", str(rel)], cwd=pa.ROOT)
    assert result.returncode == 0, "private-data/ debe estar ignorada por Git"
    dedicated = REAL_RUN(["git", "check-ignore", "-q", pa.DEDICATED_ENV.as_posix()], cwd=pa.ROOT)
    assert dedicated.returncode == 0


def test_gitignore_covers_private_files(pa):
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "private-data/" in text  # token_prueba.json y supabase_pruebas.env viven ahí
    assert pa.TOKEN_FILE.parent.name == "private-data"
    assert pa.DEDICATED_ENV.parts[0] == "private-data"


# --- configuración pública: válida --------------------------------------------------------------


def test_valid_config_from_frontend_env_is_reused_without_running_npx(pa, root):
    frontend_env(root)
    opener = FakeOpener(Response())
    messages: list[str] = []

    cfg = pa.load_test_config(root=root, env={}, opener=opener, out=messages.append)

    assert cfg.url == f"https://{TEST_REF}.supabase.co"
    assert cfg.key == PUBLIC_KEY
    assert cfg.source == "frontend/.env"
    # La clave se comprobó con Auth del proyecto de pruebas (no con la CLI) ...
    url, method, headers, timeout = opener.requests[0]
    assert (url, method) == (f"https://{TEST_REF}.supabase.co/auth/v1/settings", "GET")
    assert headers["Apikey"] == PUBLIC_KEY and timeout == pa.VERIFY_TIMEOUT_SECONDS
    # ... y nunca se imprime ni se incluye en el repr.
    assert PUBLIC_KEY not in "\n".join(messages) and PUBLIC_KEY not in repr(cfg)


def test_the_dedicated_file_wins_even_if_frontend_env_points_to_the_real_project(pa, root):
    frontend_env(root, url=f"https://{REAL_REF}.supabase.co", key=OTHER_KEY)
    write_env(
        root / "private-data" / "supabase_pruebas.env",
        SUPABASE_URL=f"https://{TEST_REF}.supabase.co/",
        SUPABASE_PUBLISHABLE_KEY=PUBLIC_KEY,
    )

    cfg = pa.load_test_config(root=root, env={}, verify=False, out=lambda _m: None)

    assert cfg.key == PUBLIC_KEY and cfg.source == "private-data/supabase_pruebas.env"
    assert cfg.url == f"https://{TEST_REF}.supabase.co"  # sin la barra final


def test_a_complete_pair_in_the_environment_is_accepted(pa, root):
    env = {"SUPABASE_URL": f"https://{TEST_REF}.supabase.co", "SUPABASE_PUBLISHABLE_KEY": PUBLIC_KEY}

    cfg = pa.load_test_config(root=root, env=env, verify=False, out=lambda _m: None)

    assert cfg.source == "variables de entorno"


def test_frontend_env_local_overrides_frontend_env_like_vite(pa, root):
    frontend_env(root, key=OTHER_KEY)
    write_env(root / "frontend" / ".env.local", VITE_SUPABASE_PUBLISHABLE_KEY=PUBLIC_KEY)

    cfg = pa.load_test_config(root=root, env={}, verify=False, out=lambda _m: None)

    assert cfg.key == PUBLIC_KEY


# --- configuración ausente, incompleta o en conflicto ---------------------------------------------


def test_missing_config_fails_fast_with_instructions_before_asking_anything(pa, root, monkeypatch):
    monkeypatch.setattr(pa, "ROOT", root)
    monkeypatch.setattr(pa, "TOKEN_FILE", root / "private-data" / "token_prueba.json")
    asked = []

    def ask(_prompt):
        asked.append(_prompt)
        return ""

    with pytest.raises(SystemExit) as exc:
        pa.main([], input_fn=ask, getpass_fn=ask, opener=FakeOpener(), out=lambda _m: None)

    assert asked == []  # falla antes de pedir correo y contraseña
    message = str(exc.value)
    assert "private-data/supabase_pruebas.env" in message and "SUPABASE_PUBLISHABLE_KEY=" in message
    assert f"https://{TEST_REF}.supabase.co" in message
    assert "Publishable key" in message  # dónde verla


@pytest.mark.parametrize(
    "env",
    [
        {"SUPABASE_PUBLISHABLE_KEY": PUBLIC_KEY},  # clave suelta: no prueba su proyecto
        {"SUPABASE_URL": f"https://{TEST_REF}.supabase.co"},  # URL sola
        {"VITE_SUPABASE_PUBLISHABLE_KEY": PUBLIC_KEY},
    ],
)
def test_a_loose_variable_in_the_environment_is_not_accepted(pa, root, env):
    frontend_env(root)  # aunque haya una configuración válida en el archivo

    with pytest.raises(SystemExit, match="solo una de las dos"):
        pa.load_test_config(root=root, env=env, verify=False, out=lambda _m: None)


def test_environment_and_file_conflict_is_rejected_without_printing_values(pa, root):
    frontend_env(root, key=PUBLIC_KEY)
    env = {"SUPABASE_URL": f"https://{TEST_REF}.supabase.co", "SUPABASE_PUBLISHABLE_KEY": OTHER_KEY}

    with pytest.raises(SystemExit, match="CONFLICTO") as exc:
        pa.load_test_config(root=root, env=env, verify=False, out=lambda _m: None)

    assert PUBLIC_KEY not in str(exc.value) and OTHER_KEY not in str(exc.value)


def test_two_names_with_different_values_in_the_environment_conflict(pa, root):
    env = {
        "SUPABASE_URL": f"https://{TEST_REF}.supabase.co",
        "VITE_SUPABASE_URL": f"https://{REAL_REF}.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": PUBLIC_KEY,
    }

    with pytest.raises(SystemExit, match="CONFLICTO"):
        pa.load_test_config(root=root, env=env, verify=False, out=lambda _m: None)


def test_an_incomplete_file_names_what_is_missing(pa, root):
    write_env(root / "frontend" / ".env", VITE_SUPABASE_URL=f"https://{TEST_REF}.supabase.co")

    with pytest.raises(SystemExit, match="VITE_SUPABASE_PUBLISHABLE_KEY"):
        pa.load_test_config(root=root, env={}, verify=False, out=lambda _m: None)


# --- destino real y claves no públicas ------------------------------------------------------------


@pytest.mark.parametrize(
    "url, match",
    [
        (f"https://{REAL_REF}.supabase.co", "proyecto real"),
        (f"https://{REAL_REF}.supabase.co/", "proyecto real"),
        ("https://abcdefghijklmnopqrst.supabase.co", "no es la del proyecto de pruebas"),
        (f"http://{TEST_REF}.supabase.co", "no es la del proyecto de pruebas"),
        (f"https://{TEST_REF}.supabase.co.otro.test", "no es la del proyecto de pruebas"),
        (f"https://otro.test/{TEST_REF}", "no es la del proyecto de pruebas"),
    ],
)
def test_only_the_exact_test_project_url_is_accepted(pa, root, url, match):
    frontend_env(root, url=url)

    with pytest.raises(SystemExit, match=match):
        pa.load_test_config(root=root, env={}, verify=False, out=lambda _m: None)


@pytest.mark.parametrize(
    "key, match",
    [
        (SECRET_KEY, "secreta"),
        (jwt(role="service_role", ref=TEST_REF), "no es de rol anon"),
        (jwt(role="anon", ref=REAL_REF), "proyecto real"),
        (jwt(role="anon", ref="abcdefghijklmnopqrst"), "otro proyecto"),
        ("clave-sin-formato-conocido", "formato de clave no reconocido"),
        ("a.b.c", "no se puede interpretar"),
        ("", "Falta la clave"),
    ],
)
def test_only_a_public_key_is_accepted_and_it_is_never_echoed(pa, root, key, match):
    with pytest.raises(SystemExit, match=match) as exc:
        pa.check_public_key(key)

    assert key == "" or key not in str(exc.value)


def test_an_anon_jwt_of_the_test_project_is_accepted(pa):
    pa.check_public_key(jwt(role="anon", ref=TEST_REF))
    pa.check_public_key(jwt(role="anon"))  # sin `ref`: el emparejamiento lo comprueba Auth


def test_a_secret_key_in_the_config_file_is_rejected(pa, root):
    frontend_env(root, key=SECRET_KEY)

    with pytest.raises(SystemExit, match="secreta") as exc:
        pa.load_test_config(root=root, env={}, verify=False, out=lambda _m: None)

    assert SECRET_KEY not in str(exc.value)


def test_private_backend_variables_are_not_read_from_the_backend_environment(pa, root):
    # DATABASE_URL u otras variables privadas jamás se consideran: solo los 4 nombres públicos.
    write_env(root / "frontend" / ".env", DATABASE_URL="postgresql://u:p@h/db",
              VITE_SUPABASE_URL=f"https://{TEST_REF}.supabase.co", VITE_SUPABASE_PUBLISHABLE_KEY=PUBLIC_KEY)

    cfg = pa.load_test_config(root=root, env={"DATABASE_URL": "postgresql://u:p@h/db"},
                              verify=False, out=lambda _m: None)

    assert cfg.key == PUBLIC_KEY
    assert "postgresql" not in repr(cfg)


# --- comprobación del par URL + clave ---------------------------------------------------------------


def test_auth_rejecting_the_key_stops_before_asking_for_credentials(pa, root):
    frontend_env(root)

    with pytest.raises(SystemExit, match="no acepta esa clave") as exc:
        pa.load_test_config(root=root, env={}, opener=FakeOpener(http_error(401)), out=lambda _m: None)

    assert PUBLIC_KEY not in str(exc.value)


@pytest.mark.parametrize(
    "outcome",
    [urllib.error.URLError("sin red"), TimeoutError("timed out"), http_error(503), http_error(404)],
    ids=["red", "tiempo", "503", "404"],
)
def test_a_network_problem_while_verifying_warns_but_does_not_block(pa, root, outcome):
    frontend_env(root)
    messages: list[str] = []

    cfg = pa.load_test_config(root=root, env={}, opener=FakeOpener(outcome), out=messages.append)

    assert cfg.key == PUBLIC_KEY
    assert any("no pude verificar" in m for m in messages)
    assert PUBLIC_KEY not in "\n".join(messages)


# --- inicio de sesión (mocks) -------------------------------------------------------------------------


@pytest.fixture
def session(pa, root, monkeypatch):
    monkeypatch.setattr(pa, "ROOT", root)
    monkeypatch.setattr(pa, "TOKEN_FILE", root / "private-data" / "token_prueba.json")
    frontend_env(root)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
    monkeypatch.delenv("VITE_SUPABASE_URL", raising=False)
    monkeypatch.delenv("VITE_SUPABASE_PUBLISHABLE_KEY", raising=False)
    return root


def run_main(pa, opener, *, email="persona@ejemplo.test", getpass_fn=None, argv=None):
    printed: list[str] = []
    code = pa.main(
        argv or [],
        input_fn=lambda _p: email,
        getpass_fn=getpass_fn or (lambda _p: PASSWORD),
        opener=opener,
        out=printed.append,
    )
    return code, "\n".join(printed)


def login_response(token: str = TOKEN, expires_in: int = 3600) -> Response:
    return Response(json.dumps({"access_token": token, "expires_in": expires_in}).encode())


def test_successful_login_saves_the_token_without_printing_it(pa, session, capsys):
    opener = FakeOpener(Response(), login_response())  # 1.º verificación de la clave; 2.º login

    code, printed = run_main(pa, opener)

    assert code == 0
    saved = json.loads(pa.TOKEN_FILE.read_text(encoding="utf-8"))
    assert saved["access_token"] == TOKEN and saved["expires_at"] > 0
    everything = printed + capsys.readouterr().out + capsys.readouterr().err
    for secret in (TOKEN, PASSWORD, PUBLIC_KEY):
        assert secret not in everything
    assert "pruebas_cane" in printed.splitlines()[0]  # destino visible desde el primer mensaje
    # El login fue un POST con la clave publicable y un tiempo de espera acotado.
    url, method, headers, timeout = opener.requests[1]
    assert (method, timeout) == ("POST", pa.HTTP_TIMEOUT_SECONDS)
    assert url == f"https://{TEST_REF}.supabase.co/auth/v1/token?grant_type=password"
    assert headers["Apikey"] == PUBLIC_KEY
    assert not pa.TOKEN_FILE.with_name(pa.TOKEN_FILE.name + ".tmp").exists()


def test_the_password_is_asked_with_getpass_and_never_passed_as_an_argument(pa):
    import inspect

    params = inspect.signature(pa.main).parameters
    assert "getpass_fn" in params
    assert "password" not in " ".join(sys.argv)
    source = SCRIPT.read_text(encoding="utf-8")
    assert "getpass.getpass" in source and "--password" not in source
    assert "shell=True" not in source


def test_a_failed_login_leaves_no_token_and_removes_a_stale_one(pa, session):
    pa.TOKEN_FILE.write_text(json.dumps({"access_token": "token-anterior", "expires_at": 1}), encoding="utf-8")
    opener = FakeOpener(Response(), http_error(400, json.dumps({"error_code": "invalid_credentials",
                                                                   "msg": f"cuerpo con {PASSWORD}"}).encode()))
    printed: list[str] = []

    with pytest.raises(SystemExit) as exc:
        pa.main([], input_fn=lambda _p: "persona@ejemplo.test", getpass_fn=lambda _p: PASSWORD,
                opener=opener, out=printed.append)

    assert not pa.TOKEN_FILE.exists()  # ni el anterior ni uno nuevo
    message = str(exc.value)
    assert "HTTP 400" in message and "invalid_credentials" in message
    assert "No se guardó ningún token" in message
    assert PASSWORD not in message and PASSWORD not in "\n".join(printed)  # sin volcar el cuerpo
    assert any("token anterior" in line for line in printed)  # y se dijo qué se hizo


def test_a_config_error_does_not_delete_a_valid_previous_token(pa, session):
    frontend_env(session, url=f"https://{REAL_REF}.supabase.co")  # configuración inválida
    pa.TOKEN_FILE.write_text(json.dumps({"access_token": "token-anterior", "expires_at": 1}), encoding="utf-8")

    with pytest.raises(SystemExit, match="proyecto real"):
        run_main(pa, FakeOpener())

    assert pa.TOKEN_FILE.exists()  # nada se tocó: el login ni siquiera empezó


@pytest.mark.parametrize(
    "failure, expected",
    [
        (urllib.error.URLError("fallo de red"), "red"),
        (TimeoutError("timed out"), "Se agotó el tiempo"),
        (urllib.error.URLError(TimeoutError("timed out")), "Se agotó el tiempo"),
    ],
)
def test_network_and_timeout_errors_are_short_and_leave_no_token(pa, session, failure, expected):
    opener = FakeOpener(Response(), failure)

    with pytest.raises(SystemExit) as exc:
        run_main(pa, opener)

    assert expected in str(exc.value) and "No se guardó ningún token" in str(exc.value)
    assert not pa.TOKEN_FILE.exists()
    assert "Traceback" not in str(exc.value)


def test_ctrl_c_ends_cleanly_without_a_traceback_or_token(pa, session):
    def cancel(_prompt):
        raise KeyboardInterrupt

    code, printed = run_main(pa, FakeOpener(Response()), getpass_fn=cancel)

    assert code == 130
    assert "Cancelado" in printed
    assert not pa.TOKEN_FILE.exists()


def test_ctrl_c_during_the_request_also_ends_cleanly(pa, session):
    opener = FakeOpener(Response(), KeyboardInterrupt())

    code, printed = run_main(pa, opener)

    assert code == 130 and not pa.TOKEN_FILE.exists()


def test_a_response_without_token_is_not_saved(pa, session):
    opener = FakeOpener(Response(), Response(b'{"expires_in": 3600}'))

    with pytest.raises(SystemExit, match="access_token"):
        run_main(pa, opener)

    assert not pa.TOKEN_FILE.exists()


def test_delete_removes_the_token_and_is_idempotent(pa, session):
    pa.TOKEN_FILE.write_text("{}", encoding="utf-8")

    first = run_main(pa, FakeOpener(), argv=["--borrar"])
    second = run_main(pa, FakeOpener(), argv=["--borrar"])

    assert first[0] == second[0] == 0
    assert not pa.TOKEN_FILE.exists()


def test_the_normal_path_never_runs_npx(pa, session):
    # `no_subprocess` (autouse) hace fallar cualquier Popen/run: este login debe pasar sin ellos.
    code, _ = run_main(pa, FakeOpener(Response(), login_response()))

    assert code == 0


def test_the_script_does_not_call_the_cli_unless_asked(pa):
    source = SCRIPT.read_text(encoding="utf-8")
    default_path = source[source.index("def main("):]

    assert "--clave-desde-cli" in default_path  # solo detrás de la opción explícita
    assert "api-keys" not in default_path
    assert "shell=True" not in source


# --- opción explícita de CLI --------------------------------------------------------------------------


class FakeProc:
    def __init__(self, *, stdout="[]", timeout=False, interrupt=False, pid=4242):
        self.stdout, self._timeout, self._interrupt, self.pid = stdout, timeout, interrupt, pid
        self.killed = False

    def communicate(self, timeout=None):
        if self._timeout:
            raise subprocess.TimeoutExpired("npx", timeout)
        if self._interrupt:
            raise KeyboardInterrupt
        return self.stdout, ""

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return 0


def cli(pa, monkeypatch, proc: FakeProc):
    """Ejecuta key_from_cli con un Popen simulado; devuelve (clave o error, comandos lanzados)."""
    launched: list[list[str]] = []
    killed: list[str] = []

    def popen(cmd, **kwargs):
        launched.append(cmd)
        assert kwargs["stdin"] is subprocess.DEVNULL  # sin prompts ocultos
        return proc

    monkeypatch.setattr(pa.subprocess, "run", lambda cmd, **kw: killed.append(" ".join(cmd)))
    return popen, launched, killed


def test_cli_option_has_no_install_no_shell_and_a_time_limit(pa, monkeypatch):
    proc = FakeProc(stdout=json.dumps([{"name": "anon", "api_key": PUBLIC_KEY}]))
    popen, launched, _ = cli(pa, monkeypatch, proc)

    key = pa.key_from_cli(popen=popen, timeout=7)

    assert key == PUBLIC_KEY
    cmd = launched[0]
    assert "--no-install" in cmd and "projects" in cmd and TEST_REF in cmd
    assert REAL_REF not in " ".join(cmd)
    assert isinstance(cmd, list)  # sin shell


def test_cli_option_kills_only_its_own_process_on_timeout(pa, monkeypatch):
    proc = FakeProc(timeout=True, pid=4242)
    popen, _, killed = cli(pa, monkeypatch, proc)

    with pytest.raises(SystemExit, match="no respondió"):
        pa.key_from_cli(popen=popen, timeout=1)

    if sys.platform == "win32":
        assert killed == ["taskkill /T /F /PID 4242"]  # su propio PID, nada más
    else:
        assert proc.killed


def test_cli_option_cleans_up_on_cancel_and_reraises(pa, monkeypatch):
    proc = FakeProc(interrupt=True, pid=777)
    popen, _, killed = cli(pa, monkeypatch, proc)

    with pytest.raises(KeyboardInterrupt):
        pa.key_from_cli(popen=popen)

    assert (killed == ["taskkill /T /F /PID 777"]) if sys.platform == "win32" else proc.killed


def test_cli_output_is_never_printed_and_secret_keys_are_not_picked(pa, monkeypatch, capsys):
    out = json.dumps([{"name": "service_role", "api_key": SECRET_KEY}])
    popen, _, _ = cli(pa, monkeypatch, FakeProc(stdout=out))

    with pytest.raises(SystemExit, match="no devolvió una clave publicable"):
        pa.key_from_cli(popen=popen)

    captured = capsys.readouterr()
    assert SECRET_KEY not in captured.out + captured.err


def test_main_with_the_cli_flag_still_validates_the_key(pa, session, monkeypatch):
    monkeypatch.setattr(pa, "key_from_cli", lambda *a, **k: SECRET_KEY)

    with pytest.raises(SystemExit, match="secreta"):
        run_main(pa, FakeOpener(), argv=["--clave-desde-cli"])


# --- backend_pruebas.py usa el mismo helper -----------------------------------------------------------


@pytest.fixture(scope="module")
def bp():
    spec = importlib.util.spec_from_file_location("backend_pruebas", SCRIPT.with_name("backend_pruebas.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["backend_pruebas"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "192.168.1.3", "10.0.0.5", "172.16.4.9"])
def test_backend_pruebas_listens_only_on_local_or_private_addresses(bp, host):
    assert bp.check_bind_host(host) == host


@pytest.mark.parametrize("host", ["0.0.0.0", "8.8.8.8", "203.0.113.7", "mi-equipo.local", "::"])
def test_backend_pruebas_refuses_public_or_unspecified_addresses(bp, host):
    with pytest.raises(SystemExit, match="RECHAZADO"):
        bp.check_bind_host(host)


def test_backend_pruebas_starts_with_the_verified_config_and_never_runs_npx(bp, monkeypatch, tmp_path, capsys):
    import uvicorn

    import app.main as app_main

    captured = {}
    real_create_app = app_main.create_app

    def spy_create_app(settings=None, **kw):
        captured["settings"] = settings
        return real_create_app(settings, **kw)

    monkeypatch.setattr(app_main, "create_app", spy_create_app)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: captured.update(app=app, kw=kw))
    monkeypatch.setenv("IMPORT_DATABASE_URL",
                       f"postgresql://postgres.{TEST_REF}:x@aws-0-eu.pooler.supabase.com:5432/postgres")
    monkeypatch.setenv("SUPABASE_URL", f"https://{TEST_REF}.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", PUBLIC_KEY)
    opener = FakeOpener(Response())
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", opener)

    code = bp.main(["--port", "8765"], config_root=tmp_path)  # sin archivos: solo el entorno

    assert code == 0
    assert captured["kw"]["host"] == "127.0.0.1" and captured["kw"]["port"] == 8765
    settings = captured["settings"]  # la pareja validada es la que llega al backend
    assert settings.supabase_url == f"https://{TEST_REF}.supabase.co"
    assert settings.supabase_publishable_key == PUBLIC_KEY
    assert captured["app"].state.auth is not None
    out = capsys.readouterr().out
    assert "pruebas_cane" in out and PUBLIC_KEY not in out
    assert opener.requests and opener.requests[0][0].endswith("/auth/v1/settings")


def test_backend_pruebas_refuses_a_real_project_url_in_the_environment(bp, monkeypatch, tmp_path):
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("no debía arrancar"))
    monkeypatch.setenv("IMPORT_DATABASE_URL",
                       f"postgresql://postgres.{TEST_REF}:x@aws-0-eu.pooler.supabase.com:5432/postgres")
    monkeypatch.setenv("SUPABASE_URL", f"https://{REAL_REF}.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", PUBLIC_KEY)

    with pytest.raises(SystemExit, match="proyecto real"):
        bp.main(["--port", "8766"], config_root=tmp_path)
