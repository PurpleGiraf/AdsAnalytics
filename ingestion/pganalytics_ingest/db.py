"""Database access for ingestion.

Connects with DATABASE_URL, which for ingestion is a privileged role (postgres / service
role) that bypasses RLS. Never use this module from code that serves a logged-in user.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from pganalytics_ingest.errors import redact
from pganalytics_ingest.settings import Settings, require

# Tables ingestion may write metric rows to. Table names are never taken from input.
METRIC_TABLES = frozenset(
    {
        "ad_metrics_daily",
        "web_metrics_daily",
        "search_metrics_daily",
        "local_metrics_daily",
        "social_metrics_daily",
    }
)


@dataclass(frozen=True)
class Connection:
    id: uuid.UUID
    client_id: uuid.UUID
    client_slug: str
    client_timezone: str
    platform: str
    external_account_id: str
    credential_source: str
    status: str


def connect(settings: Settings) -> psycopg.Connection:
    url = require(settings.database_url, "DATABASE_URL")
    return psycopg.connect(url.get_secret_value(), autocommit=True)  # type: ignore[union-attr]


def list_active_connections(
    conn: psycopg.Connection, platform: str, client_slug: str | None = None
) -> list[Connection]:
    """Connections to sync: every status except 'disabled', for active clients.

    'error' and 'expired' connections are retried on purpose: once someone fixes the
    credential, the next nightly run recovers on its own.
    """
    query = """
        select c.id, c.client_id, cl.slug as client_slug, cl.timezone as client_timezone,
               c.platform::text as platform, c.external_account_id, c.credential_source,
               c.status::text as status
        from reporting.connections c
        join reporting.clients cl on cl.id = c.client_id
        where c.platform = %(platform)s
          and c.status <> 'disabled'
          and cl.is_active
          and (%(slug)s::text is null or cl.slug = %(slug)s::text)
        order by cl.slug, c.external_account_id
    """
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(query, {"platform": platform, "slug": client_slug}).fetchall()
    return [Connection(**row) for row in rows]


def start_sync_run(
    conn: psycopg.Connection, connection_id: uuid.UUID, date_from: dt.date, date_to: dt.date
) -> int:
    row = conn.execute(
        """
        insert into reporting.sync_runs (connection_id, date_from, date_to, status)
        values (%s, %s, %s, 'running') returning id
        """,
        (connection_id, date_from, date_to),
    ).fetchone()
    assert row is not None
    return int(row[0])


def finish_sync_run(
    conn: psycopg.Connection,
    run_id: int,
    status: str,
    rows: int | None = None,
    error: object | None = None,
) -> None:
    if status not in ("succeeded", "failed"):
        raise ValueError(f"unexpected sync status {status!r}")
    conn.execute(
        """
        update reporting.sync_runs
        set status = %s, rows_loaded = %s, error = %s, finished_at = now()
        where id = %s
        """,
        (status, rows, None if error is None else redact(error), run_id),
    )


def mark_connection_status(
    conn: psycopg.Connection, connection_id: uuid.UUID, status: str, error: object | None = None
) -> None:
    """'active' also stamps last_success_at and clears last_error. Errors are redacted."""
    if status == "active":
        conn.execute(
            """
            update reporting.connections
            set status = 'active', last_success_at = now(), last_error = null
            where id = %s
            """,
            (connection_id,),
        )
    elif status in ("error", "expired", "pending", "disabled"):
        conn.execute(
            "update reporting.connections set status = %s, last_error = %s where id = %s",
            (status, None if error is None else redact(error), connection_id),
        )
    else:
        raise ValueError(f"unexpected connection status {status!r}")


def upsert_rows(
    conn: psycopg.Connection,
    table: str,
    rows: Sequence[Mapping[str, Any]],
    conflict_cols: Sequence[str],
) -> int:
    """Insert rows, updating existing ones (ON CONFLICT ... DO UPDATE) and loaded_at."""
    if table not in METRIC_TABLES:
        raise ValueError(f"{table!r} is not a metrics table")
    if not rows:
        return 0
    columns = list(rows[0].keys())
    for row in rows:
        if list(row.keys()) != columns:
            raise ValueError("all rows must have the same columns in the same order")
    missing = [c for c in conflict_cols if c not in columns]
    if missing:
        raise ValueError(f"conflict columns not in rows: {missing}")

    update_cols = [c for c in columns if c not in conflict_cols and c != "loaded_at"]
    statement = sql.SQL(
        "insert into reporting.{table} ({cols}) values ({vals}) "
        "on conflict ({conflict}) do update set {updates}"
    ).format(
        table=sql.Identifier(table),
        cols=sql.SQL(", ").join(map(sql.Identifier, columns)),
        vals=sql.SQL(", ").join(sql.Placeholder(c) for c in columns),
        conflict=sql.SQL(", ").join(map(sql.Identifier, conflict_cols)),
        updates=sql.SQL(", ").join(
            [
                *(sql.SQL("{c} = excluded.{c}").format(c=sql.Identifier(c)) for c in update_cols),
                sql.SQL("loaded_at = now()"),
            ]
        ),
    )
    with conn.cursor() as cur:
        cur.executemany(statement, rows)
    return len(rows)


def replace_window(
    conn: psycopg.Connection,
    table: str,
    connection_id: uuid.UUID,
    date_from: dt.date,
    date_to: dt.date,
    rows: Sequence[Mapping[str, Any]],
    conflict_cols: Sequence[str],
) -> int:
    """Upsert a full re-pull of [date_from, date_to] for one connection, atomically.

    Rows in that window that the new pull no longer contains are deleted. Without this,
    a campaign whose numbers were revised down to nothing (or a removed campaign) would
    keep its old row forever and overstate totals. Upserted rows get loaded_at = now(),
    which is constant within the transaction, so anything older in the window is stale.
    """
    if table not in METRIC_TABLES:
        raise ValueError(f"{table!r} is not a metrics table")
    for row in rows:
        if row.get("connection_id") != connection_id:
            raise ValueError("every row must belong to the connection being replaced")
        if not (date_from <= row["date"] <= date_to):
            raise ValueError(f"row date {row['date']} is outside the sync window")
    with conn.transaction():
        loaded = upsert_rows(conn, table, rows, conflict_cols)
        conn.execute(
            sql.SQL(
                "delete from reporting.{} where connection_id = %s "
                "and date between %s and %s and loaded_at < now()"
            ).format(sql.Identifier(table)),
            (connection_id, date_from, date_to),
        )
    return loaded
