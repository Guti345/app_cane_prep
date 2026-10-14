"""Backend FastAPI local contra el proyecto de PRUEBAS, con Supabase Auth real.

Solo para pruebas locales (por ejemplo desde un celular en la misma Wi-Fi). Toma:
- la conexión PostgreSQL de `private-data/importador.env` o de IMPORT_DATABASE_URL
  (ver docs/importador.md); no se imprime;
- la URL de Supabase del proyecto de pruebas y su clave publicable (pública por
  diseño), con la misma configuración local verificada de `prueba_auth.py`
  (`load_test_config`): no ejecuta `npx` ni consulta la CLI.

Se niega a operar si la cadena apunta al proyecto real, y solo escucha en
direcciones locales o de red privada (127.0.0.1, 192.168.x.x, 10.x.x.x, 172.16-31.x.x);
nunca en 0.0.0.0 ni en una IP pública.

    backend\\.venv\\Scripts\\python scripts\\backend_pruebas.py
    backend\\.venv\\Scripts\\python scripts\\backend_pruebas.py --host 192.168.1.3 --origin http://192.168.1.3:5173
"""

from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Solo estos rangos: loopback y RFC 1918. (`ipaddress.is_private` también acepta rangos de
# documentación y otros que no son una red doméstica.)
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def check_bind_host(host: str) -> str:
    """Acepta localhost y direcciones de red privada; rechaza 0.0.0.0 y las demás."""
    if host == "localhost":
        return host
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise SystemExit(f"RECHAZADO: {host!r} no es una dirección IP local.") from None
    if address.version != 4 or not any(address in net for net in PRIVATE_NETWORKS):
        raise SystemExit(
            f"RECHAZADO: {host} no es una dirección local ni de red privada "
            "(este script no abre el servicio al público)."
        )
    return host


def main(argv: list[str] | None = None, *, config_root: Path | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--origin", action="append", default=[],
                    help="origen del frontend permitido por CORS (repetible); por defecto localhost:5173")
    ap.add_argument("--solo-figuras", action="store_true",
                    help="solo para pruebas: las sesiones eligen entre preguntas activas con figura")
    args = ap.parse_args(argv)
    host = check_bind_host(args.host)

    imp = _load("importar_banco", "importar_banco.py")
    pa = _load("prueba_auth", "prueba_auth.py")
    import uvicorn

    import app.postgres as pg
    from app.config import Settings
    from app.main import create_app

    dsn = imp.read_dsn()
    if not dsn:
        raise SystemExit("Falta IMPORT_DATABASE_URL (variable de entorno o private-data/importador.env).")
    if pa.TEST_REF not in dsn or any(ref in dsn for ref in pa.BLOCKED_REFS):
        raise SystemExit("RECHAZADO: la cadena no corresponde al proyecto de pruebas.")

    if args.solo_figuras:
        selected = "WHERE q.active AND q.review_status = 'ready'"
        pg._LATEST_ACTIVE = pg._LATEST_ACTIVE.replace(
            selected,
            selected + " AND EXISTS (SELECT 1 FROM public.question_assets a WHERE a.question_id = q.id)",
        )

    origins = tuple(o.rstrip("/") for o in args.origin) or ("http://localhost:5173",)
    if any("*" in o for o in origins):
        raise SystemExit("RECHAZADO: CORS exige orígenes explícitos.")
    print("Destino: pruebas_cane (proyecto de PRUEBAS). Comprobando la configuración pública...", flush=True)
    cfg = pa.load_test_config(root=config_root)  # config_root: solo para pruebas
    settings = Settings(
        frontend_origins=origins,
        supabase_url=cfg.url,
        supabase_publishable_key=cfg.key,
        database_url=dsn,
    )
    print(f"Backend de PRUEBAS en http://{host}:{args.port}  (CORS: {', '.join(origins)})", flush=True)
    uvicorn.run(create_app(settings), host=host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
