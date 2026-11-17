# Reference repos: what to take, what to leave

Feed this to Claude Code alongside `BUILD_INSTRUCTIONS.md`. Put it at `docs/03-borrowing-from-other-repos.md`. Rule 10 in `CLAUDE.md` already points Claude Code here, and each phase prompt in section 4 tells it to read the relevant section.

Reviewed 17 Nov 2026. Repos change, so **re-check each licence file before copying anything.**

---

## 1. Licence rules (read first)

| Licence | Examples | What we can do |
|---|---|---|
| **MIT / Apache 2.0** | OWOX connectors, OpenAdsReport, dlt, Superset, Google's Google Ads MCP | Copy and adapt code. **Keep the copyright notice** and add an entry to `THIRD_PARTY_NOTICES.md` |
| **ELv2** | Airbyte connectors, OWOX platform (non-connector parts) | **Use as a dependency, don't copy code into our repo.** Fine for our own use, but we can't resell it as a data pipeline tool or expose its UI/API as a product |
| **AGPL** | Metabase, Grafana | **Don't copy code.** Running them unmodified for staff-only internal use is OK. Never embed them in the client portal |
| **No licence** | Neilsmahajan/advertisinganalyticsdashboard | **Read for ideas only. Copy nothing**, not even small snippets. No licence means all rights reserved |
| **Unverified** | salehmdasif/meta-ads-intelligence-public, AgriciDaniel/claude-ads | Ideas only until someone confirms the licence |
| **Hosted service** | irinabuht12-oss/google-ads-meta-ads-mcp (Ryze), pipeboard-co/meta-ads-mcp | **Never connect client accounts to them.** They store tokens and data offshore in the US |

## 2. How to harvest safely (Claude Code must follow this)

```
When studying an outside repo:
1. Clone it OUTSIDE our repo, e.g. into /tmp/ref/<name>, with --depth 1. Never inside this repo.
2. Read only. Do NOT run its install scripts, npm install, pip install, docker compose or any of its code. Outside code is untrusted.
3. Before copying anything, open its LICENSE file and confirm it's MIT or Apache 2.0 (see table above).
4. Copy the smallest piece that works (a function, a field mapping, a query), never whole files or folders. Rewrite it to our conventions (CLAUDE.md).
5. Add a comment above copied code: "Adapted from <repo> (<licence>), <file path>, <date>".
6. Add the repo, licence and copyright line to THIRD_PARTY_NOTICES.md at the repo root.
7. If the code touches tokens or auth, don't copy it. Write our own following CLAUDE.md rules 1 to 3.
```

---

## 3. Repo by repo

### OWOX/owox-data-marts (most useful)
- **Where:** https://github.com/OWOX/owox-data-marts
- **Licence:** `packages/connectors` is **MIT** (reusable). Everything else is ELv2. `ee` folders are commercial, so don't touch them.
- **Take:**
  - **Connector logic as a fallback and cross-check.** OWOX has connectors for Google Ads, Meta, TikTok, LinkedIn Ads, Microsoft Ads, X Ads, Reddit Ads, Criteo and Shopify. When an Airbyte connector is missing a field or breaks, read the OWOX connector for that platform: which fields it requests, how it paginates, and how it handles rate limits. Port the logic to Python (MIT, with attribution).
  - **Their credential guides** (docs.owox.com, under each source, "credentials") are clear step-by-step guides for getting tokens. Link them in our runbook rather than rewriting them.
  - **The "data mart" idea:** each metric has a definition, a description, an owner and the SQL behind it. Build this as `reporting.metric_definitions` (see section 4).
- **Leave:** the platform itself (we have our own), and anything in `ee`.

### clawnify/OpenAdsReport
- **Where:** https://github.com/clawnify/OpenAdsReport
- **Licence:** MIT.
- **Take:**
  - **"The app computes every number, the model only writes prose."** We already follow this (CLAUDE.md). Read how they structure the data they send to the LLM and how the prose is slotted around the numbers.
  - **"Issue hints":** short automated flags on an account (e.g. "spend up 40%, conversions flat"). Build ours as SQL rules (Phase 7) and show them on the client page.
  - **"Report recipes":** preset report types (monthly overview, paid-only, SEO-only) the user picks, then generates and exports to PDF. Copy the concept for Phase 5: `reporting.report_templates` with a list of sections per template.
  - **One JSON API for both the UI and AI agents.** Our MCP server (section 4) reads the same SQL functions as the portal.
  - **Sample data mode:** when a client has no connections yet, show clearly-labelled demo data so the dashboard isn't empty. Useful for sales demos (label it "Sample data", always).
