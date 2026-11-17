# PG Analytics: build instructions for Claude Code

How to use this file:

1. Put this whole starter pack in the `PurpleGiraf/PGAnalytics` repo (it's empty, so it's ready for it).
2. Open the repo in Claude Code. It reads `CLAUDE.md` automatically, which holds the security rules.
3. Do **one phase at a time**. Paste the phase's prompt (the grey box), let it build, then check the **"Done when"** list yourself before moving on. Don't paste the whole file at once, because big-bang builds give you lots of half-working code.
4. Commit after each phase passes.

Start the API approvals (`docs/01-api-access.md`) **today**, before Phase 1. They take days to months, and the code can't pull real data without them.

---

## What's already in the starter pack

| File | What it is |
|---|---|
| `CLAUDE.md` | Security rules and conventions. Claude Code follows these automatically |
| `docs/01-api-access.md` | Step-by-step approvals for every platform, in priority order |
| `docs/02-architecture.md` | Stack, data model, credentials model, build order |
| `supabase/migrations/0001_init.sql` | Full database schema with per-client Row Level Security |
| `supabase/tests/supabase_stub.sql` | Lets the schema be tested on plain Postgres |

## The stack (already decided, don't let Claude Code change it)

- **Supabase** (Postgres + Auth), **Sydney region**
- **Python 3.11+** ingestion, using **PyAirbyte** to run Airbyte's connectors, and **dlt** for Google Business Profile
- **Next.js (App Router) + Tailwind**, same as the team's existing `PurpleGiraf/Analytics` app, with charts drawn natively (Recharts)
- **Playwright** for PDF reports
- **Claude API** for report commentary

## What you need installed

- Node 20+, Python 3.11+, Docker Desktop, Supabase CLI (`npm i -g supabase`), Git
- A Supabase project created in **Sydney (ap-southeast-2)**. Create a separate one for dev if you can.

---

## Phase 0: project setup

```
Read CLAUDE.md and docs/02-architecture.md first.

Set up the repo structure:
- ingestion/ : Python package `pganalytics_ingest` (pyproject.toml, ruff, pytest). Dependencies: airbyte (PyAirbyte), dlt, psycopg[binary] v3, cryptography, pydantic-settings, httpx, tenacity.
- web/ : Next.js (latest, App Router, TypeScript, Tailwind, ESLint), with @supabase/supabase-js and @supabase/ssr.
- supabase/ : initialise the Supabase CLI here (supabase init) but keep the existing migrations folder and 0001_init.sql.
- .env.example at the root listing every env var below, with comments, and NO real values. Make sure .env, .env.local and any *.pem / *.json key files are in .gitignore.
- A root README.md explaining how to run each part locally.

Env vars to list in .env.example:
SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY, DATABASE_URL,
PGA_ENCRYPTION_KEY (32 random bytes, base64),
GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_REFRESH_TOKEN, GOOGLE_ADS_DEVELOPER_TOKEN (legacy, can be a placeholder), GOOGLE_ADS_LOGIN_CUSTOMER_ID (our MCC, digits only),
META_SYSTEM_USER_TOKEN, META_APP_ID, META_APP_SECRET,
GOOGLE_SERVICE_ACCOUNT_JSON_PATH (GA4 + Search Console),
GBP_CLIENT_ID, GBP_CLIENT_SECRET, GBP_REFRESH_TOKEN,
LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET,
TIKTOK_APP_ID, TIKTOK_APP_SECRET,
MICROSOFT_ADS_CLIENT_ID, MICROSOFT_ADS_CLIENT_SECRET, MICROSOFT_ADS_DEVELOPER_TOKEN, MICROSOFT_ADS_REFRESH_TOKEN, MICROSOFT_ADS_CUSTOMER_ID,
ANTHROPIC_API_KEY,
REPORT_FROM_EMAIL, SMTP or Resend settings.

Also add a script scripts/gen-key.sh that prints a new PGA_ENCRYPTION_KEY.
```

**Done when:** `supabase start` runs locally, `cd ingestion && pytest` runs (even with 0 tests), `cd web && npm run dev` shows the default page, and `git status` shows no secrets.

---

## Phase 1: database + isolation tests

