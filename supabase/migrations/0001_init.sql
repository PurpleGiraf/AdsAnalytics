-- PG Analytics: initial schema.
-- Everything lives in the `reporting` schema. RLS is on for every table.
-- Rules: see CLAUDE.md (views need security_invoker, secrets are service-role only).

create schema if not exists reporting;

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------
create type reporting.platform as enum (
  'google_ads', 'meta_ads', 'ga4', 'search_console', 'gbp',
  'linkedin_ads', 'tiktok_ads', 'microsoft_ads', 'facebook_page', 'instagram'
);

create type reporting.connection_status as enum (
  'pending', 'active', 'error', 'expired', 'disabled'
);

create type reporting.sync_status as enum ('running', 'succeeded', 'failed');

-- ---------------------------------------------------------------------------
-- Clients and people
-- ---------------------------------------------------------------------------
create table reporting.clients (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  slug        text not null unique check (slug ~ '^[a-z0-9-]+$'),
  currency    char(3) not null default 'AUD',
  timezone    text not null default 'Australia/Adelaide',
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

-- PG staff: can see and manage every client.
create table reporting.staff (
  user_id     uuid primary key references auth.users(id) on delete cascade,
  role        text not null default 'staff' check (role in ('admin', 'staff')),
  created_at  timestamptz not null default now()
);

-- Client portal logins. A user can belong to more than one client (e.g. a group).
create table reporting.client_users (
  user_id     uuid not null references auth.users(id) on delete cascade,
  client_id   uuid not null references reporting.clients(id) on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (user_id, client_id)
);

-- ---------------------------------------------------------------------------
-- Connections (platform accounts linked to a client)
-- ---------------------------------------------------------------------------
create table reporting.connections (
  id                   uuid primary key default gen_random_uuid(),
  client_id            uuid not null references reporting.clients(id) on delete cascade,
  platform             reporting.platform not null,
  external_account_id  text not null,          -- e.g. Google Ads customer ID "1234567890"
  display_name         text,
  -- 'agency' = use the agency-level credential from env (MCC, Meta system user, service account)
  -- 'client' = use the encrypted per-client token in connection_secrets
  credential_source    text not null default 'agency' check (credential_source in ('agency', 'client')),
  status               reporting.connection_status not null default 'pending',
  last_success_at      timestamptz,
  last_error           text,                   -- never include tokens in here
  token_expires_at     timestamptz,
  created_at           timestamptz not null default now(),
  unique (client_id, platform, external_account_id)
);

-- Encrypted per-client tokens. Service role ONLY: no grants to anon/authenticated.
create table reporting.connection_secrets (
  connection_id  uuid primary key references reporting.connections(id) on delete cascade,
  ciphertext     text not null,                -- base64(nonce || ciphertext || tag), AES-256-GCM
  key_version    smallint not null default 1,  -- lets us rotate PGA_ENCRYPTION_KEY
  updated_at     timestamptz not null default now()
);

-- Append-only sync log.
create table reporting.sync_runs (
  id             bigint generated always as identity primary key,
  connection_id  uuid not null references reporting.connections(id) on delete cascade,
  started_at     timestamptz not null default now(),
  finished_at    timestamptz,
  status         reporting.sync_status not null default 'running',
  date_from      date,
  date_to        date,
  rows_loaded    integer,
  error          text
);
create index on reporting.sync_runs (connection_id, started_at desc);

-- ---------------------------------------------------------------------------
-- Metrics
-- ---------------------------------------------------------------------------

-- Paid ads, all platforms in one shape. Campaign x day.
create table reporting.ad_metrics_daily (
  connection_id     uuid not null references reporting.connections(id) on delete cascade,
  client_id         uuid not null references reporting.clients(id) on delete cascade,
  platform          reporting.platform not null,
  date              date not null,
  account_id        text not null,
  campaign_id       text not null,
  campaign_name     text,
  impressions       bigint not null default 0,
  clicks            bigint not null default 0,
  cost              numeric(14,4) not null default 0,
  conversions       numeric(14,4) not null default 0,
  conversion_value  numeric(14,4) not null default 0,
  currency          char(3),
  loaded_at         timestamptz not null default now(),
  primary key (connection_id, date, campaign_id)
);
create index on reporting.ad_metrics_daily (client_id, date);

-- GA4. Channel group x day.
create table reporting.web_metrics_daily (
  connection_id     uuid not null references reporting.connections(id) on delete cascade,
  client_id         uuid not null references reporting.clients(id) on delete cascade,
  date              date not null,
  channel_group     text not null,
  sessions          bigint not null default 0,
  total_users       bigint not null default 0,
  new_users         bigint not null default 0,
  engaged_sessions  bigint not null default 0,
  key_events        numeric(14,4) not null default 0,
  revenue           numeric(14,4) not null default 0,
  loaded_at         timestamptz not null default now(),
  primary key (connection_id, date, channel_group)
);
create index on reporting.web_metrics_daily (client_id, date);

-- Search Console. Site x day (query/page detail can come later in its own table).
create table reporting.search_metrics_daily (
  connection_id  uuid not null references reporting.connections(id) on delete cascade,
  client_id      uuid not null references reporting.clients(id) on delete cascade,
  date           date not null,
  clicks         bigint not null default 0,
  impressions    bigint not null default 0,
  avg_position   numeric(8,2),
  loaded_at      timestamptz not null default now(),
  primary key (connection_id, date)
);
create index on reporting.search_metrics_daily (client_id, date);

-- Google Business Profile. Location x metric x day (GBP has many metrics, so long format).
create table reporting.local_metrics_daily (
  connection_id  uuid not null references reporting.connections(id) on delete cascade,
  client_id      uuid not null references reporting.clients(id) on delete cascade,
  date           date not null,
  location_id    text not null,
  metric         text not null,   -- e.g. CALL_CLICKS, WEBSITE_CLICKS, BUSINESS_DIRECTION_REQUESTS
  value          bigint not null default 0,
  loaded_at      timestamptz not null default now(),
  primary key (connection_id, date, location_id, metric)
);
create index on reporting.local_metrics_daily (client_id, date);

-- Organic social. Account x day.
create table reporting.social_metrics_daily (
  connection_id  uuid not null references reporting.connections(id) on delete cascade,
  client_id      uuid not null references reporting.clients(id) on delete cascade,
  platform       reporting.platform not null,
  date           date not null,
  account_id     text not null,
  followers      bigint,
  reach          bigint,
  impressions    bigint,
  engagements    bigint,
  loaded_at      timestamptz not null default now(),
  primary key (connection_id, date)
);
create index on reporting.social_metrics_daily (client_id, date);

-- ---------------------------------------------------------------------------
-- Access helpers (security definer so they can read staff/client_users
-- without recursive RLS; search_path pinned to avoid hijacking)
-- ---------------------------------------------------------------------------
create or replace function reporting.is_staff()
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select exists (select 1 from reporting.staff s where s.user_id = auth.uid());
$$;

create or replace function reporting.can_view_client(target_client uuid)
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select reporting.is_staff()
      or exists (
           select 1 from reporting.client_users cu
           where cu.user_id = auth.uid() and cu.client_id = target_client
         );
$$;

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
alter table reporting.clients              enable row level security;
alter table reporting.staff                enable row level security;
alter table reporting.client_users         enable row level security;
alter table reporting.connections          enable row level security;
alter table reporting.connection_secrets   enable row level security;
alter table reporting.sync_runs            enable row level security;
alter table reporting.ad_metrics_daily     enable row level security;
alter table reporting.web_metrics_daily    enable row level security;
alter table reporting.search_metrics_daily enable row level security;
alter table reporting.local_metrics_daily  enable row level security;
alter table reporting.social_metrics_daily enable row level security;

-- Clients: see your own; staff see and manage all.
create policy clients_select on reporting.clients
  for select to authenticated using (reporting.can_view_client(id));
create policy clients_staff_write on reporting.clients
  for all to authenticated using (reporting.is_staff()) with check (reporting.is_staff());

-- Staff list: staff only.
create policy staff_select on reporting.staff
  for select to authenticated using (reporting.is_staff());

-- Client users: see your own memberships; staff manage all.
create policy client_users_select on reporting.client_users
  for select to authenticated using (user_id = auth.uid() or reporting.is_staff());
create policy client_users_staff_write on reporting.client_users
  for all to authenticated using (reporting.is_staff()) with check (reporting.is_staff());

-- Connections: clients see their own (status only); staff manage.
create policy connections_select on reporting.connections
  for select to authenticated using (reporting.can_view_client(client_id));
create policy connections_staff_write on reporting.connections
  for all to authenticated using (reporting.is_staff()) with check (reporting.is_staff());

-- connection_secrets: NO policies for authenticated => no access. Service role bypasses RLS.

-- Sync runs: staff only.
create policy sync_runs_select on reporting.sync_runs
  for select to authenticated using (reporting.is_staff());

-- Metrics: read-only for anyone who can view the client. Writes come from the service role.
create policy ad_metrics_select on reporting.ad_metrics_daily
  for select to authenticated using (reporting.can_view_client(client_id));
create policy web_metrics_select on reporting.web_metrics_daily
  for select to authenticated using (reporting.can_view_client(client_id));
create policy search_metrics_select on reporting.search_metrics_daily
  for select to authenticated using (reporting.can_view_client(client_id));
create policy local_metrics_select on reporting.local_metrics_daily
  for select to authenticated using (reporting.can_view_client(client_id));
create policy social_metrics_select on reporting.social_metrics_daily
  for select to authenticated using (reporting.can_view_client(client_id));

-- ---------------------------------------------------------------------------
-- Grants. anon gets nothing. authenticated gets table privileges, RLS does the filtering.
-- ---------------------------------------------------------------------------
revoke all on schema reporting from public, anon;
grant usage on schema reporting to authenticated, service_role;

revoke all on all tables in schema reporting from public, anon, authenticated;
grant select on
  reporting.clients, reporting.staff, reporting.client_users, reporting.connections,
  reporting.sync_runs, reporting.ad_metrics_daily, reporting.web_metrics_daily,
  reporting.search_metrics_daily, reporting.local_metrics_daily, reporting.social_metrics_daily
  to authenticated;
grant insert, update, delete on
  reporting.clients, reporting.client_users, reporting.connections
  to authenticated;  -- still limited to staff by the policies above
-- connection_secrets deliberately not granted to authenticated.

grant all on all tables in schema reporting to service_role;
grant usage on all sequences in schema reporting to service_role;
grant execute on function reporting.is_staff(), reporting.can_view_client(uuid) to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Views for the portal. security_invoker = true so RLS applies (see CLAUDE.md rule 5).
-- ---------------------------------------------------------------------------
create view reporting.v_ad_metrics_monthly
with (security_invoker = true) as
select
  client_id,
  platform,
  date_trunc('month', date)::date as month,
  currency,
  sum(impressions)       as impressions,
  sum(clicks)            as clicks,
  sum(cost)              as cost,
  sum(conversions)       as conversions,
  sum(conversion_value)  as conversion_value,
  case when sum(clicks) > 0 then round(sum(cost) / sum(clicks), 4) end              as cpc,
  case when sum(impressions) > 0 then round(sum(clicks)::numeric / sum(impressions), 6) end as ctr,
  case when sum(conversions) > 0 then round(sum(cost) / sum(conversions), 4) end   as cost_per_conversion,
  case when sum(cost) > 0 then round(sum(conversion_value) / sum(cost), 4) end     as roas
from reporting.ad_metrics_daily
group by client_id, platform, date_trunc('month', date), currency;

grant select on reporting.v_ad_metrics_monthly to authenticated;
