# PG Analytics

Purple Giraffe's in-house client reporting platform. It pulls ad, analytics, SEO and local data for each client, stores it in Australia, and shows it in a branded portal with monthly PDF reports and AI commentary.

Before writing any code, read:

- `CLAUDE.md` for the security rules (these aren't optional)
- `docs/02-architecture.md` for the stack and data model
- `docs/01-api-access.md` for the platform API approvals (start these early, they take a while)
- `BUILD_INSTRUCTIONS.md` for the phase-by-phase build plan

## Repo layout

| Folder | What's in it |
|---|---|
| `supabase/` | Supabase CLI config, migrations (`reporting` schema with per-client RLS), test stub for plain Postgres |
| `ingestion/` | Python package `pganalytics_ingest`: pulls platform data with PyAirbyte / dlt and loads it into `reporting.*_daily` |
| `web/` | Next.js (App Router) + Tailwind portal for staff and clients |
| `scripts/` | Helper scripts (`gen-key.sh` makes a new `PGA_ENCRYPTION_KEY`) |
| `docs/` | API access steps and architecture |

## What you need installed

- Node 20+
- Python 3.11+ (and [uv](https://docs.astral.sh/uv/) or plain `pip`)
- Docker Desktop (running)
- Supabase CLI: `npm i -g supabase`, or use `npx supabase` without a global install
- Git

## First-time setup

1. Copy the env template and fill it in. Never commit the real files.

   ```bash
   cp .env.example .env
   cp .env.example web/.env.local
   ```

2. Generate an encryption key and paste it into `PGA_ENCRYPTION_KEY` in `.env`:

   ```bash
   ./scripts/gen-key.sh
   ```

## Running each part locally

### Database (Supabase)

```bash
supabase start
```

This starts Postgres, Auth, Storage and Studio in Docker and applies every migration in `supabase/migrations/`. When it finishes, run `supabase status` to get the local URL and keys, and put them in `.env` and `web/.env.local`:

- `SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_URL`: the API URL (usually `http://127.0.0.1:54321`)
- `SUPABASE_ANON_KEY` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`: the anon (publishable) key
- `SUPABASE_SERVICE_ROLE_KEY`: the service role (secret) key, `.env` only, never `web/.env.local` unless a server-only file needs it
- `DATABASE_URL`: `postgresql://postgres:postgres@127.0.0.1:54322/postgres`

To wipe the local database and re-apply all migrations:

```bash
supabase db reset
```

Studio (the local database UI) is at http://127.0.0.1:54323.

The `reporting` schema is exposed to the Supabase API in `supabase/config.toml` (`[api] schemas`). Remember to expose it in the hosted project's API settings too.

### Ingestion (Python)

```bash
cd ingestion
uv venv -p 3.11 .venv
uv pip install -p .venv -e '.[dev]'
source .venv/bin/activate
pytest
ruff check . && ruff format --check .
```

Without uv: `python3.11 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'`.

### Web app (Next.js)

```bash
cd web
npm install
npm run dev
```

Then open http://localhost:3000. The browser only ever gets the anon key; the service-role key stays on the server.

## Before you commit

- `git status` shows no `.env`, `.env.local`, `*.pem` or key `.json` files (they're in `.gitignore`, but check).
- `cd ingestion && pytest` passes.
- If you touched auth, tokens or RLS, get a second pair of eyes on the diff.
