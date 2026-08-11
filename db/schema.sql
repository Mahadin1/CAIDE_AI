-- DataScope database schema
-- Run this in the Supabase SQL editor against the `public` schema.
-- It is idempotent: safe to run multiple times.

-- ============================================================
-- Extensions
-- ============================================================
create extension if not exists pgcrypto;

-- ============================================================
-- profiles: extends Supabase auth.users
-- ============================================================
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  name text,
  plan text not null default 'free' check (plan in ('free', 'starter', 'pro', 'scale')),
  credits int not null default 0,
  qa_credits int not null default 0,
  reports_this_month int not null default 0,
  created_at timestamptz not null default now()
);

-- ============================================================
-- uploads: one row per uploaded file a user submits.
-- This row also serves as the async analysis *job record*.
-- ============================================================
create table if not exists public.uploads (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.profiles(id) on delete cascade not null,
  filename text not null,
  storage_path text not null,
  status text not null default 'pending' check (status in ('pending', 'ready', 'processing', 'done', 'failed')),
  -- job orchestration / progress
  stage text not null default 'queued',
  stage_label text,
  progress int not null default 5,
  attempts int not null default 0,
  error_message text,
  -- file / data metadata filled by the worker
  file_size_bytes bigint,
  source_format text,
  detected_encoding text,
  row_estimate bigint,
  column_count int,
  analysis_mode text check (analysis_mode in ('full', 'sample', 'truncated')),
  analysis_plan_json jsonb,
  overrides_json jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- ============================================================
-- reports: the agent's output for an upload
-- ============================================================
create table if not exists public.reports (
  id uuid primary key default gen_random_uuid(),
  upload_id uuid references public.uploads(id) on delete cascade not null,
  summary_json jsonb not null,
  narrative text not null,
  column_glossary jsonb,
  -- adaptive-planning / large-file provenance (mirrors uploads for convenience)
  analysis_plan_json jsonb,
  overrides_json jsonb,
  sample_info_json jsonb,
  analysis_mode text,
  source_format text,
  export_html_url text,
  export_pdf_url text,
  cleaned_data_url text,
  created_at timestamptz not null default now()
);

-- ============================================================
-- subscriptions: Paddle subscription state per user
-- ============================================================
create table if not exists public.subscriptions (
  user_id uuid primary key references public.profiles(id) on delete cascade,
  paddle_subscription_id text,
  status text not null default 'inactive' check (status in ('active', 'inactive', 'cancelled')),
  updated_at timestamptz not null default now()
);

-- ============================================================
-- skill_runs: one row per user-initiated skill execution (#8-#15).
-- A run belongs to the report it was attached to and to its owner.
-- result_json holds the deterministic output (models are re-fit
-- deterministically, never persisted).
-- ============================================================
create table if not exists public.skill_runs (
  id uuid primary key default gen_random_uuid(),
  report_id uuid references public.reports(id) on delete cascade not null,
  user_id uuid references public.profiles(id) on delete cascade not null,
  skill text not null,
  params_json jsonb,
  status text not null default 'running' check (status in ('running', 'done', 'failed', 'skipped')),
  result_json jsonb,
  credit_cost int not null default 0,
  created_at timestamptz not null default now()
);

-- ============================================================
-- qa_turns: persisted report-Q&A turns (#8). Separate, cheaper meter.
-- ============================================================
create table if not exists public.qa_turns (
  id uuid primary key default gen_random_uuid(),
  report_id uuid references public.reports(id) on delete cascade not null,
  user_id uuid references public.profiles(id) on delete cascade not null,
  question text not null,
  answer text not null,
  answered boolean not null default true,
  model text,
  created_at timestamptz not null default now()
);

-- ============================================================
-- Indexes
-- ============================================================
create index if not exists uploads_user_id_idx on public.uploads(user_id);
create index if not exists uploads_status_idx on public.uploads(status);
create index if not exists reports_upload_id_idx on public.reports(upload_id);
create index if not exists profiles_plan_idx on public.profiles(plan);
create index if not exists skill_runs_report_idx on public.skill_runs(report_id);
create index if not exists skill_runs_user_idx on public.skill_runs(user_id);
create index if not exists qa_turns_report_idx on public.qa_turns(report_id);

-- ============================================================
-- Row Level Security
-- ============================================================
alter table public.profiles enable row level security;
alter table public.uploads enable row level security;
alter table public.reports enable row level security;
alter table public.subscriptions enable row level security;
alter table public.skill_runs enable row level security;
alter table public.qa_turns enable row level security;

-- profiles: a user can read/update their own row; insert handled by trigger
drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own"
  on public.profiles for select
  using (id = auth.uid());

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
  on public.profiles for update
  using (id = auth.uid());

drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own"
  on public.profiles for insert
  with check (id = auth.uid());

-- uploads: a user can manage only their own uploads
drop policy if exists "uploads_select_own" on public.uploads;
create policy "uploads_select_own"
  on public.uploads for select
  using (user_id = auth.uid());

drop policy if exists "uploads_insert_own" on public.uploads;
create policy "uploads_insert_own"
  on public.uploads for insert
  with check (user_id = auth.uid());

drop policy if exists "uploads_update_own" on public.uploads;
create policy "uploads_update_own"
  on public.uploads for update
  using (user_id = auth.uid());

-- reports: users can read reports whose upload they own.
-- Because reports only references upload_id, join through uploads.
drop policy if exists "reports_select_own" on public.reports;
create policy "reports_select_own"
  on public.reports for select
  using (
    exists (
      select 1 from public.uploads u
      where u.id = reports.upload_id
        and u.user_id = auth.uid()
    )
  );

drop policy if exists "reports_insert_own" on public.reports;
create policy "reports_insert_own"
  on public.reports for insert
  with check (
    exists (
      select 1 from public.uploads u
      where u.id = reports.upload_id
        and u.user_id = auth.uid()
    )
  );

-- subscriptions: a user can read/update only their own subscription row
drop policy if exists "subscriptions_select_own" on public.subscriptions;
create policy "subscriptions_select_own"
  on public.subscriptions for select
  using (user_id = auth.uid());

drop policy if exists "subscriptions_insert_own" on public.subscriptions;
create policy "subscriptions_insert_own"
  on public.subscriptions for insert
  with check (user_id = auth.uid());

drop policy if exists "subscriptions_update_own" on public.subscriptions;
create policy "subscriptions_update_own"
  on public.subscriptions for update
  using (user_id = auth.uid());

-- skill_runs: users manage only their own runs
drop policy if exists "skill_runs_select_own" on public.skill_runs;
create policy "skill_runs_select_own"
  on public.skill_runs for select
  using (user_id = auth.uid());

drop policy if exists "skill_runs_insert_own" on public.skill_runs;
create policy "skill_runs_insert_own"
  on public.skill_runs for insert
  with check (user_id = auth.uid());

drop policy if exists "skill_runs_update_own" on public.skill_runs;
create policy "skill_runs_update_own"
  on public.skill_runs for update
  using (user_id = auth.uid());

-- qa_turns: users manage only their own turns
drop policy if exists "qa_turns_select_own" on public.qa_turns;
create policy "qa_turns_select_own"
  on public.qa_turns for select
  using (user_id = auth.uid());

drop policy if exists "qa_turns_insert_own" on public.qa_turns;
create policy "qa_turns_insert_own"
  on public.qa_turns for insert
  with check (user_id = auth.uid());

drop policy if exists "qa_turns_delete_own" on public.qa_turns;
create policy "qa_turns_delete_own"
  on public.qa_turns for delete
  using (user_id = auth.uid());

-- ============================================================
-- Trigger: create a profile row automatically on signup
-- ============================================================
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, email, name, plan, credits, reports_this_month)
  values (
    new.id,
    coalesce(new.email, ''),
    nullif(new.raw_user_meta_data ->> 'name', ''),
    'free',
    3,
    0
  )
  on conflict (id) do nothing;
  insert into public.subscriptions (user_id, status)
  values (new.id, 'inactive')
  on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ============================================================
-- Report counter increments (called by backend after a report is saved)
-- ============================================================
create or replace function public.increment_reports_used(uid uuid)
returns void
language plpgsql
security definer set search_path = public
as $$
begin
  update public.profiles
  set reports_this_month = reports_this_month + 1
  where id = uid;
end;
$$;

-- ============================================================
-- Credits: one analysis consumes one credit. Never below zero.
-- ============================================================
create or replace function public.decrement_credit(uid uuid)
returns void
language plpgsql
security definer set search_path = public
as $$
begin
  update public.profiles
  set credits = greatest(credits - 1, 0)
  where id = uid;
end;
$$;

-- Decrement a variable amount (used by user-initiated skills).
create or replace function public.decrement_credits(uid uuid, amount int)
returns void
language plpgsql
security definer set search_path = public
as $$
begin
  update public.profiles
  set credits = greatest(credits - coalesce(amount, 0), 0)
  where id = uid;
end;
$$;

-- Decrement the separate Q&A meter. Never below zero.
create or replace function public.decrement_qa_credit(uid uuid)
returns void
language plpgsql
security definer set search_path = public
as $$
begin
  update public.profiles
  set qa_credits = greatest(qa_credits - 1, 0)
  where id = uid;
end;
$$;

-- ============================================================
-- Monthly credit reset (called by cron / scheduled function)
-- ============================================================
create or replace function public.reset_monthly_credits()
returns void
language plpgsql
security definer set search_path = public
as $$
begin
  update public.profiles
  set credits = case plan
        when 'free' then 3
        when 'starter' then 30
        when 'pro' then 100
        when 'scale' then 300
        else 0
      end,
      qa_credits = case plan
        when 'pro' then 300
        when 'scale' then 1000
        else 0
      end,
      reports_this_month = 0;
end;
$$;

-- ============================================================
-- Plan & credits migration for existing databases.
-- The CREATE TABLE above only applies to fresh databases; existing rows and
-- CHECK constraints were created with the old (free, pro) plan list and no
-- credits column, so migrate them explicitly. Idempotent.
-- ============================================================
alter table public.profiles drop constraint if exists profiles_plan_check;
alter table public.profiles
  add constraint profiles_plan_check check (plan in ('free', 'starter', 'pro', 'scale'));

alter table public.uploads drop constraint if exists uploads_status_check;
alter table public.uploads
  add constraint uploads_status_check
  check (status in ('pending', 'ready', 'processing', 'done', 'failed'));

alter table public.profiles add column if not exists credits int not null default 0;
alter table public.profiles add column if not exists qa_credits int not null default 0;

-- Backfill credits for users who existed before credits existed.
update public.profiles
set credits = case plan
      when 'free' then 3
      when 'starter' then 30
      when 'pro' then 100
      when 'scale' then 300
      else 0
    end
where credits = 0;

-- Backfill qa credits for pro/scale users.
update public.profiles
set qa_credits = case plan
      when 'pro' then 300
      when 'scale' then 1000
      else 0
    end
where qa_credits = 0;

-- ============================================================
-- Idempotent upgrades for databases created before the adaptive
-- platform redesign. Safe to run; no-ops when columns exist.
-- ============================================================
alter table public.uploads add column if not exists stage text not null default 'queued';alter table public.uploads add column if not exists stage_label text;
alter table public.uploads add column if not exists progress int not null default 5;
alter table public.uploads add column if not exists attempts int not null default 0;
alter table public.uploads add column if not exists error_message text;
alter table public.uploads add column if not exists file_size_bytes bigint;
alter table public.uploads add column if not exists source_format text;
alter table public.uploads add column if not exists detected_encoding text;
alter table public.uploads add column if not exists row_estimate bigint;
alter table public.uploads add column if not exists column_count int;
alter table public.uploads add column if not exists analysis_mode text;
alter table public.uploads add column if not exists analysis_plan_json jsonb;
alter table public.uploads add column if not exists overrides_json jsonb;
alter table public.uploads add column if not exists updated_at timestamptz not null default now();

alter table public.reports add column if not exists analysis_plan_json jsonb;
alter table public.reports add column if not exists overrides_json jsonb;
alter table public.reports add column if not exists sample_info_json jsonb;
alter table public.reports add column if not exists analysis_mode text;
alter table public.reports add column if not exists source_format text;
alter table public.reports add column if not exists export_html_url text;
alter table public.reports add column if not exists export_pdf_url text;
alter table public.reports add column if not exists cleaned_data_url text;
alter table public.reports add column if not exists column_glossary jsonb;

-- ============================================================
-- Storage buckets
-- ============================================================
insert into storage.buckets (id, name, public)
values ('uploads', 'uploads', false)
on conflict (id) do nothing;

insert into storage.buckets (id, name, public)
values ('reports', 'reports', false)
on conflict (id) do nothing;

-- Storage policy: users can only touch their own paths (uploads/<user_id>/...)
-- storage.foldername returns the folder path as an array (indexed from 1), so
-- [1] is the leading "uploads" folder and [2] is the owning user id.
drop policy if exists "uploads_read_own" on storage.objects;
create policy "uploads_read_own"
  on storage.objects for select
  using (bucket_id = 'uploads' and (storage.foldername(name))[2] = auth.uid()::text);

drop policy if exists "uploads_insert_own" on storage.objects;
create policy "uploads_insert_own"
  on storage.objects for insert
  with check (bucket_id = 'uploads' and (storage.foldername(name))[2] = auth.uid()::text);

drop policy if exists "uploads_update_own" on storage.objects;
create policy "uploads_update_own"
  on storage.objects for update
  using (bucket_id = 'uploads' and (storage.foldername(name))[2] = auth.uid()::text);

drop policy if exists "uploads_delete_own" on storage.objects;
create policy "uploads_delete_own"
  on storage.objects for delete
  using (bucket_id = 'uploads' and (storage.foldername(name))[2] = auth.uid()::text);

-- Storage policy: generated PDFs live under reports/<user_id>/... and are private.
drop policy if exists "reports_read_own" on storage.objects;
create policy "reports_read_own"
  on storage.objects for select
  using (bucket_id = 'reports' and (storage.foldername(name))[2] = auth.uid()::text);

drop policy if exists "reports_insert_own" on storage.objects;
create policy "reports_insert_own"
  on storage.objects for insert
  with check (bucket_id = 'reports' and (storage.foldername(name))[2] = auth.uid()::text);

-- ============================================================
-- Service role helpers (used by the backend via service key):
-- grant the service role bypass on all policies so it can read any row.
-- ============================================================
grant usage on schema public to service_role;
grant all on all tables in schema public to service_role;
grant all on all sequences in schema public to service_role;
