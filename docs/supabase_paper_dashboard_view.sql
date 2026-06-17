-- Fast one-row-per-paper dashboard view for normal browsing/filtering.
--
-- Run this once in the Supabase SQL Editor after the multi-database migration.
-- The app filters this view with database_id = 'main', 'library', or 'john'.

create index if not exists papers_database_id_idx
  on papers(database_id);

create index if not exists paper_authors_database_paper_idx
  on paper_authors(database_id, paper_id);

create index if not exists paper_instruments_database_paper_idx
  on paper_instruments(database_id, paper_id);

create index if not exists verification_database_paper_idx
  on verification(database_id, paper_id);

create index if not exists paper_sources_database_paper_idx
  on paper_sources(database_id, paper_id);

create or replace view paper_dashboard_view as
with paper_author_rows as (
  select
    pa.database_id,
    pa.paper_id,
    a.author_name,
    case
      when pa.author_order ~ '^[0-9]+$' then pa.author_order::integer
      else null
    end as author_sort
  from paper_authors pa
  join authors a
    on a.database_id = pa.database_id
   and a.author_id = pa.author_id
),
author_rows as (
  select
    database_id,
    paper_id,
    string_agg(nullif(author_name, ''), '; ' order by author_sort nulls last, author_name) as authors,
    split_part(
      string_agg(nullif(author_name, ''), '; ' order by author_sort nulls last, author_name),
      '; ',
      1
    ) as first_author
  from paper_author_rows
  group by database_id, paper_id
),
instrument_rows as (
  select
    pi.database_id,
    pi.paper_id,
    string_agg(nullif(i.instrument_name, ''), '; ' order by i.instrument_name) as instruments,
    string_agg(nullif(pi.instrument_status, ''), '; ' order by i.instrument_name) as instrument_statuses,
    string_agg(
      nullif(i.instrument_name, '') || ': ' || coalesce(nullif(v.status, ''), 'unchecked'),
      '; '
      order by i.instrument_name
    ) as instrument_verification_pairs,
    string_agg(
      coalesce(nullif(v.status, ''), 'unchecked'),
      '; '
      order by i.instrument_name
    ) as all_verification_statuses,
    case
      when bool_or(coalesce(nullif(v.status, ''), 'unchecked') in (
        'verified_true',
        'true',
        'uses',
        'uses_data',
        'definitely_uses',
        'definitely_uses_data',
        'uses_go_canada_data',
        'yes'
      )) then 'verified_true'
      when bool_or(coalesce(nullif(v.status, ''), 'unchecked') in (
        'verified_false',
        'false',
        'known_false_positive',
        'does_not_use',
        'definitely_does_not_use',
        'definitely_does_not_use_data',
        'mentioned_only',
        'reference_only',
        'no'
      )) then 'verified_false'
      when bool_or(coalesce(nullif(v.status, ''), 'unchecked') in (
        'unsure',
        'maybe',
        'uncertain',
        'cant_find_paper',
        'can''t_find_paper',
        'not_accessible',
        'doi_not_working'
      )) then 'unsure'
      else 'unchecked'
    end as verification_status,
    string_agg(distinct nullif(v.evidence_quote, ''), ' | ') as evidence_quote,
    string_agg(distinct nullif(v.checked_date, ''), ' | ') as checked_date,
    string_agg(distinct nullif(v.notes, ''), ' | ') as notes
  from paper_instruments pi
  join instruments i
    on i.database_id = pi.database_id
   and i.instrument_id = pi.instrument_id
  left join verification v
    on v.database_id = pi.database_id
   and v.paper_id = pi.paper_id
   and v.instrument_id = pi.instrument_id
  group by pi.database_id, pi.paper_id
),
source_rows as (
  select
    ps.database_id,
    ps.paper_id,
    string_agg(nullif(s.source_name, ''), '; ' order by s.source_name) as sources,
    string_agg(nullif(s.source_type, ''), '; ' order by s.source_name) as source_types
  from paper_sources ps
  join sources s
    on s.database_id = ps.database_id
   and s.source_id = ps.source_id
  group by ps.database_id, ps.paper_id
)
select
  p.database_id,
  p.paper_id,
  p."DOI",
  p.title,
  p.year,
  p.journal,
  p.publisher,
  p.paper_type,
  p.go_canada_status,
  p.is_known_false_positive,
  coalesce(ar.authors, '') as authors,
  coalesce(ar.authors, '') as display_authors,
  coalesce(ar.first_author, '') as first_author,
  coalesce(ir.instruments, '') as instruments,
  coalesce(ir.instruments, '') as display_instruments,
  coalesce(ir.instrument_statuses, '') as instrument_statuses,
  coalesce(ir.all_verification_statuses, '') as all_verification_statuses,
  coalesce(ir.instrument_verification_pairs, '') as instrument_verification_pairs,
  coalesce(ir.instrument_verification_pairs, '') as display_instrument_verification,
  coalesce(ir.verification_status, 'unchecked') as verification_status,
  coalesce(ir.evidence_quote, '') as evidence_quote,
  coalesce(ir.checked_date, '') as checked_date,
  coalesce(ir.notes, '') as notes,
  coalesce(sr.sources, '') as sources,
  coalesce(sr.sources, '') as display_sources,
  coalesce(sr.source_types, '') as source_types
from papers p
left join author_rows ar
  on ar.database_id = p.database_id
 and ar.paper_id = p.paper_id
left join instrument_rows ir
  on ir.database_id = p.database_id
 and ir.paper_id = p.paper_id
left join source_rows sr
  on sr.database_id = p.database_id
 and sr.paper_id = p.paper_id;
