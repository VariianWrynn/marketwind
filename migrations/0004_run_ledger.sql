-- Run ledger (P2b durable operation): double-publish guard keyed on (job_id, trading_date)

create table if not exists run_ledger (
    ledger_id    uuid        primary key default gen_random_uuid(),
    job_id       text        not null,
    trading_date date        not null,
    status       text        not null,
    trace_id     text        not null,
    detail       text,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    unique (job_id, trading_date)
);
create index if not exists run_ledger_trading_date_idx on run_ledger (trading_date);
