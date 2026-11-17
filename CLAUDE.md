# PG Analytics: rules for anyone (human or AI) writing code here

PG Analytics is Purple Giraffe's in-house client reporting platform (our own AgencyAnalytics). It pulls ad, analytics, SEO and local data for each client, stores it in Australia, and shows it in a branded client portal with scheduled PDF reports and AI commentary.

Read `docs/02-architecture.md` before making structural changes.

## Security rules (non-negotiable)

This app holds access to every client's ad accounts. One mistake here exposes all of them at once. If a request conflicts with a rule below, stop and say so instead of working around it.

1. **Never put secrets in code, git, logs or error messages.** API keys, OAuth tokens, refresh tokens and passwords live in environment variables (local `.env`, never committed) or encrypted in `reporting.connection_secrets`. Never `print`/`console.log` a token, even partially.
2. **Client tokens are encrypted before they touch the database.** Use `ingestion/pganalytics_ingest/crypto.py` (Python) or `web/lib/crypto.ts` (Node), AES-256-GCM, with the key from `PGA_ENCRYPTION_KEY`. Never store a token in plain text, not even "temporarily".
3. **`reporting.connection_secrets` is service-role only.** The web app's browser code must never read it. No API route may return it.
4. **Every client-facing query is filtered by client, enforced by the database.** Row Level Security (RLS) is on for every table in `reporting`. Never disable RLS, never add `using (true)` policies, and never query client data with the service-role key from code that serves a logged-in user. The one exception: a table on the `GLOBAL_TABLES` allow-list in `ingestion/tests/test_rls.py` (no `client_id`, no client data, e.g. metric labels) may have a `using (true)` policy for **select only**. The tests enforce both conditions, so don't use this for anything holding client data.
5. **Views must use `security_invoker = true`.** A normal Postgres view runs as its owner and **skips RLS**, which would show one client another client's data. Every `create view` in `reporting` needs `with (security_invoker = true)`. There is a test for this, so don't delete it.
6. **Read-only API scopes only.** We never create, edit or pause campaigns. Don't request `ads_management`, `rw_ads`, or any write scope.
7. **Data stays in Australia.** Database, storage and job runners live in Sydney (`ap-southeast-2` or `australia-southeast1`). Don't add a service that stores client data offshore without checking with the team first.
8. **No client data in AI prompts beyond what's needed.** Claude gets aggregated metrics for one client at a time. Never send another client's data, raw tokens, or personal information (lead names, emails, phone numbers).
9. **Every new table** needs RLS enabled, policies, and an isolation test in `ingestion/tests/test_rls.py`.
10. **Respect other repos' licences, and treat their code as untrusted.** Read `docs/03-borrowing-from-other-repos.md` before reusing anything. Clone reference repos to `/tmp/ref/`, never into this repo, and never install or run their code. Only MIT or Apache 2.0 code may be adapted, with credit in `THIRD_PARTY_NOTICES.md`. Unlicensed, unverified or "demo only" repos are for ideas only. Never copy token, OAuth or auth code from anywhere: write our own under rules 1 to 3. Never connect a client account to a hosted third-party service.

## How the data flows

```
Platform APIs ──> ingestion (Python: Airbyte connectors / dlt) ──> reporting.*_daily tables
                                                                         │
                       client portal (Next.js) <── RLS-filtered reads ───┘
                       PDF reports + Claude commentary
```

- **Numbers come from SQL. Claude only writes the words around them.** Never ask the model to calculate a metric.
- Ingestion re-pulls a lookback window (default 30 days) every run, because platforms revise conversions after the fact. Loads are upserts, so re-running is always safe.
- Every sync writes a row to `reporting.sync_runs`, whether it succeeds or fails.

## Conventions

- Database: all app tables live in the `reporting` schema. Migrations go in `supabase/migrations/NNNN_description.sql`, numbered, and **never edit a migration that's already been applied**. Add a new one instead.
- Money is stored as `numeric(14,4)` in the account's currency, with a `currency` column. Google's `cost_micros` is divided by 1,000,000 at load time.
- Dates are the **ad account's local date** as the platform reports it. Don't convert to UTC.
- Platform names are lowercase identifiers: `google_ads`, `meta_ads`, `ga4`, `search_console`, `gbp`, `linkedin_ads`, `tiktok_ads`, `microsoft_ads`, `facebook_page`, `instagram`.
- Python: 3.11+, type hints, `ruff` formatting, tests with `pytest`. Each source lives in `ingestion/pganalytics_ingest/sources/<platform>.py` and has a pure `normalise()` function with fixture tests.
- Web: Next.js (App Router) + Tailwind + Supabase, matching the team's existing `PurpleGiraf/Analytics` app.
- Client-facing copy follows the PG voice: warm, direct, plain English, and **no em dashes**.

## Before you say something is done

- `cd ingestion && pytest` passes (includes the RLS isolation tests, which need Docker).
- New sources have a fixture test proving the numbers come out right (for example, micros are converted and dates parse).
- If you touched auth, tokens or RLS, flag it in the PR description for a human review.
