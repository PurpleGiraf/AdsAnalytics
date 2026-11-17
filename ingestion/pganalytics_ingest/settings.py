"""Environment settings. Values are never logged.

Secrets are `SecretStr`, so `repr()` and logging show `**********` instead of the value.
Call `.get_secret_value()` only at the point of use.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,  # validation errors never echo the value
    )

    # Supabase / database
    supabase_url: str | None = None
    supabase_anon_key: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None
    database_url: SecretStr | None = None

    # Encryption (see crypto.py)
    pga_encryption_key: SecretStr | None = None
    pga_encryption_key_version: int = 1
    # Older keys kept only to decrypt during a rotation: "1:<base64>,2:<base64>"
    pga_encryption_keys_previous: SecretStr | None = None

    # Google Ads (agency MCC)
    google_ads_client_id: str | None = None
    google_ads_client_secret: SecretStr | None = None
    google_ads_refresh_token: SecretStr | None = None
    google_ads_developer_token: SecretStr | None = None
    google_ads_login_customer_id: str | None = None

    # Meta
    meta_system_user_token: SecretStr | None = None
    meta_app_id: str | None = None
    meta_app_secret: SecretStr | None = None

    # Google service account (GA4 + Search Console)
    google_service_account_json_path: Path | None = None

    # Google Business Profile
    gbp_client_id: str | None = None
    gbp_client_secret: SecretStr | None = None
    gbp_refresh_token: SecretStr | None = None

    # LinkedIn
    linkedin_client_id: str | None = None
    linkedin_client_secret: SecretStr | None = None

    # TikTok
    tiktok_app_id: str | None = None
    tiktok_app_secret: SecretStr | None = None

    # Microsoft Ads
    microsoft_ads_client_id: str | None = None
    microsoft_ads_client_secret: SecretStr | None = None
    microsoft_ads_developer_token: SecretStr | None = None
    microsoft_ads_refresh_token: SecretStr | None = None
    microsoft_ads_customer_id: str | None = None

    # Claude API
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str | None = None

    # Ingestion behaviour
    pga_default_lookback_days: int = 30
    # Where PyAirbyte installs connector virtualenvs. Kept out of the repo.
    pga_airbyte_install_dir: Path = Path.home() / ".cache" / "pganalytics" / "connectors"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def require(value: object, name: str) -> object:
    """Fail clearly (naming the variable, never the value) when a setting is missing."""
    if value is None or (isinstance(value, SecretStr) and not value.get_secret_value()):
        raise MissingSettingError(f"{name} is not set. Add it to .env (see .env.example).")
    return value


class MissingSettingError(RuntimeError):
    pass
