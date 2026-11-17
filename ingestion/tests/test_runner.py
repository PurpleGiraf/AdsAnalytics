"""Runner behaviour with fake sources against a real database."""

import datetime as dt
from decimal import Decimal

import psycopg

from pganalytics_ingest import runner
from pganalytics_ingest.errors import SourceAuthError
from tests.test_db import ad_row, make_connection

D1, D2 = dt.date(2026, 10, 1), dt.date(2026, 10, 2)
LEAKY_TOKEN = "ya29.a0AfH6SMBthisisnotarealtoken"


class FakeSource:
    platform = "google_ads"
    target_table = "ad_metrics_daily"
    conflict_cols = ("connection_id", "date", "campaign_id")

    def __init__(self, failures: dict) -> None:
        self.failures = failures  # connection_id -> exception to raise

    def fetch(self, connection, date_from, date_to):
        if connection.id in self.failures:
            raise self.failures[connection.id]
        return [ad_row(connection, date_from, "c1", "4.5")]

    def normalise(self, raw_records, connection):
        return list(raw_records)


def state(conn, connection_id):
    return conn.execute(
        """
        select c.status::text, c.last_error, r.status::text, r.error, r.rows_loaded
        from reporting.connections c
        join reporting.sync_runs r on r.connection_id = c.id
        where c.id = %s
        """,
        (connection_id,),
    ).fetchone()


def test_one_failure_does_not_stop_others_and_errors_are_classified(
    conn: psycopg.Connection,
) -> None:
    ok, broken, expired = make_connection(conn), make_connection(conn), make_connection(conn)
    source = FakeSource(
        {
            broken.id: RuntimeError(
                f"connector crashed, header Authorization: Bearer {LEAKY_TOKEN}"
            ),
            expired.id: SourceAuthError(f"invalid_grant {LEAKY_TOKEN}"),
        }
    )
    ours = {ok.id, broken.id, expired.id}

    results = [
        r
        for r in runner.run_sync(
            conn, {"google_ads": source}, "google_ads", date_from=D1, date_to=D2
        )
        if r.connection_id in {str(i) for i in ours}
    ]

    by_id = {r.connection_id: r for r in results}
    assert by_id[str(ok.id)].status == "succeeded" and by_id[str(ok.id)].rows == 1
    assert by_id[str(broken.id)].status == "failed"
    assert by_id[str(expired.id)].status == "failed"

    assert state(conn, ok.id) == ("active", None, "succeeded", None, 1)

    conn_status, last_error, run_status, run_error, _ = state(conn, broken.id)
    assert (conn_status, run_status) == ("error", "failed")
    assert "RuntimeError" in run_error
    for text in (last_error, run_error, by_id[str(broken.id)].error):
        assert LEAKY_TOKEN not in text

    conn_status, last_error, run_status, run_error, _ = state(conn, expired.id)
    assert (conn_status, run_status) == ("expired", "failed")
    assert LEAKY_TOKEN not in last_error and LEAKY_TOKEN not in run_error

    cost = conn.execute(
        "select cost from reporting.ad_metrics_daily where connection_id = %s", (ok.id,)
    ).fetchone()[0]
    assert cost == Decimal("4.5000")


def test_client_filter(conn: psycopg.Connection) -> None:
    a, b = make_connection(conn), make_connection(conn)
    results = runner.run_sync(
        conn, {"google_ads": FakeSource({})}, "google_ads", client_slug=a.client_slug
    )
    assert [r.connection_id for r in results] == [str(a.id)]
    assert (
        conn.execute(
            "select count(*) from reporting.sync_runs where connection_id = %s", (b.id,)
        ).fetchone()[0]
        == 0
    )


def test_default_window_is_inclusive_and_local() -> None:
    assert runner.default_window("Australia/Adelaide", 30, today=dt.date(2026, 11, 17)) == (
        dt.date(2026, 10, 19),
        dt.date(2026, 11, 17),
    )
