"""Login real con Supabase Auth de un usuario de PRUEBAS, para pruebas locales.

Lo ejecuta una persona en su terminal; la contraseña se pide con `getpass` (no se
muestra, no queda en el historial, no se pasa como argumento) y el token NO se
imprime. El resultado se guarda en `private-data/token_prueba.json`, que Git
ignora; dura lo que dure el token (normalmente 1 hora).

    backend\\.venv\\Scripts\\python scripts\\prueba_auth.py
    backend\\.venv\\Scripts\\python scripts\\prueba_auth.py --borrar     # elimina el archivo

Solo funciona contra el proyecto de pruebas; se niega con el real.

Configuración pública (URL del proyecto + clave publicable, pública por diseño: el
navegador también la lleva). Se toma, en este orden, de:

1. variables de entorno `SUPABASE_URL` + `SUPABASE_PUBLISHABLE_KEY` (o las `VITE_*`),
   solo como pareja completa;
2. `private-data/supabase_pruebas.env` (ignorado por Git), con esas mismas dos variables;
3. `frontend/.env.local` y `frontend/.env` (`VITE_SUPABASE_URL` y
   `VITE_SUPABASE_PUBLISHABLE_KEY`), solo si su URL es la del proyecto de pruebas.

Nunca se ejecuta `npx` por defecto. La consulta de claves con la CLI de Supabase solo
ocurre con la opción explícita `--clave-desde-cli`.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "private-data" / "token_prueba.json"
DEDICATED_ENV = Path("private-data") / "supabase_pruebas.env"
FRONTEND_ENV_FILES = (Path("frontend") / ".env.local", Path("frontend") / ".env")

TEST_REF = "yqhtmrlwxgvxyiekzscb"  # pruebas_cane
BLOCKED_REFS = ("lzzyuxploolyqgitjtdu",)  # proyecto real

URL_NAMES = ("SUPABASE_URL", "VITE_SUPABASE_URL")
KEY_NAMES = ("SUPABASE_PUBLISHABLE_KEY", "VITE_SUPABASE_PUBLISHABLE_KEY")

HTTP_TIMEOUT_SECONDS = 20
VERIFY_TIMEOUT_SECONDS = 10
CLI_TIMEOUT_SECONDS = 30

Opener = Callable[..., Any]


def supabase_url(ref: str = TEST_REF) -> str:
    if ref in BLOCKED_REFS:
        raise SystemExit("RECHAZADO: este script no opera contra el proyecto real.")
    return f"https://{ref}.supabase.co"


# --- 1. configuración pública -----------------------------------------------------------


@dataclass(frozen=True)
class TestConfig:
    """URL del proyecto de pruebas y su clave publicable. La clave no aparece en el `repr`."""

    __test__ = False  # no es una clase de pruebas para pytest

    url: str
    key: str = field(repr=False)
    source: str


def read_env_file(path: Path) -> dict[str, str]:
    """Variables `NOMBRE=valor` de un archivo local. Nunca se imprimen sus valores."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if match and not line.lstrip().startswith("#"):
            values[match.group(1)] = match.group(2).strip().strip("\"'")
    return values


def _pick(values: dict[str, str], names: tuple[str, ...], what: str, where: str) -> str | None:
    """El valor de una familia de nombres; si hay varios y difieren, es un conflicto."""
    found = {n: values[n].strip() for n in names if values.get(n, "").strip()}
    if len(set(found.values())) > 1:
        raise SystemExit(
            f"CONFLICTO en {where}: {' y '.join(found)} tienen valores distintos ({what}). "
            "Deja uno solo."
        )
    return next(iter(found.values()), None)


def check_test_url(url: str) -> str:
    """La URL debe ser exactamente la del proyecto de pruebas. No se repite su valor."""
    normalized = url.strip().rstrip("/")
    if any(ref in normalized for ref in BLOCKED_REFS):
        raise SystemExit("RECHAZADO: la URL es la del proyecto real; este script no opera con él.")
    if normalized != supabase_url():
        raise SystemExit("RECHAZADO: la URL no es la del proyecto de pruebas (pruebas_cane).")
    return normalized


