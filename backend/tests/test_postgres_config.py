"""Configuración del pool: sin conectar a nada."""

from app.postgres import make_pool


def test_pool_defaults_to_ssl_and_is_not_opened():
    pool = make_pool("postgresql://usuario:clave@db.ejemplo.test:5432/postgres")

    assert "sslmode=require" in pool.conninfo
    assert pool.closed  # no abre conexiones al crearse


def test_pool_respects_an_explicit_sslmode():
    pool = make_pool("postgresql://usuario:clave@db.ejemplo.test/postgres?sslmode=verify-full")

    assert "sslmode=verify-full" in pool.conninfo
    assert "sslmode=require" not in pool.conninfo


def test_pool_disables_prepared_statements_for_the_transaction_pooler():
    pool = make_pool("postgresql://usuario:clave@db.ejemplo.test/postgres")

    assert pool.kwargs["prepare_threshold"] is None
