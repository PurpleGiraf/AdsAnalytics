# Architecture

## Goal

Replace AgencyAnalytics for Purple Giraffe clients with a platform we own:

- Data from Google Ads, Meta Ads, GA4, Search Console, Google Business Profile, LinkedIn Ads, TikTok Ads and Microsoft Ads (version 1)
- A branded client portal, where each client sees only their own data
- Scheduled monthly PDF reports
- Claude-written commentary on top of numbers calculated in SQL

## Components

| Layer | Choice | Why |
|---|---|---|
| Database + auth | **Supabase (Postgres), Sydney region** | The team already uses it (`PurpleGiraf/Analytics`). Postgres Row Level Security gives per-client isolation in the database, and Supabase Auth handles client logins |
| Data pulls | **Airbyte connectors, run in Python with PyAirbyte** | Airbyte-maintained connectors exist for Google Ads, Meta, GA4, Search Console, LinkedIn, TikTok, Microsoft Ads, Instagram and Shopify, updated within the last week (checked 17 Nov 2026). PyAirbyte runs them as plain Python, so we don't host the Airbyte platform |
| Custom pulls | **dlt** (Apache 2.0) | For platforms without a solid Airbyte connector, Google Business Profile first |
| Client portal | **Next.js + Tailwind** | Matches the existing app. Charts are drawn natively in the portal (not embedded Superset), because that's one less server to run and the Superset embedding SDK is still alpha |
| PDF reports | Headless Chromium (Playwright) rendering a print view of the portal | One design for screen and PDF |
| AI commentary | Claude API, fed one client's aggregated metrics | Claude writes the narrative, SQL does the maths, a strategist approves it before it's sent |
| Scheduling | Decide when hosting is chosen (Cloud Run jobs / ECS / cron on a VM), in Sydney | |

## Credentials model

Two kinds of access:

1. **Agency-level credentials** (stored as environment secrets, never in the DB):
   - Google Ads: our manager account (MCC) OAuth refresh token. Every client account is linked under the MCC, so `connections.external_account_id` is just the client's customer ID.
   - Meta: a system user token, with client ad accounts assigned to it in Business Settings.
   - GA4 / Search Console: a service account, added as Viewer on each client property.
   - Microsoft Ads: our manager account OAuth + developer token.
2. **Per-client credentials** (encrypted in `reporting.connection_secrets`): used only when a client connects an account we don't manage (for example, they log in with OAuth from the portal). Encrypted with AES-256-GCM using `PGA_ENCRYPTION_KEY`.

Prefer agency-level access. It's simpler, we revoke one credential instead of hundreds, and clients don't have to click through OAuth screens.

## Data model (schema `reporting`)

| Table | Purpose |
|---|---|
| `clients` | One row per client |
| `staff` | PG staff users (see all clients) |
| `client_users` | Portal logins, mapped to one or more clients |
| `connections` | Each platform account linked to a client (status, last sync, errors) |
| `connection_secrets` | Encrypted per-client tokens. Service role only |
| `sync_runs` | Append-only log of every sync |
| `ad_metrics_daily` | Paid ads, campaign x day, all ad platforms in one shape |
| `web_metrics_daily` | GA4, channel group x day |
| `search_metrics_daily` | Search Console, site x day |
| `local_metrics_daily` | Google Business Profile, location x metric x day |
| `social_metrics_daily` | Organic Facebook / Instagram / LinkedIn, account x day |

All ad platforms land in the same `ad_metrics_daily` shape, so the portal draws "all paid channels" with one query.

## Build order

1. **Slice 1 (this commit):** schema + RLS tests, Google Ads pull from the MCC into `ad_metrics_daily`.
2. Slice 2: minimal portal: staff login, client list, one client's Google Ads dashboard.
3. Slice 3: Meta Ads, GA4, Search Console (agency-level credentials, same pattern).
4. Slice 4: client logins + monthly PDF report + Claude commentary with approval step.
5. Slice 5: LinkedIn, TikTok, Microsoft Ads, Google Business Profile (as approvals land).
6. Slice 6: alerts (spend pacing, conversion drops) and goals.

Keep AgencyAnalytics running until 5 to 10 clients are fully on PG Analytics.
