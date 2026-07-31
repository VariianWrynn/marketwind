-- I12: derived_metric claims must carry a methodology (CITATION_CONTRACT §4 I12, D-12).
-- Migrations are versioned (schema_migrations); 0006 runs exactly once.
alter table claims add column category text not null default 'quantitative';
alter table claims add column methodology text;
alter table claims add constraint claims_category_enum check (
    category in ('quantitative', 'temporal', 'comparative', 'attribution',
                 'causal', 'quoted_inference', 'freshness', 'derived_metric', 'correction')
);
alter table claims add constraint claims_derived_needs_methodology check (
    category <> 'derived_metric' or methodology is not null
);
