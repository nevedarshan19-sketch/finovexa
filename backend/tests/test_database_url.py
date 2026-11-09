from __future__ import annotations

from app.database import normalize_database_url


def test_normalize_database_url_maps_hosted_postgres_to_psycopg3():
    assert (
        normalize_database_url("postgres://user:pass@host:5432/finovexa")
        == "postgresql+psycopg://user:pass@host:5432/finovexa"
    )
    assert (
        normalize_database_url("postgresql://user:pass@host/finovexa?sslmode=require")
        == "postgresql+psycopg://user:pass@host/finovexa?sslmode=require"
    )


def test_normalize_database_url_leaves_other_urls_unchanged():
    assert normalize_database_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("sqlite:///./finovexa.db") == "sqlite:///./finovexa.db"