def check_public_key(key: str) -> None:
    """Acepta solo una clave publicable/anon. Nunca repite la clave en un mensaje."""
    if not key:
        raise SystemExit("Falta la clave publicable.")
    if key.startswith("sb_secret_"):
        raise SystemExit("RECHAZADO: es una clave secreta (sb_secret_...), no una publicable.")
    if key.startswith("sb_publishable_"):
        return
    if key.count(".") == 2:  # clave anon/service_role en formato JWT
        payload = key.split(".")[1]
        try:
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except (ValueError, UnicodeDecodeError):
            raise SystemExit("RECHAZADO: la clave no se puede interpretar.") from None
        if not isinstance(claims, dict) or claims.get("role") != "anon":
            raise SystemExit("RECHAZADO: la clave no es de rol anon (¿secreta o service_role?).")
        ref = claims.get("ref")
        if ref in BLOCKED_REFS:
            raise SystemExit("RECHAZADO: la clave es la del proyecto real.")
        if ref is not None and ref != TEST_REF:
            raise SystemExit("RECHAZADO: la clave pertenece a otro proyecto.")
        return
    raise SystemExit(
        "RECHAZADO: formato de clave no reconocido; se espera una clave publicable "
        "(sb_publishable_...) o anon."
    )


def verify_pair(url: str, key: str, *, opener: Opener | None = None, out: Callable[[str], None] = print) -> None:
    """Comprueba con Auth que la clave corresponde a ESE proyecto (GET /auth/v1/settings).

    Una clave suelta no prueba a qué proyecto pertenece. 401/403 es un rechazo; cualquier
    otro resultado (red, tiempo, otro estado) no impide seguir: el inicio de sesión mostrará
    si no corresponde. No se imprime nada de la respuesta.
    """
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(f"{url}/auth/v1/settings", headers={"apikey": key})
    try:
        with opener(request, timeout=VERIFY_TIMEOUT_SECONDS) as response:
            if getattr(response, "status", 200) == 200:
                out("Clave publicable verificada con el proyecto de pruebas.")
                return
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise SystemExit(
                "RECHAZADO: Auth no acepta esa clave para el proyecto de pruebas "
                f"(HTTP {exc.code}). Revisa que sea la publicable de pruebas_cane."
            ) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    out("Aviso: no pude verificar la clave contra el proyecto (red o tiempo); se continúa. "
        "El inicio de sesión dirá si no corresponde.")


def missing_config_message() -> str:
    return (
        "Falta la configuración pública del proyecto de pruebas. Crea el archivo local "
        f"{DEDICATED_ENV.as_posix()} (ignorado por Git) con dos líneas:\n"
        f"  SUPABASE_URL={supabase_url()}\n"
        "  SUPABASE_PUBLISHABLE_KEY=<clave publicable de pruebas_cane>\n"
        "La clave está en el panel del proyecto de PRUEBAS: Project Settings > API Keys > "
        "Publishable key. (También sirve completar VITE_SUPABASE_URL y "
        "VITE_SUPABASE_PUBLISHABLE_KEY en frontend/.env.) No es la contraseña ni una clave secreta."
    )


