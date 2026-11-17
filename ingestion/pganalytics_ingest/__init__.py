"""PG Analytics ingestion package."""

import os

# PyAirbyte sends anonymous usage telemetry to Airbyte (US) unless this is set.
# Our rule is that nothing about client syncs leaves Australia without a reason,
# so switch it off before airbyte is ever imported.
os.environ.setdefault("DO_NOT_TRACK", "1")

__version__ = "0.1.0"