```
Apply supabase/migrations/0001_init.sql to the local Supabase (supabase db reset).

Then write ingestion/tests/test_rls.py (pytest + psycopg). It must create, as the postgres superuser:
- 2 clients (A and B), 1 staff user, 1 portal user linked only to client A
- rows in every metrics table and a connection_secrets row for both clients

Then, switching to the `authenticated` role with the JWT sub set (set local role authenticated; set local request.jwt.claims = '{"sub":"<uuid>"}'), assert:
1. Portal user A sees client A's rows in every metrics table and the v_ad_metrics_monthly view, and ZERO rows for client B.
2. Portal user A cannot insert/update/delete metrics, clients or connections.
3. Portal user A gets permission denied on connection_secrets.
4. Staff user sees both clients, but still cannot read connection_secrets.
5. The anon role can't read anything in the reporting schema.
6. A meta-test: query pg_class/pg_options for every view in the reporting schema and fail if any view lacks security_invoker=true.
7. A meta-test: every table in the reporting schema has relrowsecurity = true.

Make the tests run against DATABASE_URL (local Supabase). Also make them work against plain Postgres by loading supabase/tests/supabase_stub.sql first when an env flag PGA_TEST_PLAIN_POSTGRES=1 is set, so CI doesn't need Supabase.

Add a GitHub Actions workflow (.github/workflows/test.yml) that runs ruff and pytest against a postgres:16 service container using the stub.
```

**Done when:** all 7 checks pass. **This phase is the most important one. Don't skip it or let Claude Code weaken a test to make it pass.**

---

## Phase 2: ingestion framework + Google Ads

```
Build the ingestion framework in ingestion/pganalytics_ingest/:

- settings.py : pydantic-settings, loads all env vars. Never log values.
- crypto.py : AES-256-GCM encrypt/decrypt using PGA_ENCRYPTION_KEY. Format: base64(12-byte nonce || ciphertext || tag). Include key_version support. Tests: round trip, a tampered ciphertext fails, a wrong key fails.
- db.py : psycopg connection using the service-role DATABASE_URL. Functions: list_active_connections(platform, client_slug=None), start_sync_run(), finish_sync_run(status, rows, error), mark_connection_status(), upsert_rows(table, rows, conflict_cols). Upserts must use ON CONFLICT ... DO UPDATE and update loaded_at.
- errors.py : a redact() helper that strips anything token-shaped (long base64/JWT-like strings, 'Bearer ...', access_token=...) from error messages before they go into sync_runs.error or connections.last_error.
- sources/base.py : a Source protocol with fetch(connection, date_from, date_to) -> iterable of raw records, and normalise(raw_records, connection) -> list of rows for the target table.
- runner.py + __main__.py : CLI `python -m pganalytics_ingest sync --platform google_ads [--client SLUG] [--days 30] [--from YYYY-MM-DD --to YYYY-MM-DD]`. For each connection: start a sync_run, fetch, normalise, upsert, finish the sync_run. One connection failing must not stop the others. On auth errors mark the connection 'expired', on other errors 'error' (with redacted message), and on success 'active' + last_success_at.
- Default lookback: re-pull the last 30 days every run, because conversions get revised.

Then sources/google_ads.py, using PyAirbyte:
- source = airbyte.get_source("source-google-ads", config=..., install_if_missing=True)
- First run source.print_config_spec() and match the config keys to the CURRENT connector spec. Don't guess them.
- Credentials: agency-level OAuth from env (client id/secret/refresh token), login_customer_id = our MCC, customer_id = connections.external_account_id.
- Note: Google sunset developer tokens on 9 Sep 2026. The connector still needs a non-empty value, so a placeholder is fine. Our Cloud project needs Basic access.
- Use a custom GAQL query (the connector's custom_queries_array) rather than a built-in stream, so we control the fields exactly:
  SELECT customer.id, customer.currency_code, campaign.id, campaign.name, segments.date,
         metrics.impressions, metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.conversions_value
  FROM campaign WHERE segments.date BETWEEN '{from}' AND '{to}'
- Read into a PyAirbyte DuckDB cache (in a temp dir), then hand the records to normalise().
- normalise(): map to reporting.ad_metrics_daily. cost = cost_micros / 1_000_000. platform='google_ads'. Accept both dotted ("campaign.id") and underscored ("campaign_id") key styles, because connector output naming can vary. Skip rows where every metric is 0.
- Fixture test in tests/fixtures/google_ads_campaign.json with realistic rows (including a cost_micros of 12345678 -> 12.3457) and a test that normalise() output is exactly right.

Also scripts/seed_dev.sql: inserts a test client and a google_ads connection for a real client customer ID that I'll fill in.
```

**Done when:** fixture tests pass. Once Google Ads Basic access is approved, `python -m pganalytics_ingest sync --platform google_ads --client <slug>` loads real rows, the numbers match the Google Ads UI for the same dates (check spend and clicks for 3 days), and a deliberately wrong customer ID produces a failed `sync_runs` row with no token in the error.

---

## Phase 3: staff portal (first thing you can see)

