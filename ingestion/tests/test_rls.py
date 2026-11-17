"""Row Level Security isolation tests for the `reporting` schema.

These are the most important tests in the repo: they prove one client can never see
another client's data, and nobody but the service role can read connection_secrets.
Do not weaken an assertion to make a test pass. Fix the schema instead.

Every table in `reporting` must be classified below (rule 9 in CLAUDE.md). A new table
that isn't classified fails `test_every_table_is_classified`, so it can't slip in
without an isolation test.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
import pytest
from psycopg import errors, sql

# ---------------------------------------------------------------------------
# Table classification
# ---------------------------------------------------------------------------

# Tables with a client_id column are found automatically. Each needs a seed statement
# in CLIENT_SEEDS (connections and client_users are seeded by the fixture itself), and
# is checked generically: a client user sees only their own client's rows.

# Tables with no client_id that hold client-related data. Each has its own explicit tests.
SPECIAL_TABLES = {
    "clients",  # isolated by id
    "staff",  # staff-only
    "connection_secrets",  # service role only
    "sync_runs",  # staff-only, keyed by connection_id
}

# Tables with no client_id and no client data, readable by every authenticated user.
# Add a table here only if it holds no client data at all (e.g. metric labels).
GLOBAL_TABLES: set[str] = set()

# Seed statements for every client-scoped table except connections and client_users.
# Parameters: client, conn_ads, conn_ga4, conn_gsc, conn_gbp, conn_social.
CLIENT_SEEDS: dict[str, str] = {
    "ad_metrics_daily": """
        insert into reporting.ad_metrics_daily
          (connection_id, client_id, platform, date, account_id, campaign_id, campaign_name,
           impressions, clicks, cost, conversions, conversion_value, currency)
        values
          (%(conn_ads)s, %(client)s, 'google_ads', date '2026-10-01', '1234567890', 'c1',
           'Brand', 1000, 50, 123.4567, 5, 500, 'AUD'),
          (%(conn_ads)s, %(client)s, 'google_ads', date '2026-10-02', '1234567890', 'c1',
           'Brand', 800, 40, 99.0, 3, 300, 'AUD')
    """,
    "web_metrics_daily": """
        insert into reporting.web_metrics_daily
          (connection_id, client_id, date, channel_group, sessions, total_users, new_users,
           engaged_sessions, key_events, revenue)
        values (%(conn_ga4)s, %(client)s, date '2026-10-01', 'Organic Search', 100, 80, 40,
                60, 4, 250)
    """,
    "search_metrics_daily": """
        insert into reporting.search_metrics_daily
          (connection_id, client_id, date, clicks, impressions, avg_position)
        values (%(conn_gsc)s, %(client)s, date '2026-10-01', 30, 900, 7.4)
    """,
    "local_metrics_daily": """
        insert into reporting.local_metrics_daily
          (connection_id, client_id, date, location_id, metric, value)
        values (%(conn_gbp)s, %(client)s, date '2026-10-01', 'locations/1', 'CALL_CLICKS', 3)
    """,
    "social_metrics_daily": """
        insert into reporting.social_metrics_daily
          (connection_id, client_id, platform, date, account_id, followers, reach,
           impressions, engagements)
        values (%(conn_social)s, %(client)s, 'facebook_page', date '2026-10-01', 'page1',
                500, 1200, 2000, 75)
    """,
}

CONNECTION_PLATFORMS = {
    "conn_ads": "google_ads",
    "conn_ga4": "ga4",
    "conn_gsc": "search_console",
    "conn_gbp": "gbp",
    "conn_social": "facebook_page",
}


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class World:
    client_a: uuid.UUID
    client_b: uuid.UUID
    staff_user: uuid.UUID
    portal_a: uuid.UUID  # client user linked only to client A
    portal_b: uuid.UUID  # client user linked only to client B
    outsider: uuid.UUID  # logged-in user with no memberships at all
    connections: dict[uuid.UUID, dict[str, uuid.UUID]]  # client -> {key: connection_id}


def _relations(conn: psycopg.Connection, relkinds: tuple[str, ...]) -> list[str]:
    rows = conn.execute(
        """
        select c.relname from pg_class c
        where c.relnamespace = 'reporting'::regnamespace and c.relkind = any(%s)
        order by c.relname
        """,
        (list(relkinds),),
    ).fetchall()
    return [r[0] for r in rows]


def _tables(conn: psycopg.Connection) -> list[str]:
    return _relations(conn, ("r", "p"))


def _views(conn: psycopg.Connection) -> list[str]:
    return _relations(conn, ("v", "m"))


def _has_client_id(conn: psycopg.Connection, relname: str) -> bool:
    return conn.execute(
        """
        select exists (
          select 1 from pg_attribute
          where attrelid = format('reporting.%%I', %s::text)::regclass
            and attname = 'client_id' and not attisdropped
        )
        """,
        (relname,),
    ).fetchone()[0]


def _client_scoped(conn: psycopg.Connection) -> list[str]:
    return [t for t in _tables(conn) if _has_client_id(conn, t)]


def _ident(relname: str) -> sql.Composed:
    return sql.SQL("reporting.{}").format(sql.Identifier(relname))


@contextmanager
def as_role(
    conn: psycopg.Connection, role: str, user_id: uuid.UUID | None = None
) -> Iterator[psycopg.Connection]:
    """Run the block as `role` (with JWT sub = user_id), the way PostgREST does.

    Wrapped in a savepoint that is always rolled back, so the role switch and any writes
    are undone, and an expected error doesn't poison the outer transaction.
    """
    with conn.transaction() as tx:
        conn.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
        claims = json.dumps({"sub": str(user_id), "role": role}) if user_id else ""
        conn.execute("select set_config('request.jwt.claims', %s, true)", (claims,))
        yield conn
        raise psycopg.Rollback(tx)


def _client_ids_visible(conn: psycopg.Connection, relname: str) -> list[uuid.UUID]:
    rows = conn.execute(sql.SQL("select client_id from {}").format(_ident(relname))).fetchall()
    return [r[0] for r in rows]


@pytest.fixture
def world(conn: psycopg.Connection) -> World:
    """Two clients, their users and connections, and rows in every client-scoped table."""
    client_a, client_b = uuid.uuid4(), uuid.uuid4()
    staff_user, portal_a, portal_b, outsider = (uuid.uuid4() for _ in range(4))
    suffix = uuid.uuid4().hex[:8]  # avoid slug clashes with any real local data

    for user_id, label in [
        (staff_user, "staff"),
        (portal_a, "portal-a"),
        (portal_b, "portal-b"),
        (outsider, "outsider"),
    ]:
        conn.execute(
            "insert into auth.users (id, email) values (%s, %s)",
            (user_id, f"{label}-{suffix}@example.test"),
        )
    conn.execute("insert into reporting.staff (user_id) values (%s)", (staff_user,))

    connections: dict[uuid.UUID, dict[str, uuid.UUID]] = {}
    for client_id, name, portal_user in [
        (client_a, "a", portal_a),
        (client_b, "b", portal_b),
    ]:
        conn.execute(
            "insert into reporting.clients (id, name, slug) values (%s, %s, %s)",
            (client_id, f"Test client {name.upper()}", f"test-{name}-{suffix}"),
        )
        conn.execute(
            "insert into reporting.client_users (user_id, client_id) values (%s, %s)",
            (portal_user, client_id),
        )
        conns: dict[str, uuid.UUID] = {}
        for key, platform in CONNECTION_PLATFORMS.items():
            conns[key] = conn.execute(
                """
                insert into reporting.connections
                  (client_id, platform, external_account_id, status)
                values (%s, %s, %s, 'active') returning id
                """,
                (client_id, platform, f"{platform}-{name}"),
            ).fetchone()[0]
        connections[client_id] = conns

        params = {"client": client_id, **conns}
        for statement in CLIENT_SEEDS.values():
            conn.execute(statement, params)

        conn.execute(
            "insert into reporting.connection_secrets (connection_id, ciphertext) values (%s, %s)",
            (conns["conn_ads"], "dGVzdC1jaXBoZXJ0ZXh0LW5vdC1hLXJlYWwtdG9rZW4="),
        )
        conn.execute(
            """
            insert into reporting.sync_runs (connection_id, status, rows_loaded, finished_at)
            values (%s, 'succeeded', 2, now())
            """,
            (conns["conn_ads"],),
        )

    return World(client_a, client_b, staff_user, portal_a, portal_b, outsider, connections)


# ---------------------------------------------------------------------------
# Classification guards (rule 9: every new table needs an isolation test)
# ---------------------------------------------------------------------------


def test_every_table_is_classified(conn: psycopg.Connection) -> None:
    unclassified = []
    for table in _tables(conn):
        if table in SPECIAL_TABLES or table in GLOBAL_TABLES:
            continue
        if not _has_client_id(conn, table):
            unclassified.append(table)
    assert not unclassified, (
        f"Tables with no client_id and no classification: {unclassified}. "
        "Give them a client_id, or add them to SPECIAL_TABLES with explicit tests."
    )


def test_every_client_scoped_table_is_seeded(conn: psycopg.Connection) -> None:
    seeded_by_fixture = {"connections", "client_users"}
    missing = [
        t for t in _client_scoped(conn) if t not in CLIENT_SEEDS and t not in seeded_by_fixture
    ]
    assert not missing, f"Add seed rows to CLIENT_SEEDS for: {missing}"


def test_global_tables_have_no_client_id(conn: psycopg.Connection) -> None:
    offenders = [t for t in GLOBAL_TABLES if _has_client_id(conn, t)]
    assert not offenders, f"Global tables must not hold client data: {offenders}"


def test_fixture_seeds_both_clients_everywhere(conn: psycopg.Connection, world: World) -> None:
    # Guards against a vacuous pass: isolation tests mean nothing if the rows aren't there.
    for table in _client_scoped(conn):
        seen = set(_client_ids_visible(conn, table))
        assert {world.client_a, world.client_b} <= seen, f"{table} is missing seed rows"


# ---------------------------------------------------------------------------
# 1. Portal user A sees only client A
# ---------------------------------------------------------------------------


def test_portal_user_sees_only_own_client_in_every_client_scoped_table(
    conn: psycopg.Connection, world: World
) -> None:
    tables = _client_scoped(conn)
    assert tables
    with as_role(conn, "authenticated", world.portal_a):
        for table in tables:
            ids = _client_ids_visible(conn, table)
            assert ids, f"portal user A sees no rows of their own in {table}"
            assert set(ids) == {world.client_a}, f"portal user A sees other clients in {table}"


def test_portal_user_sees_only_own_client_in_every_view(
    conn: psycopg.Connection, world: World
) -> None:
    views = _views(conn)
    assert "v_ad_metrics_monthly" in views
    with as_role(conn, "authenticated", world.portal_a):
        for view in views:
            assert _has_client_id(conn, view), f"view {view} has no client_id to check"
            ids = _client_ids_visible(conn, view)
            assert ids, f"portal user A sees no rows of their own in {view}"
            assert set(ids) == {world.client_a}, f"portal user A sees other clients in {view}"


def test_portal_user_sees_only_own_client_row(conn: psycopg.Connection, world: World) -> None:
    with as_role(conn, "authenticated", world.portal_a):
        ids = [r[0] for r in conn.execute("select id from reporting.clients").fetchall()]
    assert ids == [world.client_a]


def test_portal_user_sees_no_staff_or_sync_runs(conn: psycopg.Connection, world: World) -> None:
    with as_role(conn, "authenticated", world.portal_a):
        assert conn.execute("select count(*) from reporting.staff").fetchone()[0] == 0
        assert conn.execute("select count(*) from reporting.sync_runs").fetchone()[0] == 0


def test_user_with_no_membership_sees_nothing(conn: psycopg.Connection, world: World) -> None:
    with as_role(conn, "authenticated", world.outsider):
        for table in [*_client_scoped(conn), *_views(conn), "clients", "staff", "sync_runs"]:
            count = conn.execute(
                sql.SQL("select count(*) from {}").format(_ident(table))
            ).fetchone()[0]
            assert count == 0, f"user with no memberships sees {count} rows in {table}"


# ---------------------------------------------------------------------------
# 2. Portal user A can't write
# ---------------------------------------------------------------------------

METRIC_TABLES = list(CLIENT_SEEDS)


@pytest.mark.parametrize("table", METRIC_TABLES)
def test_portal_user_cannot_insert_metrics(
    conn: psycopg.Connection, world: World, table: str
) -> None:
    params = {"client": world.client_a, **world.connections[world.client_a]}
    with pytest.raises(errors.InsufficientPrivilege):
        with as_role(conn, "authenticated", world.portal_a):
            # Re-running the seed would also clash on the primary key, so shift the date.
            conn.execute(CLIENT_SEEDS[table].replace("2026-10-0", "2025-01-0"), params)


@pytest.mark.parametrize("table", METRIC_TABLES)
@pytest.mark.parametrize("statement", ["update {} set loaded_at = now()", "delete from {}"])
def test_portal_user_cannot_update_or_delete_metrics(
    conn: psycopg.Connection, world: World, table: str, statement: str
) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        with as_role(conn, "authenticated", world.portal_a):
            conn.execute(sql.SQL(statement).format(_ident(table)))


def _row_snapshot(conn: psycopg.Connection, table: str, client_id: uuid.UUID) -> list[tuple]:
    column = "id" if table == "clients" else "client_id"
    query = sql.SQL("select to_jsonb(t)::text from {} t where {} = %s order by 1").format(
        _ident(table), sql.Identifier(column)
    )
    return conn.execute(query, (client_id,)).fetchall()


@pytest.mark.parametrize("table", ["clients", "connections", "client_users"])
def test_portal_user_cannot_change_clients_connections_or_memberships(
    conn: psycopg.Connection, world: World, table: str
) -> None:
    """authenticated has write grants here (for staff), so RLS must block client users.

    RLS either raises (insert, or a with-check failure) or silently matches zero rows
    (update/delete). Both are fine; what matters is that nothing changed.
    """
    before = {c: _row_snapshot(conn, table, c) for c in (world.client_a, world.client_b)}
    where = "id" if table == "clients" else "client_id"

    attempts = [
        sql.SQL("update {} set {} = {} where {} = %(a)s").format(
            _ident(table),
            sql.Identifier("name" if table == "clients" else "created_at"),
            sql.SQL("'hacked'" if table == "clients" else "now()"),
            sql.Identifier(where),
        ),
        sql.SQL("delete from {}").format(_ident(table)),
    ]
    for attempt in attempts:
        try:
            with as_role(conn, "authenticated", world.portal_a):
                cur = conn.execute(attempt, {"a": world.client_a})
                assert cur.rowcount == 0, f"portal user A changed {cur.rowcount} rows in {table}"
        except errors.InsufficientPrivilege:
            pass

    inserts = {
        "clients": "insert into reporting.clients (name, slug) values ('X', %(slug)s)",
        "connections": (
            "insert into reporting.connections (client_id, platform, external_account_id) "
            "values (%(a)s, 'google_ads', 'injected')"
        ),
        # The dangerous one: a client user granting themselves access to client B.
        "client_users": (
            "insert into reporting.client_users (user_id, client_id) values (%(me)s, %(b)s)"
        ),
    }
    with pytest.raises(errors.InsufficientPrivilege):
        with as_role(conn, "authenticated", world.portal_a):
            conn.execute(
                inserts[table],
                {
                    "a": world.client_a,
                    "b": world.client_b,
                    "me": world.portal_a,
                    "slug": f"injected-{uuid.uuid4().hex[:8]}",
                },
            )

    after = {c: _row_snapshot(conn, table, c) for c in (world.client_a, world.client_b)}
    assert after == before, f"{table} changed after portal user A's write attempts"


# ---------------------------------------------------------------------------
# 3 and 4. connection_secrets: nobody but the service role; staff see everything else
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("who", ["portal_a", "staff_user"])
def test_authenticated_cannot_read_connection_secrets(
    conn: psycopg.Connection, world: World, who: str
) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        with as_role(conn, "authenticated", getattr(world, who)):
            conn.execute("select * from reporting.connection_secrets")


@pytest.mark.parametrize("who", ["portal_a", "staff_user"])
@pytest.mark.parametrize(
    "statement",
    [
        "insert into reporting.connection_secrets (connection_id, ciphertext) values (%(c)s, 'x')",
        "update reporting.connection_secrets set ciphertext = 'x'",
        "delete from reporting.connection_secrets",
    ],
)
def test_authenticated_cannot_write_connection_secrets(
    conn: psycopg.Connection, world: World, who: str, statement: str
) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        with as_role(conn, "authenticated", getattr(world, who)):
            conn.execute(statement, {"c": world.connections[world.client_a]["conn_ga4"]})


def test_staff_sees_both_clients_everywhere(conn: psycopg.Connection, world: World) -> None:
    both = {world.client_a, world.client_b}
    with as_role(conn, "authenticated", world.staff_user):
        for relation in [*_client_scoped(conn), *_views(conn)]:
            assert both <= set(_client_ids_visible(conn, relation)), f"staff can't see {relation}"
        ids = {r[0] for r in conn.execute("select id from reporting.clients").fetchall()}
        assert both <= ids
        run_connections = {
            r[0] for r in conn.execute("select connection_id from reporting.sync_runs").fetchall()
        }
        assert {
            world.connections[world.client_a]["conn_ads"],
            world.connections[world.client_b]["conn_ads"],
        } <= run_connections


# ---------------------------------------------------------------------------
# 5. anon gets nothing
# ---------------------------------------------------------------------------


def test_anon_cannot_read_anything_in_reporting(conn: psycopg.Connection, world: World) -> None:
    relations = [*_tables(conn), *_views(conn)]
    assert relations
    for relation in relations:
        with pytest.raises(errors.InsufficientPrivilege):
            with as_role(conn, "anon"):
                conn.execute(sql.SQL("select 1 from {} limit 1").format(_ident(relation)))


def test_anon_with_forged_sub_still_gets_nothing(conn: psycopg.Connection, world: World) -> None:
    # anon can't be talked into acting as a client user just by carrying a sub claim.
    with pytest.raises(errors.InsufficientPrivilege):
        with as_role(conn, "anon", world.portal_a):
            conn.execute("select 1 from reporting.ad_metrics_daily limit 1")


# ---------------------------------------------------------------------------
# 6 and 7. Meta-tests on the schema itself
# ---------------------------------------------------------------------------


def test_every_view_uses_security_invoker(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        """
        select c.relname, c.relkind,
               coalesce((select o.option_value from pg_options_to_table(c.reloptions) o
                         where o.option_name = 'security_invoker'), 'false') as invoker
        from pg_class c
        where c.relnamespace = 'reporting'::regnamespace and c.relkind in ('v', 'm')
        """
    ).fetchall()
    assert rows, "expected at least one view in reporting"
    # Materialized views can't be security_invoker and never apply RLS, so none allowed.
    matviews = [name for name, kind, _ in rows if kind == "m"]
    assert not matviews, f"materialized views bypass RLS, not allowed in reporting: {matviews}"
    unsafe = [name for name, _, invoker in rows if invoker.lower() not in ("true", "on", "1")]
    assert not unsafe, f"views without security_invoker=true (they skip RLS): {unsafe}"


def test_every_table_has_rls_enabled(conn: psycopg.Connection) -> None:
    rows = conn.execute(
        """
        select relname, relrowsecurity from pg_class
        where relnamespace = 'reporting'::regnamespace and relkind in ('r', 'p')
        """
    ).fetchall()
    assert rows
    missing = [name for name, enabled in rows if not enabled]
    assert not missing, f"tables without row level security: {missing}"


def test_no_policy_is_unconditionally_true(conn: psycopg.Connection) -> None:
    # CLAUDE.md rule 4: never add `using (true)` policies. Tables on GLOBAL_TABLES are the
    # only sanctioned exception, and only for select.
    rows = conn.execute(
        """
        select tablename, policyname, cmd, qual, with_check from pg_policies
        where schemaname = 'reporting'
        """
    ).fetchall()
    offenders = []
    for table, policy, cmd, qual, with_check in rows:
        for expr in (qual, with_check):
            if expr is not None and expr.strip().lower() in ("true", "(true)"):
                if not (table in GLOBAL_TABLES and cmd == "SELECT"):
                    offenders.append(f"{table}.{policy}")
    assert not offenders, f"unconditional policies: {offenders}"