def load_test_config(
    *,
    root: Path | None = None,
    env: dict[str, str] | None = None,
    verify: bool = True,
    opener: Opener | None = None,
    out: Callable[[str], None] = print,
) -> TestConfig:
    """URL + clave publicable del proyecto de PRUEBAS, validadas. No ejecuta ningún comando."""
    root = root or ROOT
    env = dict(os.environ) if env is None else env

    # 1) Entorno: solo como pareja completa; una clave suelta no prueba su proyecto.
    env_url = _pick(env, URL_NAMES, "URL", "el entorno")
    env_key = _pick(env, KEY_NAMES, "clave", "el entorno")
    if bool(env_url) != bool(env_key):
        raise SystemExit(
            "El entorno trae solo una de las dos variables (URL o clave). Define la pareja "
            "completa (SUPABASE_URL y SUPABASE_PUBLISHABLE_KEY) o ninguna: una clave suelta "
            "no demuestra a qué proyecto pertenece."
        )

    # 2) Archivos locales ignorados, por orden de prioridad.
    file_url = file_key = None
    file_source = ""
    dedicated = root / DEDICATED_ENV
    if dedicated.is_file():
        values = read_env_file(dedicated)
        file_url = _pick(values, URL_NAMES, "URL", DEDICATED_ENV.as_posix())
        file_key = _pick(values, KEY_NAMES, "clave", DEDICATED_ENV.as_posix())
        file_source = DEDICATED_ENV.as_posix()
        if bool(file_url) != bool(file_key):
            raise SystemExit(
                f"{file_source} está incompleto: hacen falta SUPABASE_URL y "
                "SUPABASE_PUBLISHABLE_KEY."
            )
    if not file_url:
        merged: dict[str, str] = {}
        used = []
        for rel in reversed(FRONTEND_ENV_FILES):  # .env.local pisa a .env, como en Vite
            path = root / rel
            if path.is_file():
                merged.update(read_env_file(path))
                used.append(rel.as_posix())
        file_url = _pick(merged, URL_NAMES, "URL", "frontend/.env")
        file_key = _pick(merged, KEY_NAMES, "clave", "frontend/.env")
        file_source = " + ".join(reversed(used))
        if bool(file_url) != bool(file_key):
            raise SystemExit(
                "frontend/.env está incompleto: hacen falta VITE_SUPABASE_URL y "
                "VITE_SUPABASE_PUBLISHABLE_KEY."
            )

    if env_url and file_url and (env_url.rstrip("/") != file_url.rstrip("/") or env_key != file_key):
        raise SystemExit(
            f"CONFLICTO: el entorno y {file_source} traen valores distintos para la URL "
            "o la clave. Deja una sola fuente."
        )
    url, key, source = (
        (env_url, env_key, "variables de entorno") if env_url else (file_url, file_key, file_source)
    )
    if not url or not key:
        raise SystemExit(missing_config_message())

    url = check_test_url(url)
    assert key is not None
    check_public_key(key)
    out(f"Configuración pública de pruebas tomada de: {source}.")
    if verify:
        verify_pair(url, key, opener=opener, out=out)
    return TestConfig(url=url, key=key, source=source)


def publishable_key(ref: str = TEST_REF) -> str:
    """Compatibilidad: la clave de la configuración local verificada (nunca consulta la CLI)."""
    supabase_url(ref)  # rechaza el real
    return load_test_config(out=lambda _msg: None).key


# --- 2. opción explícita: clave desde la CLI de Supabase -------------------------------------


def pick_publishable_key(api_keys: list[dict]) -> str | None:
    """La clave pública (anon/publishable) de la lista de la CLI; nunca una secreta."""
    for entry in api_keys:
        name = str(entry.get("name") or entry.get("id") or "")
        key = entry.get("api_key")
        if name in ("anon", "publishable") and isinstance(key, str) and key:
            return key
    return None


def _kill_own_process_tree(proc: subprocess.Popen) -> None:
    """Termina SOLO el proceso lanzado por este script y sus hijos."""
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True, timeout=10, check=False,
            )
        else:
            proc.kill()
    except Exception:  # best effort: el proceso pudo haber terminado ya
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def key_from_cli(
    ref: str = TEST_REF,
    *,
    timeout: float = CLI_TIMEOUT_SECONDS,
    popen: Callable[..., Any] = subprocess.Popen,
) -> str:
    """Clave publicable según la CLI de Supabase. SOLO con `--clave-desde-cli`.

    Sin instalación (`--no-install`), sin entrada (no hay prompts ocultos), con límite de
    tiempo y sin imprimir su salida. Si vence o se cancela, termina únicamente el proceso
    propio.
    """
    supabase_url(ref)
    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    cmd = [npx, "--no-install", "supabase", "projects", "api-keys", "--project-ref", ref, "-o", "json"]
    proc = popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    try:
        stdout, _stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_own_process_tree(proc)
        raise SystemExit(
            f"La CLI de Supabase no respondió en {int(timeout)} s y se terminó. No se obtuvo la clave."
        ) from None
    except KeyboardInterrupt:
        _kill_own_process_tree(proc)
        raise
    try:
        keys = json.loads(stdout[stdout.index("["): stdout.rindex("]") + 1])
    except ValueError:
        keys = []
    key = pick_publishable_key(keys)
    if not key:
        raise SystemExit(
            "La CLI no devolvió una clave publicable (¿sesión de la CLI o paquete no instalado?). "
            f"Usa {DEDICATED_ENV.as_posix()} en su lugar."
        )
    return key


# --- 3. inicio de sesión --------------------------------------------------------------------