```
Build the web app in web/ for PG staff:

- Supabase Auth with email magic link or Google sign-in restricted to @purplegiraffe.com.au. Use @supabase/ssr with server-side session handling. The browser only ever uses the ANON key. The service-role key is never imported into any file under web/app or any client component. Add an ESLint rule or a test that fails the build if SUPABASE_SERVICE_ROLE_KEY appears in web/ outside web/lib/server-admin.ts.
- Supabase client scoped to the `reporting` schema.
- Pages:
  /login
  /clients : list of clients with each connection's status (active/error/expired), last successful sync, and a red badge for anything not synced in 48 hours.
  /clients/[slug] : dashboard for one client with a date-range picker (default: last month, with comparison to the previous period):
     - KPI tiles: spend, clicks, conversions, cost per conversion, ROAS, each with % change vs previous period
     - Spend and conversions by day (line chart)
     - Breakdown by platform (table)
     - Top campaigns table (sortable)
  /clients/new and /clients/[slug]/connections : staff can add a client and add connections (platform + account ID).
- Use Recharts. Brand: Purple Giraffe purple, the Nordique Pro fonts, and the giraffe mark (copy from the PurpleGiraf/Analytics repo: src/fonts and public/assets/giraffe-mark.png).
- All metrics come from SQL (views or RPC functions in a new migration, security_invoker=true). No calculations of totals/ratios in React except formatting.
- Light and dark mode.
```

**Done when:** you can log in, see the client list, open one client and see correct Google Ads numbers, and a non-PG email can't log in.

---

## Phase 4: Meta Ads, GA4, Search Console

```
Add three sources, following the exact pattern of sources/google_ads.py (PyAirbyte, check the spec first, normalise() + fixture test for each):

1. sources/meta_ads.py : source-facebook-marketing.
   - Credentials: META_SYSTEM_USER_TOKEN (Airbyte open source needs an access token, not OAuth). account_ids = connections.external_account_id, digits only, with NO "act_" prefix.
   - Stream: ads_insights at campaign level, daily (time_increment 1). Map: spend -> cost, impressions, clicks (use inline_link_clicks if present, else clicks, and document which in a comment), conversions = the purchase/lead action values from `actions` per a per-client configurable list of action types (store this as connections.settings jsonb in a new migration, default ["purchase","lead"]), conversion_value from action_values for the same types.
   - Known limits to respect: insights only go back 37 months, the lookback window is capped at 28 days, and the 7d/28d view-through windows no longer exist (only 1d_view).
2. sources/ga4.py : source-google-analytics-data-api with the service account (GOOGLE_SERVICE_ACCOUNT_JSON_PATH). Custom report: dimensions date + sessionDefaultChannelGroup, metrics sessions, totalUsers, newUsers, engagedSessions, keyEvents, totalRevenue -> reporting.web_metrics_daily. Use a 1-day window_in_days to avoid sampling.
3. sources/search_console.py : source-google-search-console with the service account. Site-level daily totals (dimension: date only) -> reporting.search_metrics_daily. Data is only kept 16 months, so we must store history from day one. New Google Cloud projects often start at 60 requests/minute, so set requests_per_minute to 60.

Update the dashboard: add a Website section (sessions, users, key events by channel) and an SEO section (clicks, impressions, average position) to /clients/[slug].

Add a scheduler entry point: `python -m pganalytics_ingest sync --all` that runs every platform for every active connection, for running nightly.
```

**Done when:** for one real client, all four sources load and the numbers match each platform's own UI within rounding (Meta conversions can differ slightly because of attribution settings, so note any gap).

---

## Phase 5: client logins, monthly PDF, AI commentary

```
1. Client portal:
   - Staff can invite a client user (email) to a client from /clients/[slug]/users. That creates a reporting.client_users row.
   - Client users log in with a magic link, land on /portal (their own client's dashboard, read-only, no staff pages). If they belong to several clients, show a picker.
   - Add a test (Playwright) that logs in as client A's user and confirms client B's slug returns 404, and that the staff pages are blocked.

2. Monthly report:
   - A print-optimised route /reports/[slug]/[yyyy-mm] (A4, PG branding, cover page, one section per connected platform, KPI tiles with month-on-month and year-on-year change).
   - A new migration with reporting.reports (client_id, month, status draft|approved|sent, commentary text, pdf_path, approved_by, sent_at), RLS: staff full access, client users can read approved/sent reports for their client.
   - ingestion or a small web/worker script renders the PDF with Playwright and stores it in Supabase Storage (private bucket, Sydney), never a public URL. Clients download via a signed URL that expires in 1 hour.

3. AI commentary:
   - For a report, build a JSON summary from SQL only (this month vs last month vs same month last year, per platform, top/bottom campaigns). One client per call, aggregated numbers only, no personal data.
   - Send it to the Claude API (model from env var ANTHROPIC_MODEL) with a system prompt: write in Purple Giraffe's voice (warm, direct, plain English, Australian spelling, NO em dashes), 3 to 5 short paragraphs: what happened, why it probably happened, what we'll do next. Every number mentioned must come from the JSON. Never invent a figure.
   - After generating, run a check that every number in the text appears in the JSON (allowing rounding). If not, flag it for the strategist.
   - Staff review screen: edit the commentary, approve, then send. Nothing goes to a client without a human approving it.
   - Email the client a link (not an attachment) when it's sent.
```

