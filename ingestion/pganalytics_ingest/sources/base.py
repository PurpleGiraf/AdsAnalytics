"""The contract every platform source follows."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from pganalytics_ingest.db import Connection


class Source(Protocol):
    platform: str
    target_table: str
    conflict_cols: tuple[str, ...]

    def fetch(
        self, connection: Connection, date_from: dt.date, date_to: dt.date
    ) -> Iterable[Mapping[str, Any]]:
        """Pull raw records from the platform for one connection and date window.

        Raise errors.SourceAuthError when credentials are rejected, so the connection is
        marked 'expired' rather than 'error'.
        """
        ...

    def normalise(
        self, raw_records: Iterable[Mapping[str, Any]], connection: Connection
    ) -> list[dict[str, Any]]:
        """Pure function: raw records -> rows for target_table. No I/O. Fixture-tested."""
        ...
