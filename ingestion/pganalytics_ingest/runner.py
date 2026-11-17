"""Runs a sync for every matching connection. One failure never stops the others."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import psycopg

from pganalytics_ingest import db
from pganalytics_ingest.errors import SourceAuthError, redact
from pganalytics_ingest.sources.base import Source

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    connection_id: str
    client_slug: str
    platform: str
    external_account_id: str
    status: str  # 'succeeded' | 'failed'
    rows: int
    error: str | None = None


def default_window(
    timezone: str, days: int, today: dt.date | None = None
) -> tuple[dt.date, dt.date]:
    """The last `days` days up to and including today, in the client's local time.

    Re-pulled every run because platforms revise conversions after the fact.
    """
    if days < 1:
        raise ValueError("days must be at least 1")
    today = today or dt.datetime.now(ZoneInfo(timezone)).date()
    return today - dt.timedelta(days=days - 1), today


def sync_connection(
    conn: psycopg.Connection,
    source: Source,
    connection: db.Connection,
    date_from: dt.date,
    date_to: dt.date,
) -> SyncResult:
    run_id = db.start_sync_run(conn, connection.id, date_from, date_to)
    try:
        raw = source.fetch(connection, date_from, date_to)
        rows = source.normalise(raw, connection)
        loaded = db.replace_window(
            conn,
            source.target_table,
            connection.id,
            date_from,
            date_to,
            rows,
            source.conflict_cols,
        )
    except Exception as exc:  # noqa: BLE001 - every failure is recorded, never raised
        status = "expired" if isinstance(exc, SourceAuthError) else "error"
        message = redact(f"{type(exc).__name__}: {exc}")
        db.finish_sync_run(conn, run_id, "failed", error=message)
        db.mark_connection_status(conn, connection.id, status, error=message)
        log.warning(
            "sync failed: %s %s %s (%s)",
            connection.client_slug,
            connection.platform,
            connection.external_account_id,
            status,
        )
        return SyncResult(
            str(connection.id),
            connection.client_slug,
            connection.platform,
            connection.external_account_id,
            "failed",
            0,
            message,
        )

    db.finish_sync_run(conn, run_id, "succeeded", rows=loaded)
    db.mark_connection_status(conn, connection.id, "active")
    return SyncResult(
        str(connection.id),
        connection.client_slug,
        connection.platform,
        connection.external_account_id,
        "succeeded",
        loaded,
    )


def run_sync(
    conn: psycopg.Connection,
    sources: Mapping[str, Source],
    platform: str,
    client_slug: str | None = None,
    days: int = 30,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> list[SyncResult]:
    if platform not in sources:
        raise ValueError(f"unknown platform {platform!r}; known: {sorted(sources)}")
    if (date_from is None) != (date_to is None):
        raise ValueError("pass both --from and --to, or neither")
    if date_from and date_to and date_from > date_to:
        raise ValueError("--from is after --to")

    source = sources[platform]
    results = []
    for connection in db.list_active_connections(conn, platform, client_slug):
        if date_from and date_to:
            window = (date_from, date_to)
        else:
            window = default_window(connection.client_timezone, days)
        results.append(sync_connection(conn, source, connection, *window))
    return results
