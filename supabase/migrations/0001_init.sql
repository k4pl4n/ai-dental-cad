-- AI Dental CAD — initial schema (SPEC §8, §9)
-- Applied with: supabase db push

create table if not exists cases (
  case_id    text primary key,
  reference  text not null,
  user_id    text not null default 'dev',
  status     text not null,
  payload    jsonb not null,
  updated_at timestamptz not null default now()
);

create index if not exists cases_user_idx on cases (user_id, updated_at desc);

-- Audit log: every AI decision, override, download. Regulatory evidence pack (SPEC §12).
create table if not exists audit (
  id        bigserial primary key,
  case_id   text not null,
  event     text not null,
  detail    text not null default '',
  timestamp timestamptz not null default now()
);

create index if not exists audit_case_idx on audit (case_id, timestamp);

-- Corrections: every user override — future training data (SPEC §8).
create table if not exists corrections (
  id              bigserial primary key,
  case_id         text not null,
  correction_type text not null,          -- perception | plan | design
  tooth_number    integer,
  original_value  text not null,
  corrected_value text not null,
  timestamp       timestamptz not null default now()
);

create index if not exists corrections_case_idx on corrections (case_id);

-- RLS: the backend connects with the service role (bypasses RLS).
-- Enable RLS so anon/browser keys can't read anything directly.
alter table cases enable row level security;
alter table audit enable row level security;
alter table corrections enable row level security;
