-- Scout fetch/lookup failure log. Deliberately separate from claim_failures:
-- that table is the Verifier's rejection log (reviewed weekly, keyed by
-- trace_id); these rows record that a source was unreachable, so a systemic
-- outage is distinguishable from a genuinely quiet news day.

create table if not exists fetch_failures (
    failure_id   uuid primary key default gen_random_uuid(),
    stage        text not null,
    locus        text not null,
    detail       text not null,
    created_at   timestamptz not null default now()
);
create index if not exists fetch_failures_created_idx on fetch_failures (created_at);
