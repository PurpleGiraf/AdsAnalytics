-- Dev seed: one test client with a Google Ads connection.
-- LOCAL / DEV DATABASES ONLY. Safe to re-run.
--
-- 1. Replace 0000000000 below with a real client customer ID (10 digits, no dashes)
--    that is linked under our MCC.
-- 2. Run:  psql "$DATABASE_URL" -f scripts/seed_dev.sql
-- 3. Sync: cd ingestion && python -m pganalytics_ingest sync --platform google_ads --client dev-test-client

insert into reporting.clients (name, slug, currency, timezone)
values ('Dev Test Client', 'dev-test-client', 'AUD', 'Australia/Adelaide')
on conflict (slug) do nothing;

insert into reporting.connections
  (client_id, platform, external_account_id, display_name, credential_source, status)
select id, 'google_ads', '0000000000', 'Dev Google Ads account', 'agency', 'pending'
from reporting.clients where slug = 'dev-test-client'
on conflict (client_id, platform, external_account_id) do nothing;
