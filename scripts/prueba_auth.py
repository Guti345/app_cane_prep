"""Login real con Supabase Auth de un usuario de PRUEBAS, para pruebas locales.

Lo ejecuta una persona en su terminal; la contraseña se pide con `getpass` (no se
muestra, no queda en el historial, no se pasa como argumento) y el token NO se
imprime. El resultado se guarda en `private-data/token_prueba.json`, que Git
ignora; dura lo que dure el token (normalmente 1 hora).

    backend\\.venv\\Scripts\\python scripts\\prueba_auth.py
    backend\\.venv\\Scripts\\python scripts\\prueba_auth.py --borrar     # elimina el archivo

Solo funciona contra el proyecto de pruebas; se niega con el real.

La clave publicable (pública por diseño: el navegador también la lleva) se toma
de la variable SUPABASE_PUBLISHABLE_KEY o, si no existe, de la CLI de Supabase
(`projects api-keys`, que enmascara las claves secretas).
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "private-data" / "token_prueba.json"

TEST_REF = "yqhtmrlwxgvxyiekzscb"  # pruebas_cane
BLOCKED_REFS = ("lzzyuxploolyqgitjtdu",)  # proyecto real


def supabase_url(ref: str = TEST_REF) -> str:
    if ref in BLOCKED_REFS:
        raise SystemExit("RECHAZADO: este script no opera contra el proyecto real.")
    return f"https://{ref}.supabase.co"


def pick_publishable_key(api_keys: list[dict]) -> str | None:
    """La clave pública (anon/publishable) de la lista de la CLI; nunca una secreta."""
    for entry in api_keys:
        name = str(entry.get("name") or entry.get("id") or "")
        key = entry.get("api_key")
        if name in ("anon", "publishable") and isinstance(key, str) and key:
            return key
    return None


def publishable_key(ref: str = TEST_REF) -> str:
    from_env = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if from_env:
        return from_env
    result = subprocess.run(
        f"npx supabase projects api-keys --project-ref {ref} -o json",
        shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = result.stdout
    try:
        keys = json.loads(out[out.index("["): out.rindex("]") + 1])
    except ValueError:
        keys = []
    key = pick_publishable_key(keys)
    if not key:
        raise SystemExit(
            "No pude obtener la clave publicable. Define SUPABASE_PUBLISHABLE_KEY "
            "(Project Settings > API) o inicia sesión en la CLI de Supabase."
        )
    return key


def sign_in(base_url: str, apikey: str, email: str, password: str) -> dict:
    request = urllib.request.Request(
        f"{base_url}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": email, "password": password}).encode("utf-8"),
        headers={"apikey": apikey, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8"))
            message = detail.get("error_description") or detail.get("msg") or detail.get("error_code")
        except ValueError:
            message = None
        raise SystemExit(f"Supabase Auth rechazó el inicio de sesión (HTTP {exc.code}): {message}") from None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--borrar" in argv:
        TOKEN_FILE.unlink(missing_ok=True)
        print("Archivo de token eliminado.")
        return 0

    base_url = supabase_url()
    apikey = publishable_key()
    email = input("Correo del usuario de PRUEBAS: ").strip()
    password = getpass.getpass("Contraseña (no se muestra): ")
    data = sign_in(base_url, apikey, email, password)
    del password

    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise SystemExit("La respuesta de Auth no trae access_token.")
    expires_in = int(data.get("expires_in") or 3600)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps({"access_token": token, "expires_at": int(time.time()) + expires_in}),
        encoding="utf-8",
    )
    print(f"Inicio de sesión correcto. Token válido unos {expires_in // 60} min; "
          f"guardado en {TOKEN_FILE.relative_to(ROOT)} (ignorado por Git). No se imprimió.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
