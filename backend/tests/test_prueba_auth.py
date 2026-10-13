"""scripts/prueba_auth.py: solo las partes sin red ni contraseña."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prueba_auth.py"


@pytest.fixture(scope="module")
def pa():
    spec = importlib.util.spec_from_file_location("prueba_auth", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["prueba_auth"] = module
    spec.loader.exec_module(module)
    return module


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


def test_token_file_is_ignored_by_git(pa):
    import subprocess

    rel = pa.TOKEN_FILE.relative_to(pa.ROOT)
    result = subprocess.run(["git", "check-ignore", "-q", str(rel)], cwd=pa.ROOT)
    assert result.returncode == 0, "private-data/ debe estar ignorada por Git"


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
