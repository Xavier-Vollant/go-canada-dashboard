create table if not exists papers (
  paper_id text primary key,
  "DOI" text,
  title text,
  year text,
  journal text,
  publisher text,
  paper_type text,
  go_canada_status text,
  is_known_false_positive text
);

create table if not exists authors (
  author_id text primary key,
  author_name text not null
);

create table if not exists instruments (
  instrument_id text primary key,
  instrument_name text not null
);

create table if not exists sources (
  source_id text primary key,
  source_name text,
  source_type text,
  notes text
);

create table if not exists paper_authors (
  paper_id text references papers(paper_id) on delete cascade,
  author_id text references authors(author_id) on delete cascade,
  author_order text,
  primary key (paper_id, author_id, author_order)
);

create table if not exists paper_instruments (
  paper_id text references papers(paper_id) on delete cascade,
  instrument_id text references instruments(instrument_id) on delete cascade,
  instrument_status text,
  primary key (paper_id, instrument_id)
);

create table if not exists verification (
  paper_id text references papers(paper_id) on delete cascade,
  instrument_id text references instruments(instrument_id) on delete cascade,
  status text,
  evidence_quote text,
  checked_date text,
  notes text,
  primary key (paper_id, instrument_id)
);

create table if not exists paper_sources (
  paper_id text references papers(paper_id) on delete cascade,
  source_id text references sources(source_id) on delete cascade,
  primary key (paper_id, source_id)
);

create table if not exists global_presets (
  preset_name text primary key,
  preset_json text not null,
  updated_at text
);