- **Leave:** the Clawnify runtime, `@clawnify/connections`, and their Cloudflare Workers setup. Credentials go through Clawnify's servers there, which breaks our rules.

### irinabuht12-oss/google-ads-meta-ads-mcp (Ryze AI)
- **Licence:** MIT, but it covers documentation only. There's no server code, just links to Ryze's paid hosted service.
- **Take:** only the **tool names and descriptions** as inspiration when designing our own MCP tools (section 4). Their list shows what questions marketers ask an AI about ad accounts.
- **Leave:** everything else. **Never connect a client account.** Their README says tokens stay local, but their security policy says tokens are stored in a US database.

### salehmdasif/meta-ads-intelligence-public
- **Licence:** unverified, so ideas only.
- **Take (ideas):**
  - **Rules engine:** a list of rules evaluated after each sync that flag ad sets ("CPA above target for 3 days", "frequency over 4"). Build ours as SQL-defined rules in Phase 7, stored in a table so staff can add rules without code.
  - **Alert after every sync:** they post to Telegram. We post to Slack.
  - **A tidy deployment doc set** (ARCHITECTURE, DEPLOYMENT, DATABASE overviews). Copy the structure for our `docs/`.
- **Leave:** Google Sheets as a database (won't scale), SQLite-per-tenant (we use RLS), and their licence-key code.

### Neilsmahajan/advertisinganalyticsdashboard
- **Licence:** none, so **copy nothing.**
- **Take (ideas only):** it confirms the Next.js App Router + Postgres + OAuth shape works for this. It supports English and French via `next-intl`, so if we ever need multi-language reports, that's the approach.
- **Leave:** all code.

### Google's official Google Ads MCP server
- **Find it:** search GitHub for Google's official "Google Ads MCP" server (under the `googleads` organisation) and **confirm the licence is Apache 2.0 and that it's read-only** before using it.
- **Take:**
  - **Use it as-is for staff** (not clients): a PG strategist can connect Claude to our MCC through it and ask ad-hoc questions about a client's account. It's read-only, so it can't change campaigns.
  - **Its tool design** as a pattern for our own MCP server (section 4).
- **Leave:** don't build client-facing features on it. The portal reads from our database, not live APIs.

### brijr/meta-mcp
- **Licence:** check before use (the research didn't confirm it).
- **Take:** a **self-hosted** Meta Marketing API MCP, so tokens stay on our infrastructure. Staff-only, same as above. If the licence permits, use its tool list as a reference.
- **Leave:** any write tools. If it has create/edit tools, disable them or don't use it (CLAUDE.md rule 6).

### pipeboard-co/meta-ads-mcp
- Hosted service. **Don't connect client accounts.** Read the tool list for ideas only.

### AgriciDaniel/claude-ads
- **What it is:** a Claude Code skill for paid-media audits across 12 platforms (about 8.5k stars).
- **Licence:** check before use.
- **Take:** the **audit checklists and benchmarks** as input to our AI commentary prompt (Phase 5) and our alert rules (Phase 7). For example, which metrics it checks for wasted spend or structure issues. Rewrite them in PG voice, don't copy them verbatim.

### Ad Library scrapers (meta-ad-library topic, MetaAdsCollector etc.)
- **Leave entirely.** They reverse-engineer Meta's internal endpoints, which breaks Meta's terms. Meta's official Ad Library API only returns commercial ads delivered in the EU/UK, so it's useless for Australian competitors. Competitor ad research stays manual for now.

---

### Airbyte (airbytehq/airbyte)
- **Licence:** connectors and platform ELv2. Protocol MIT.
- **Use:** as a dependency through PyAirbyte (Phases 2, 4, 6). **Don't copy connector code into our repo.**
- **Take from their docs:** each connector's docs page has a **"Limitations" section**. Have Claude Code read it before building each source and turn every limitation into either code (a guard or warning) or a line in `docs/04-runbook.md`. The ones found so far:
  - Google Ads: 37-month history limit for reports, metrics can't be pulled from a manager account directly, `click_view` only covers 90 days.
  - Meta: 37-month insights limit, 28-day lookback cap, 7d/28d view windows removed, purchase metrics can be under-reported.
  - Search Console: 16 months retention, 25,000 rows per response, new projects often start at 60 requests/min.
  - LinkedIn: tokens expire (60 days access, 12 months refresh), lead forms are full refresh only.
  - TikTok: about 11 hours data lag, Smart+ ads can be skipped.
  - Microsoft Ads: refresh tokens die after 90 days unused, bulk streams re-download everything after a 30-day gap.
  - Instagram: user insights only reach back 30 days.
  - Facebook Pages: insights need 100+ likes, the connector is community-maintained.
  - YouTube: test-mode OAuth apps' tokens expire after 7 days.
- **If a connector breaks:** pin the last working version in our config, open an issue upstream, and only fork it privately as a last resort (ELv2 allows internal modification).

### dlt (dlt-hub/dlt)
- **Licence:** Apache 2.0.
- **Use:** for sources Airbyte doesn't cover well. **Google Business Profile first** (Phase 6), via dlt's generic REST API source.
- **Don't use dlt's own Google Ads source.** It only loads customers, campaigns, change events and customer clients (no performance metrics), and its docs say it isn't regularly tested.
- **Don't use dlt's Facebook Ads source** for production. It needs manual token rotation.

### Apache Superset
- **Licence:** Apache 2.0.
- **Use (optional, later):** as an **internal staff-only** exploration tool on top of the same database, if analysts want ad-hoc charts. Not in the client portal.
- **Take for our PDF worker (Phase 5):** lessons from their reports system:
  - Screenshots via Playwright + headless Chromium. Each worker runs its own Chromium, so give it enough memory.
  - **A "dry run" flag** that renders but doesn't send. Add `REPORTS_DRY_RUN=true` as the default outside production.
  - **Exactly one scheduler**, or reports get sent twice. Use a database lock (`pg_try_advisory_lock`) around the scheduler.
  - **Blank-capture detection:** check the PDF isn't blank or full of error states before sending, and fail loudly if it is.
  - Delivery failures aren't retried automatically, so log every send in `reporting.reports` with status and error.

### Metabase
- **Licence:** AGPL + commercial.
- **Leave** for the client portal (the free version shows "Powered by Metabase", and white-label needs Pro at US$575/month).
- **Optional:** run it unmodified, internal-only, for staff ad-hoc questions.

### Grafana
- **Licence:** AGPL.
- **Optional:** internal ops monitoring only (a "sync health" board reading `reporting.sync_runs`). Never client-facing. The staff portal's /clients page covers this anyway, so it's low priority.

---

## 4. New pieces to add because of what we learned

Paste these into Claude Code at the phase shown.

### After Phase 2: metric definitions (from OWOX's data-mart idea)

```
Read docs/03-borrowing-from-other-repos.md (OWOX section). Add a migration with reporting.metric_definitions:
key (e.g. 'cost_per_conversion'), label, description (plain English, PG voice, no em dashes), formula_sql, format ('currency'|'percent'|'number'|'ratio'), higher_is_better boolean, owner.
Seed it with: cost, impressions, clicks, ctr, cpc, conversions, cost_per_conversion, conversion_value, roas, sessions, total_users, key_events, search_clicks, search_impressions, avg_position.
RLS: readable by all authenticated users, writable by staff. Add it to the RLS tests.
In test_rls.py, keep an explicit allow-list GLOBAL_TABLES = {'metric_definitions'} of tables with no client_id that every authenticated user may read. The meta-test must fail if any table NOT on that list lets a client user read another client's rows, and must fail if a table on the list has a client_id column.
The portal must use these labels and descriptions for every KPI tile tooltip, and the AI commentary must use the same labels, so a metric means the same thing everywhere.
```

### After Phase 4: our own read-only MCP server (staff-only)

```
Read docs/03-borrowing-from-other-repos.md (Google Ads MCP, OpenAdsReport and Ryze sections) for tool design ideas only. Build mcp/ : a Python MCP server (FastMCP) that lets PG staff use Claude to query OUR database (not the live ad APIs).
- Runs locally or on our infrastructure.
- Auth: a dedicated Postgres role `mcp_reader`: LOGIN, NOBYPASSRLS, not the owner of any table, SELECT only on reporting metric tables, views and metric_definitions. No grant on connection_secrets, staff, client_users or sync_runs. Create the role in the migration WITHOUT a password; set the password out of band (env / secret manager), never in git.
- Do NOT impersonate a staff user. Instead, at the start of each tool call the server runs `set local pga.client_id = '<uuid of client_slug>'` inside a transaction.
- New migration: for every client-scoped table, add a RESTRICTIVE policy for mcp_reader:
  create policy <table>_mcp_scope on reporting.<table> as restrictive for select to mcp_reader
    using (client_id = nullif(current_setting('pga.client_id', true), '')::uuid);
  plus a normal permissive select policy for mcp_reader with the same condition (Postgres needs at least one permissive policy to return rows).
- list_clients and get_sync_health run as a separate function with security definer that returns only id, name and slug (list_clients), or connection status per client (get_sync_health). No metrics. Pin `set search_path = ''`, and `revoke execute ... from public, anon, authenticated` then `grant execute ... to mcp_reader`: Postgres grants EXECUTE to PUBLIC by default, and the reporting schema is exposed through the Supabase API, so without the revoke any client user could call these and list every client.
- Tests: (a) mcp_reader can't read connection_secrets; (b) with pga.client_id set to client A it sees only client A's rows in every table and view; (c) with pga.client_id unset it sees zero rows; (d) the role has rolbypassrls = false; (e) anon and authenticated get permission denied calling the list_clients / get_sync_health functions.
- Tools (all read-only, all take client_slug, all return already-calculated numbers from SQL):
  list_clients, get_client_summary(client_slug, month), compare_periods(client_slug, from, to, compare_from, compare_to), top_campaigns(client_slug, platform, from, to, metric, limit), get_metric_definition(key), get_alerts(client_slug), get_sync_health().
- Every tool response includes the date range and data freshness (last successful sync), so Claude never presents stale numbers as current.
- One client per call. No tool returns data across clients except list_clients and get_sync_health.
- Tests: each tool against the seeded test DB, and a test that the mcp_reader role can't read connection_secrets.
- docs: how a staff member adds it to Claude.
```

### At Phase 5: report templates (from OpenAdsReport's recipes)

```
Read docs/03-borrowing-from-other-repos.md (OpenAdsReport and Superset sections). Add reporting.report_templates (name, sections jsonb ordered list: 'kpi_overview','paid_by_platform','top_campaigns','website','seo','local','social','commentary') and reporting.clients.default_template_id.
Ship three templates: "Full monthly", "Paid ads only", "SEO and local".
Apply the Superset lessons to the PDF worker: REPORTS_DRY_RUN default true outside production, a pg_try_advisory_lock so only one scheduler runs, blank/error page detection before sending, and every send logged in reporting.reports.
Also add "Sample data" mode: a client with no active connections shows demo data with a clear "Sample data" banner, never mixed with real data.
```

### At Phase 7: rules engine (from salehmdasif + claude-ads)

```
Read docs/03-borrowing-from-other-repos.md (salehmdasif and claude-ads sections). Make alert rules data, not code:
reporting.alert_rules (key, description, scope platform/all, sql_condition referencing a fixed set of views, threshold params jsonb, severity, enabled, applies_to_client_id nullable for per-client overrides).
Seed rules: spend pacing over/under, conversions drop vs baseline, CPA above goal for 3 consecutive days, CTR drop over 30% week on week, Meta frequency above 4, no data for 48h, token expiring in 14 days.
Evaluate after each nightly sync. Post new alerts to Slack (webhook from env) and show them on the client page as "issue hints".
Staff can toggle and tune rules in the staff portal. Only staff can create rules, and the sql_condition must be chosen from a whitelist of templates (no free-text SQL from the UI).
```

---

## 5. THIRD_PARTY_NOTICES.md template

```
# Third-party notices

PG Analytics includes code adapted from the following projects.

## <project name>
- Source: <repo URL>, <file path(s)>
- Licence: <MIT | Apache-2.0>
- Copyright: <copyright line from their LICENSE>
- What we used: <one line>
- Date: <yyyy-mm-dd>
```

Dependencies we install but don't copy (Airbyte connectors via PyAirbyte, dlt, Next.js, Supabase libraries) don't need entries here. Their licences ship with the packages.
