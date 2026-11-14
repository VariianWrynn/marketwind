-- G2.3: claim state machine.
-- Claims gain a state field (drafted/verified/failed/rewritten) and retry_count.
-- Max retry = 1 (D-9). Failure-rate thresholds: 10% warn / 25% halt (D-4).

alter table claims add column state text not null default 'verified';
alter table claims add column retry_count int not null default 0;