**Done when:** you can generate a draft for one real client, edit and approve it, and the client gets an email, logs in and downloads the PDF. A second test client sees nothing of the first.

---

## Phase 6: remaining platforms (as approvals land)

```
Add these sources, each with normalise() + fixture test, same pattern:

1. sources/linkedin_ads.py : source-linkedin-ads. Per-client OAuth or agency token. Campaign x day ad analytics -> ad_metrics_daily (costInLocalCurrency -> cost, externalWebsiteConversions -> conversions). LinkedIn access tokens expire after 60 days and refresh tokens after 12 months: record token_expires_at and show a warning in the staff portal 14 days before expiry.
2. sources/tiktok_ads.py : source-tiktok-marketing. Campaign daily report -> ad_metrics_daily. TikTok reporting lags about 11 hours, so use a lookback of at least 3 days (we use 30 anyway).
3. sources/microsoft_ads.py : source-bing-ads. Campaign performance report, daily -> ad_metrics_daily. Refresh tokens expire after 90 days without use, so make sure the nightly sync keeps them alive, and store the rotated refresh token (encrypted) after every run.
4. sources/gbp.py : NO good Airbyte connector, so build it with dlt (or plain httpx) against the Business Profile Performance API: fetchMultiDailyMetricsTimeSeries for each location, metrics: BUSINESS_IMPRESSIONS_DESKTOP_MAPS, BUSINESS_IMPRESSIONS_DESKTOP_SEARCH, BUSINESS_IMPRESSIONS_MOBILE_MAPS, BUSINESS_IMPRESSIONS_MOBILE_SEARCH, CALL_CLICKS, WEBSITE_CLICKS, BUSINESS_DIRECTION_REQUESTS -> reporting.local_metrics_daily. Handle a 429 "quota 0" error with a clear message: "Business Profile API not approved yet for this Google Cloud project".
5. sources/instagram.py and sources/facebook_page.py : source-instagram (Airbyte-maintained) and source-facebook-pages (community-maintained, so check it works and fall back to direct Graph API calls if it doesn't) -> social_metrics_daily. Instagram user insights only go back 30 days, and Facebook Page insights need 100+ page likes.

When a new token is obtained via OAuth in the web app (LinkedIn, TikTok, client-owned accounts), the OAuth callback must be a server route that encrypts the token with web/lib/crypto.ts (AES-256-GCM, same format as Python, with a cross-language test) and writes it with the service role to connection_secrets. Tokens never go to the browser.

Add each platform's section to the dashboard and the PDF.
```

---

## Phase 7: alerts and goals

```
- New migration: reporting.goals (client_id, metric, period monthly, target, platform nullable) and reporting.alerts (client_id, rule, triggered_at, details, acknowledged_by).
- Nightly after sync, evaluate rules in SQL:
  - Spend pacing: month-to-date spend projected to month end vs monthly budget goal, alert if > 110% or < 80%.
  - Conversions drop: last 7 days vs the previous 28-day daily average, alert if down more than 30% with at least 20 conversions in the baseline.
  - Data freshness: any active connection without a successful sync in 48 hours.
  - Token expiry within 14 days.
- Send alerts to a Slack channel (webhook URL from env) and show them on /clients.
```

---

## Phase 8: deploy (Sydney)

```
Prepare deployment, everything in Australia:
- Supabase project in ap-southeast-2 (production), with migrations applied via supabase db push.
- Web app: deploy to a host with a Sydney region (Vercel with the syd1 function region, or Cloud Run in australia-southeast1). Set function region explicitly.
- Ingestion: Dockerfile for ingestion/, run nightly at 3am Adelaide time as a scheduled job in australia-southeast1 (Cloud Run Jobs + Cloud Scheduler) or ap-southeast-2. Secrets from the cloud secret manager, not baked into the image.
- PDF rendering worker: same image with Playwright + Chromium, enough memory (2 GB+).
- Write docs/03-runbook.md: how to add a client, connect each platform, rotate PGA_ENCRYPTION_KEY, what to do when a token expires, and how to re-run a failed sync.
```

---

## Rules of thumb while vibecoding

- **One phase, one session.** Start a fresh Claude Code chat per phase so it doesn't drift.
- **Ask it to show you the test results**, not just say "done". If a test was changed to pass, ask why.
- **Anything touching logins, tokens, RLS or the service-role key:** read the diff yourself or get a second pair of eyes. That's where a mistake leaks every client's data.
- **Check numbers against the platform UI** for every new source. A connector that "works" but double-counts is worse than one that fails.
- **Keep AgencyAnalytics running** until 5 to 10 clients are fully on PG Analytics.
