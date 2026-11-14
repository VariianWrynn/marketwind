-- G2.1: cross-report storage + I10 time_window field.
-- pipeline_runs persists each report's verified-claim set for I11 comparison.
-- claims.time_window carries the temporal scope (e.g. "2026-Q1", "2026-05-27").

alter table claims add column time_window text;

create table if not exists pipeline_runs (
    run_id uuid primary key default gen_random_uuid(),
    report_id uuid not null,
    trading_date date not null,
    job_id text not null,
    claim_ids uuid [] not null default '{}',
    created_at timestamptz not null default now()
);

create index if not exists pipeline_runs_trading_date_idx on pipeline_runs (trading_date);
