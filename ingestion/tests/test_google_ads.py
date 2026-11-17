import datetime as dt
import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from pganalytics_ingest.db import Connection
from pganalytics_ingest.errors import SourceConfigError
from pganalytics_ingest.settings import MissingSettingError, Settings
from pganalytics_ingest.sources.google_ads import (
    STREAM,
    GoogleAdsSource,
    build_config,
    build_query,
    customer_id_digits,
)

FIXTURE = Path(__file__).parent / "fixtures" / "google_ads_campaign.json"
CONN_ID = uuid.UUID("00000000-0000-0000-0000-00000000c0de")
CLIENT_ID = uuid.UUID("00000000-0000-0000-0000-0000000c1e17")


def connection(account: str = "123-456-7890") -> Connection:
    return Connection(
        id=CONN_ID,
        client_id=CLIENT_ID,
        client_slug="test-client",
        client_timezone="Australia/Adelaide",
        platform="google_ads",
        external_account_id=account,
        credential_source="agency",
        status="active",
    )


def raw_records() -> list[dict]:
    return json.loads(FIXTURE.read_text())


def underscored(records: list[dict]) -> list[dict]:
    return [{k.replace(".", "_"): v for k, v in r.items()} for r in records]


def expected_row(date, campaign_id, name, impressions, clicks, cost, conv, value):
    return {
        "connection_id": CONN_ID,
        "client_id": CLIENT_ID,
        "platform": "google_ads",
        "date": dt.date.fromisoformat(date),
        "account_id": "1234567890",
        "campaign_id": campaign_id,
        "campaign_name": name,
        "impressions": impressions,
        "clicks": clicks,
        "cost": Decimal(cost),
        "conversions": Decimal(conv),
        "conversion_value": Decimal(value),
        "currency": "AUD",
    }


EXPECTED = [
    expected_row(
        "2026-10-01", "111111111", "Brand | Search", 1520, 87, "12.3457", "3.0000", "450.5000"
    ),
    expected_row(
        "2026-10-01", "222222222", "Generic | Search", 9800, 210, "268.4500", "7.5000", "1125.2500"
    ),
    # 2026-10-02 Brand is all zeros, so it's skipped.
    expected_row(
        "2026-10-02", "222222222", "Generic | Search", 10234, 198, "252.0000", "6.3333", "0.0000"
    ),
    # A conversion-only row (a late-attributed conversion) is kept.
    expected_row("2026-10-03", "333333333", "Performance Max", 0, 0, "0.0000", "1.0000", "99.0000"),
]


def test_normalise_dotted_keys_exact() -> None:
    assert GoogleAdsSource().normalise(raw_records(), connection()) == EXPECTED


def test_normalise_underscored_keys_exact() -> None:
    assert GoogleAdsSource().normalise(underscored(raw_records()), connection()) == EXPECTED


def test_cost_micros_conversion() -> None:
    rows = GoogleAdsSource().normalise(raw_records()[:1], connection())
    assert rows[0]["cost"] == Decimal("12.3457")  # 12345678 micros
    assert rows[0]["cost"].as_tuple().exponent == -4


def test_string_values_parse_the_same() -> None:
    as_strings = [{k: str(v) for k, v in r.items()} for r in raw_records()]
    assert GoogleAdsSource().normalise(as_strings, connection()) == EXPECTED


def test_record_for_another_customer_is_rejected() -> None:
    records = raw_records()
    records[1]["customer.id"] = 9999999999
    with pytest.raises(SourceConfigError, match="9999999999"):
        GoogleAdsSource().normalise(records, connection())


def test_duplicate_campaign_day_is_rejected() -> None:
    records = raw_records()
    records.append(dict(records[0]))
    with pytest.raises(SourceConfigError, match="duplicate"):
        GoogleAdsSource().normalise(records, connection())


def test_missing_field_is_an_error_not_a_zero() -> None:
    records = raw_records()
    del records[0]["metrics.clicks"]
    with pytest.raises(KeyError, match="metrics.clicks"):
        GoogleAdsSource().normalise(records, connection())


@pytest.mark.parametrize("value", ["1234567890", "123-456-7890", " 123 456 7890 "])
def test_customer_id_digits(value: str) -> None:
    assert customer_id_digits(value) == "1234567890"


@pytest.mark.parametrize("value", ["12345", "act_1234567890123", ""])
def test_customer_id_digits_rejects_bad_ids(value: str) -> None:
    with pytest.raises(SourceConfigError):
        customer_id_digits(value)


def test_build_query() -> None:
    query = build_query(dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    assert query == (
        "SELECT customer.id, customer.currency_code, campaign.id, campaign.name, segments.date, "
        "metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, "
        "metrics.conversions_value "
        "FROM campaign WHERE segments.date BETWEEN '2026-10-01' AND '2026-10-31'"
    )
    with pytest.raises(ValueError):
        build_query(dt.date(2026, 10, 2), dt.date(2026, 10, 1))


def _settings(**overrides) -> Settings:
    values = {
        "google_ads_client_id": "client-id",
        "google_ads_client_secret": SecretStr("s3cret"),
        "google_ads_refresh_token": SecretStr("refresh"),
        "google_ads_developer_token": SecretStr("placeholder"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_build_config_matches_connector_spec_keys() -> None:
    config = build_config(_settings(), "1234567890", dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    assert set(config) == {
        "credentials",
        "customer_id",
        "start_date",
        "end_date",
        "custom_queries_array",
    }
    assert set(config["credentials"]) == {
        "developer_token",
        "client_id",
        "client_secret",
        "refresh_token",
    }
    assert config["customer_id"] == "1234567890"
    assert config["custom_queries_array"][0]["table_name"] == STREAM
    assert "BETWEEN '2026-10-01' AND '2026-10-31'" in config["custom_queries_array"][0]["query"]


def test_build_config_names_missing_setting_without_values() -> None:
    with pytest.raises(MissingSettingError, match="GOOGLE_ADS_REFRESH_TOKEN"):
        build_config(
            _settings(google_ads_refresh_token=None),
            "1234567890",
            dt.date(2026, 10, 1),
            dt.date(2026, 10, 2),
        )


class FakeConnectorError(Exception):
    def __init__(self, log_file):
        super().__init__("Connector failed.")
        self.log_file = log_file
        self.log_text = None


def test_connector_error_reasons_reads_trace_errors(tmp_path) -> None:
    from pganalytics_ingest.sources.google_ads import connector_error_reasons

    trace = {
        "type": "TRACE",
        "trace": {
            "type": "ERROR",
            "error": {"message": "The authentication to Google Ads has expired."},
        },
    }
    log = tmp_path / "connector.log"
    log.write_text(
        "2026-11-17 05:54:46 - ERROR - something\n"
        f"2026-11-17 05:54:46 - INFO - {json.dumps(trace)}\n"
        f"2026-11-17 05:54:47 - INFO - {json.dumps(trace)}\n"
        '2026-11-17 05:54:47 - INFO - {"type":"LOG","log":{"level":"INFO"}}\n'
    )
    assert connector_error_reasons(FakeConnectorError(log)) == [
        "The authentication to Google Ads has expired."
    ]
    assert connector_error_reasons(FakeConnectorError(tmp_path / "missing.log")) == []
