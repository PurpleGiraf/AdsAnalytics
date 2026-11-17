"""CLI: python -m pganalytics_ingest sync --platform google_ads [--client SLUG] ..."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

from pganalytics_ingest import db, runner
from pganalytics_ingest.settings import get_settings
from pganalytics_ingest.sources import registry


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def build_parser(platforms: list[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pganalytics_ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="pull platform data into the reporting schema")
    sync.add_argument("--platform", required=True, choices=platforms)
    sync.add_argument("--client", help="only this client slug")
    sync.add_argument("--days", type=int, default=None, help="lookback window (default 30)")
    sync.add_argument("--from", dest="date_from", type=_date, help="YYYY-MM-DD")
    sync.add_argument("--to", dest="date_to", type=_date, help="YYYY-MM-DD")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sources = registry()
    args = build_parser(sorted(sources)).parse_args(argv)
    settings = get_settings()

    if args.days is not None and args.date_from:
        print("Use --days or --from/--to, not both.", file=sys.stderr)
        return 2
    days = args.days or settings.pga_default_lookback_days

    with db.connect(settings) as conn:
        try:
            results = runner.run_sync(
                conn,
                sources,
                args.platform,
                client_slug=args.client,
                days=days,
                date_from=args.date_from,
                date_to=args.date_to,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    if not results:
        print(
            f"No connections to sync for {args.platform}"
            + (f" / {args.client}" if args.client else "")
        )
        return 0
    for r in results:
        line = (
            f"{r.status:9} {r.client_slug:24} {r.platform:14} "
            f"{r.external_account_id:14} rows={r.rows}"
        )
        print(line + (f"  error: {r.error}" if r.error else ""))
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
