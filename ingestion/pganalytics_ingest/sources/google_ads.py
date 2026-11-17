"""Google Ads: campaign x day performance via Airbyte's source-google-ads (PyAirbyte).

Credentials are agency-level (our MCC's OAuth client and refresh token, from env).
connections.external_account_id is the client's 10-digit customer ID.

Notes from the connector (checked against v6.1.12's spec and code, 17 Nov 2026):
- There is no login_customer_id setting any more. The connector finds the manager
  account itself from the accounts our OAuth user can reach, and sends the right
  login-customer-id header per client account. GOOGLE_ADS_LOGIN_CUSTOMER_ID is kept in
  .env for reference and for direct API calls, but the connector doesn't take it.
- A custom query with segments.date in both SELECT and WHERE is sent to Google exactly
  as written (no incremental slicing), so the date window below is exactly what we get.
- Metrics can't be pulled from a manager account directly: the customer ID must be a
  client (non-manager) account.
- Reports only go back 37 months.
- Google sunset developer tokens on 9 Sep 2026, but the connector still requires a
  non-empty value, so a placeholder is fine.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import tempfile
from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from pganalytics_ingest.db import Connection
from pganalytics_ingest.errors import SourceAuthError, SourceConfigError
from pganalytics_ingest.settings import Settings, get_settings, require

CONNECTOR = "source-google-ads"
# Pinned on purpose: connector updates can rename fields or change behaviour. Bump it
# deliberately, re-run the fixture tests and check numbers against the Google Ads UI.
CONNECTOR_VERSION = "6.1.12"
STREAM = "pga_campaign_daily"
PLATFORM = "google_ads"
FOUR_DP = Decimal("0.0001")

QUERY_TEMPLATE = (
    "SELECT customer.id, customer.currency_code, campaign.id, campaign.name, segments.date, "
    "metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, "
    "metrics.conversions_value "
    "FROM campaign WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'"
)

# Messages that mean the agency credential itself was rejected (-> connection 'expired').
_AUTH_MARKERS = (
    "invalid_grant",
    "unauthenticated",
    "token has been expired or revoked",
    "oauth_token_invalid",
    "developer_token_not_approved",
    "invalid_client",
    "authentication to google ads has expired",
)


def connector_error_reasons(exc: BaseException) -> list[str]:
    """The connector's own error messages, which PyAirbyte keeps in its log, not the exception.

    PyAirbyte raises a generic "Connector failed"; the useful reason (e.g. "The
    authentication to Google Ads has expired") is in the connector's TRACE error
    messages. Returns them de-duplicated, in order. Callers must still redact.
    """
    texts: list[str] = []
    log_text = getattr(exc, "log_text", None)
    if isinstance(log_text, str):
        texts.append(log_text)
    elif isinstance(log_text, list):
        texts.extend(str(t) for t in log_text)
    log_file = getattr(exc, "log_file", None)
    if log_file:
        try:
            texts.append(Path(log_file).read_text(errors="replace"))
        except OSError:
            pass

    reasons: list[str] = []
    for line in "\n".join(texts).splitlines():
        start = line.find('{"type":')
        if start == -1:
            continue
        try:
            message = json.loads(line[start:])
        except ValueError:
            continue
        trace = message.get("trace") or {}
        if message.get("type") == "TRACE" and trace.get("type") == "ERROR":
            reason = (trace.get("error") or {}).get("message")
            if reason and reason not in reasons:
                reasons.append(reason)
    return reasons


def customer_id_digits(external_account_id: str) -> str:
    digits = re.sub(r"\D", "", external_account_id)
    if len(digits) != 10:
        raise SourceConfigError(
            f"Google Ads customer ID must be 10 digits (dashes are fine), got {len(digits)} digits"
        )
    return digits


def build_query(date_from: dt.date, date_to: dt.date) -> str:
    if date_from > date_to:
        raise ValueError("date_from is after date_to")
    return QUERY_TEMPLATE.format(date_from=date_from.isoformat(), date_to=date_to.isoformat())


def build_config(
    settings: Settings, customer_id: str, date_from: dt.date, date_to: dt.date
) -> dict[str, Any]:
    """Connector config matching the v6.1.12 spec. Contains secrets: never log it."""

    def secret(value: Any, name: str) -> str:
        return require(value, name).get_secret_value()  # type: ignore[union-attr]

    return {
        "credentials": {
            "developer_token": secret(
                settings.google_ads_developer_token, "GOOGLE_ADS_DEVELOPER_TOKEN"
            ),
            "client_id": require(settings.google_ads_client_id, "GOOGLE_ADS_CLIENT_ID"),
            "client_secret": secret(settings.google_ads_client_secret, "GOOGLE_ADS_CLIENT_SECRET"),
            "refresh_token": secret(settings.google_ads_refresh_token, "GOOGLE_ADS_REFRESH_TOKEN"),
        },
        "customer_id": customer_id,
        "start_date": date_from.isoformat(),
        "end_date": date_to.isoformat(),
        "custom_queries_array": [
            {"query": build_query(date_from, date_to), "table_name": STREAM},
        ],
    }


def _field(record: Mapping[str, Any], dotted: str) -> Any:
    """Read a field whether the connector/cache named it 'campaign.id' or 'campaign_id'."""
    for key in (dotted, dotted.replace(".", "_")):
        if key in record:
            return record[key]
    raise KeyError(f"record is missing {dotted!r} (keys: {sorted(record)})")


def _decimal(value: Any) -> Decimal:
    return Decimal("0") if value in (None, "") else Decimal(str(value))


def _int(value: Any) -> int:
    return 0 if value in (None, "") else int(value)


def _date(value: Any) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


class GoogleAdsSource:
    platform = PLATFORM
    target_table = "ad_metrics_daily"
    conflict_cols = ("connection_id", "date", "campaign_id")

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    def fetch(
        self, connection: Connection, date_from: dt.date, date_to: dt.date
    ) -> list[dict[str, Any]]:
        import airbyte as ab  # imported lazily: heavy, and unit tests don't need it

        customer_id = customer_id_digits(connection.external_account_id)
        config = build_config(self.settings, customer_id, date_from, date_to)
        with tempfile.TemporaryDirectory(prefix="pga-gads-") as tmp:
            cache = ab.DuckDBCache(db_path=Path(tmp) / "cache.duckdb", cache_dir=Path(tmp))
            try:
                source = ab.get_source(
                    CONNECTOR,
                    config=config,
                    version=CONNECTOR_VERSION,
                    install_if_missing=True,
                    install_root=self.settings.pga_airbyte_install_dir,
                )
                source.select_streams([STREAM])
                result = source.read(cache=cache, force_full_refresh=True)
                # Materialise before the temp dir (and the DuckDB file) is deleted.
                return [dict(record) for record in result[STREAM]]
            except Exception as exc:
                reasons = connector_error_reasons(exc)
                detail = "; ".join(reasons) or str(exc)
                if any(marker in detail.lower() for marker in _AUTH_MARKERS):
                    raise SourceAuthError(f"Google Ads rejected our credentials: {detail}") from exc
                if reasons:
                    raise RuntimeError(f"Google Ads connector failed: {detail}") from exc
                raise

    def normalise(
        self, raw_records: Iterable[Mapping[str, Any]], connection: Connection
    ) -> list[dict[str, Any]]:
        expected_customer = customer_id_digits(connection.external_account_id)
        rows: list[dict[str, Any]] = []
        seen: set[tuple[dt.date, str]] = set()
        for record in raw_records:
            customer = str(_field(record, "customer.id"))
            if customer != expected_customer:
                # Never let one account's rows land on another connection.
                raise SourceConfigError(
                    f"record for customer {customer} in a sync for {expected_customer}"
                )
            impressions = _int(_field(record, "metrics.impressions"))
            clicks = _int(_field(record, "metrics.clicks"))
            cost = (_decimal(_field(record, "metrics.cost_micros")) / 1_000_000).quantize(
                FOUR_DP, ROUND_HALF_UP
            )
            conversions = _decimal(_field(record, "metrics.conversions")).quantize(
                FOUR_DP, ROUND_HALF_UP
            )
            conversion_value = _decimal(_field(record, "metrics.conversions_value")).quantize(
                FOUR_DP, ROUND_HALF_UP
            )
            if not any((impressions, clicks, cost, conversions, conversion_value)):
                continue

            date = _date(_field(record, "segments.date"))
            campaign_id = str(_field(record, "campaign.id"))
            if (date, campaign_id) in seen:
                raise SourceConfigError(
                    f"duplicate row for campaign {campaign_id} on {date}: refusing to guess"
                )
            seen.add((date, campaign_id))

            currency = _field(record, "customer.currency_code")
            rows.append(
                {
                    "connection_id": connection.id,
                    "client_id": connection.client_id,
                    "platform": PLATFORM,
                    "date": date,
                    "account_id": customer,
                    "campaign_id": campaign_id,
                    "campaign_name": _field(record, "campaign.name"),
                    "impressions": impressions,
                    "clicks": clicks,
                    "cost": cost,
                    "conversions": conversions,
                    "conversion_value": conversion_value,
                    "currency": str(currency).upper() if currency else None,
                }
            )
        rows.sort(key=lambda r: (r["date"], r["campaign_id"]))
        return rows
