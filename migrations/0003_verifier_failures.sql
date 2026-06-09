-- Verifier failure log (Law-5 gate): one row per Violation, see CITATION_CONTRACT.md

create table if not exists claim_failures (
    failure_id   uuid primary key default gen_random_uuid(),
    trace_id     text not null,
    check_name   text not null,
    locus        text not null,
    detail       text not null,
    created_at   timestamptz not null default now()
);
create index if not exists claim_failures_trace_idx on claim_failures (trace_id);
