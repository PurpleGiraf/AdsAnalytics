"""db.py against a real database (same DATABASE_URL modes as test_rls.py)."""

import datetime as dt
import uuid
from decimal import Decimal

import psycopg
import pytest

from pganalytics_ingest import db

D1, D2, D3 = dt.date(2026, 10, 1), dt.date(2026, 10, 2), dt.date(2026, 10, 3)
CONFLICT = ("connection_id", "date", "campaign_id")


def make_connection(
    conn: psycopg.Connection, platform: str = "google_ads", status: str = "active", active=True
) -> db.Connection:
    suffix = uuid.uuid4().hex[:8]
    client_id = conn.execute(
        "insert into reporting.clients (name, slug, is_active) values (%s, %s, %s) returning id",
        (f"DB test {suffix}", f"db-test-{suffix}", active),
    ).fetchone()[0]
    connection_id = conn.execute(
        """
        insert into reporting.connections (client_id, platform, external_account_id, status)
        values (%s, %s, '1234567890', %s) returning id
        """,
        (client_id, platform, status),
    ).fetchone()[0]
    return db.Connection(
        id=connection_id,
        client_id=client_id,
        client_slug=f"db-test-{suffix}",
        client_timezone="Australia/Adelaide",
        platform=platform,
        external_account_id="1234567890",
        credential_source="agency",
        status=status,
    )


def ad_row(c: db.Connection, date: dt.date, campaign: str, cost: str, clicks: int = 1) -> dict:
    return {
        "connection_id": c.id,
        "client_id": c.client_id,
        "platform": "google_ads",
        "date": date,
        "account_id": "1234567890",
        "campaign_id": campaign,
        "campaign_name": f"Campaign {campaign}",
        "impressions": 10,
        "clicks": clicks,
        "cost": Decimal(cost),
        "conversions": Decimal("0"),
        "conversion_value": Decimal("0"),
        "currency": "AUD",
    }


def stored(conn: psycopg.Connection, c: db.Connection) -> dict:
    rows = conn.execute(
        "select date, campaign_id, cost, clicks from reporting.ad_metrics_daily "
        "where connection_id = %s order by 1, 2",
        (c.id,),
    ).fetchall()
    return {(r[0], r[1]): (r[2], r[3]) for r in rows}


def test_upsert_inserts_then_updates_and_bumps_loaded_at(conn: psycopg.Connection) -> None:
    c = make_connection(conn)
    assert db.upsert_rows(conn, "ad_metrics_daily", [ad_row(c, D1, "a", "1.5")], CONFLICT) == 1
    conn.execute(
        "update reporting.ad_metrics_daily set loaded_at = now() - interval '1 day' "
        "where connection_id = %s",
        (c.id,),
    )
    db.upsert_rows(conn, "ad_metrics_daily", [ad_row(c, D1, "a", "2.25", clicks=7)], CONFLICT)
    assert stored(conn, c) == {(D1, "a"): (Decimal("2.2500"), 7)}
    fresh = conn.execute(
        "select loaded_at > now() - interval '1 minute' from reporting.ad_metrics_daily "
        "where connection_id = %s",
        (c.id,),
    ).fetchone()[0]
    assert fresh


def test_upsert_rejects_unknown_tables(conn: psycopg.Connection) -> None:
    with pytest.raises(ValueError):
        db.upsert_rows(conn, "connection_secrets", [{"x": 1}], ["x"])


def test_replace_window_deletes_stale_rows_only_inside_window(conn: psycopg.Connection) -> None:
    c = make_connection(conn)
    other = make_connection(conn)
    old = [ad_row(c, D1, "a", "1"), ad_row(c, D2, "gone", "5"), ad_row(c, D3, "outside", "9")]
    db.upsert_rows(conn, "ad_metrics_daily", old, CONFLICT)
    db.upsert_rows(conn, "ad_metrics_daily", [ad_row(other, D2, "keep", "3")], CONFLICT)
    conn.execute(
        "update reporting.ad_metrics_daily set loaded_at = now() - interval '1 day' "
        "where connection_id = any(%s)",
        ([c.id, other.id],),
    )

    loaded = db.replace_window(
        conn, "ad_metrics_daily", c.id, D1, D2, [ad_row(c, D1, "a", "1.75")], CONFLICT
    )

    assert loaded == 1
    # 'gone' was in the window but not re-pulled -> deleted; 'outside' is out of window.
    assert stored(conn, c) == {
        (D1, "a"): (Decimal("1.7500"), 1),
        (D3, "outside"): (Decimal("9.0000"), 1),
    }
    assert stored(conn, other) == {(D2, "keep"): (Decimal("3.0000"), 1)}


def test_replace_window_refuses_rows_from_other_connections(conn: psycopg.Connection) -> None:
    c, other = make_connection(conn), make_connection(conn)
    with pytest.raises(ValueError):
        db.replace_window(
            conn, "ad_metrics_daily", c.id, D1, D2, [ad_row(other, D1, "a", "1")], CONFLICT
        )
    with pytest.raises(ValueError):
        db.replace_window(
            conn, "ad_metrics_daily", c.id, D1, D2, [ad_row(c, D3, "a", "1")], CONFLICT
        )


def test_sync_run_lifecycle_redacts_errors(conn: psycopg.Connection) -> None:
    c = make_connection(conn)
    run_id = db.start_sync_run(conn, c.id, D1, D2)
    db.finish_sync_run(conn, run_id, "failed", error="boom access_token=EAAsecretvalue123")
    status, error, finished = conn.execute(
        "select status::text, error, finished_at is not null "
        "from reporting.sync_runs where id = %s",
        (run_id,),
    ).fetchone()
    assert status == "failed" and finished
    assert "EAAsecretvalue123" not in error


def test_mark_connection_status(conn: psycopg.Connection) -> None:
    c = make_connection(conn, status="pending")
    db.mark_connection_status(conn, c.id, "error", error="Bearer abcdef123456")
    status, last_error, last_success = conn.execute(
        "select status::text, last_error, last_success_at from reporting.connections where id = %s",
        (c.id,),
    ).fetchone()
    assert status == "error" and "abcdef123456" not in last_error and last_success is None

    db.mark_connection_status(conn, c.id, "active")
    status, last_error, last_success = conn.execute(
        "select status::text, last_error, last_success_at from reporting.connections where id = %s",
        (c.id,),
    ).fetchone()
    assert status == "active" and last_error is None and last_success is not None


def test_list_active_connections_filters(conn: psycopg.Connection) -> None:
    keep = make_connection(conn)
    expired = make_connection(conn, status="expired")
    disabled = make_connection(conn, status="disabled")
    inactive_client = make_connection(conn, active=False)
    other_platform = make_connection(conn, platform="ga4")

    ids = {x.id for x in db.list_active_connections(conn, "google_ads")}
    assert {keep.id, expired.id} <= ids
    assert not ids & {disabled.id, inactive_client.id, other_platform.id}

    only = db.list_active_connections(conn, "google_ads", keep.client_slug)
    assert [x.id for x in only] == [keep.id]