def sign_in(
    base_url: str,
    apikey: str,
    email: str,
    password: str,
    *,
    opener: Opener | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> dict:
    """POST /auth/v1/token. Errores sin cuerpo, cabeceras, claves ni token."""
    opener = opener or urllib.request.urlopen
    request = urllib.request.Request(
        f"{base_url}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": email, "password": password}).encode("utf-8"),
        headers={"apikey": apikey, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        code = None
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            candidate = detail.get("error_code") or detail.get("error")
            if isinstance(candidate, str) and re.fullmatch(r"[a-z_]{1,40}", candidate):
                code = candidate
        except (ValueError, AttributeError):
            pass
        suffix = f", {code}" if code else ""
        raise SystemExit(
            f"Supabase Auth rechazó el inicio de sesión (HTTP {exc.code}{suffix}). No se guardó ningún token."
        ) from None
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        timed_out = isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError) or "timed out" in str(reason)
        what = (
            f"Se agotó el tiempo de espera ({int(timeout)} s) al contactar con Supabase Auth."
            if timed_out
            else "No se pudo contactar con Supabase Auth (red)."
        )
        raise SystemExit(f"{what} No se guardó ningún token.") from None
    except ValueError:
        raise SystemExit("La respuesta de Auth no tiene el formato esperado. No se guardó ningún token.") from None


def _write_token(token: str, expires_in: int) -> None:
    """Escritura atómica: o queda el archivo completo o no queda ninguno nuevo."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_FILE.with_name(TOKEN_FILE.name + ".tmp")
    tmp.write_text(
        json.dumps({"access_token": token, "expires_at": int(time.time()) + expires_in}),
        encoding="utf-8",
    )
    os.replace(tmp, TOKEN_FILE)


def _delete_token() -> bool:
    existed = TOKEN_FILE.exists()
    TOKEN_FILE.unlink(missing_ok=True)
    TOKEN_FILE.with_name(TOKEN_FILE.name + ".tmp").unlink(missing_ok=True)
    return existed


def main(
    argv: list[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    getpass_fn: Callable[[str], str] = getpass.getpass,
    opener: Opener | None = None,
    out: Callable[[str], None] = print,
) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--borrar" in argv:
        _delete_token()
        out("Archivo de token eliminado.")
        return 0

    try:
        out(f"Destino: pruebas_cane (proyecto de PRUEBAS, ref {TEST_REF}). El proyecto real no se usa.")
        if "--clave-desde-cli" in argv:
            out(f"Consultando la clave publicable con la CLI de Supabase (máx. {CLI_TIMEOUT_SECONDS} s)...")
            key = key_from_cli()
            check_public_key(key)
            base_url = supabase_url()
            verify_pair(base_url, key, opener=opener, out=out)
        else:
            cfg = load_test_config(opener=opener, out=out)
            base_url, key = cfg.url, cfg.key

        # La configuración es válida: a partir de aquí un intento fallido no deja un token
        # anterior que pueda confundirse con su resultado.
        if _delete_token():
            out("Se eliminó el token anterior; solo quedará uno si este inicio de sesión es correcto.")
        email = input_fn("Correo del usuario de PRUEBAS: ").strip()
        password = getpass_fn("Contraseña (no se muestra): ")
        out(f"Contactando con Supabase Auth (máx. {HTTP_TIMEOUT_SECONDS} s)...")
        data = sign_in(base_url, key, email, password, opener=opener)
        del password

        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise SystemExit("La respuesta de Auth no trae access_token. No se guardó ningún token.")
        expires_in = int(data.get("expires_in") or 3600)
        _write_token(token, expires_in)
    except KeyboardInterrupt:
        # Si ya se había retirado el token anterior, no hay ninguno; si la cancelación llegó
        # antes (durante la configuración), el anterior no se toca. Solo se limpia el temporal.
        TOKEN_FILE.with_name(TOKEN_FILE.name + ".tmp").unlink(missing_ok=True)
        out("\nCancelado. No se guardó ningún token.")
        return 130
    except EOFError:
        raise SystemExit("No hay una terminal interactiva para escribir el correo y la contraseña.") from None
    out(f"Inicio de sesión correcto. Token válido unos {expires_in // 60} min; "
        f"guardado en {TOKEN_FILE.relative_to(ROOT).as_posix()} (ignorado por Git). No se imprimió.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
