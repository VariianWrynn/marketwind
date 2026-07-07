-- Rejected-draft capture: on a verify_fail the offending draft is otherwise
-- discarded; persist it (keyed by trace_id, joins claim_failures) so a rejection
-- is diagnosable after the fact.

create table if not exists rejected_drafts (
    rejection_id uuid primary key default gen_random_uuid(),
    trace_id     text not null,
    draft_json   jsonb not null,
    created_at   timestamptz not null default now()
);
create index if not exists rejected_drafts_trace_idx on rejected_drafts (trace_id);
