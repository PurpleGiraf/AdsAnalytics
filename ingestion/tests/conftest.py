"""Shared database fixtures for the RLS isolation tests.

Two modes:

* Local Supabase (default): DATABASE_URL points at `supabase start`'s Postgres, and
  migrations were applied by `supabase db reset`.
* Plain Postgres (PGA_TEST_PLAIN_POSTGRES=1, used in CI): the test session drops and
  rebuilds the `reporting` schema from supabase/tests/supabase_stub.sql plus every
  migration. This is destructive, so it refuses to run against anything that looks
  like a real Supabase database.

Every test runs inside a transaction that is always rolled back, so tests never leave
data behind, even on local Supabase.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
STUB_SQL = REPO_ROOT / "supabase" / "tests" / "supabase_stub.sql"


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    msg = (
        "DATABASE_URL is not set, so the RLS isolation tests can't run. "
        "Run `supabase start` and export DATABASE_URL (see README)."
    )
    if os.environ.get("CI"):
        pytest.fail(msg)  # never let CI go green without the isolation tests
    pytest.skip(msg)


def _plain_postgres() -> bool:
    return os.environ.get("PGA_TEST_PLAIN_POSTGRES") == "1"


def _build_plain_postgres(conn: psycopg.Connection) -> None:
    looks_like_supabase = conn.execute(
        "select exists (select 1 from pg_namespace "
        "where nspname in ('storage', 'supabase_migrations', 'graphql'))"
    ).fetchone()[0]
    if looks_like_supabase:
        pytest.fail(
            "PGA_TEST_PLAIN_POSTGRES=1 but this database looks like Supabase. "
            "Refusing to drop the reporting schema. Unset the flag or use a throwaway database."
        )
    conn.execute("drop schema if exists reporting cascade")
    conn.execute(STUB_SQL.read_text())
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        conn.execute(migration.read_text())


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _database_url()
    with psycopg.connect(url, autocommit=True) as conn:
        if _plain_postgres():
            _build_plain_postgres(conn)
        has_schema = conn.execute(
            "select exists (select 1 from pg_namespace where nspname = 'reporting')"
        ).fetchone()[0]
        if not has_schema:
            pytest.fail("The reporting schema doesn't exist. Run `supabase db reset` first.")
    return url


@pytest.fixture
def conn(database_url: str) -> Iterator[psycopg.Connection]:
    """A connection as the postgres (admin) user, inside an always-rolled-back transaction."""
    with psycopg.connect(database_url) as connection:
        with connection.transaction(force_rollback=True):
            yield connection
