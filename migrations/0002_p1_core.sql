-- P1 core data model: a subset of CITATION_CONTRACT.md §3.
-- Scout (P1a) populates sources + quotes; Writer (P1b) populates claims + sentences.

create table if not exists sources (
    source_id uuid primary key default gen_random_uuid(),
    url text not null unique,
    domain text not null,
    byline text,
    publish_ts timestamptz not null,
    is_primary boolean not null default false,
    raw_content text not null,
    ingested_at timestamptz not null default now()
);

create table if not exists quotes (
    quote_id uuid primary key default gen_random_uuid(),
    source_id uuid not null references sources (source_id) on delete cascade,
    text text not null,
    span_start integer not null,
    span_end integer not null,
    context_before text,
    context_after text,
    quote_type text not null default 'factual',
    is_quantitative boolean not null default false,
    attached_primary_url text,
    constraint quotes_span_order check (span_end > span_start),
    constraint quotes_quote_type check (
        quote_type in ('factual', 'quoted_inference', 'data')
    )
);

create index if not exists quotes_source_id_idx on quotes (source_id);

create table if not exists claims (
    claim_id uuid primary key default gen_random_uuid(),
    statement text not null,
    quote_ids uuid [] not null,
    created_at timestamptz not null default now()
);

create table if not exists sentences (
    sentence_id uuid primary key default gen_random_uuid(),
    report_id uuid not null,
    claim_ids uuid [] not null default '{}',
    source_ids uuid [] not null default '{}',
    rendered_text text not null,
    sentence_type text not null default 'factual',
    position integer not null
);
