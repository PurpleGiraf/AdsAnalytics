"""One module per platform. Each exposes a pure normalise() with fixture tests."""

from __future__ import annotations

from pganalytics_ingest.sources.base import Source
from pganalytics_ingest.sources.google_ads import GoogleAdsSource


def registry() -> dict[str, Source]:
    """Platform name -> source. Add new platforms here."""
    return {"google_ads": GoogleAdsSource()}
