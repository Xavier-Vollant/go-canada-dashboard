create table if not exists papers (
  database_id text not null default 'main',
  paper_id text,
  "DOI" text,
  title text,
  year text,
  journal text,
  publisher text,
  paper_type text,
  go_canada_status text,
  is_known_false_positive text,
  primary key (database_id, paper_id)
);

create table if not exists authors (
  database_id text not null default 'main',
  author_id text,
  author_name text not null,
  primary key (database_id, author_id)
);

create table if not exists instruments (
  database_id text not null default 'main',
  instrument_id text,
  instrument_name text not null,
  primary key (database_id, instrument_id)
);

create table if not exists sources (
  database_id text not null default 'main',
  source_id text,
  source_name text,
  source_type text,
  notes text,
  primary key (database_id, source_id)
);

create table if not exists paper_authors (
  database_id text not null default 'main',
  paper_id text,
  author_id text,
  author_order text,
  primary key (database_id, paper_id, author_id, author_order),
  foreign key (database_id, paper_id) references papers(database_id, paper_id) on delete cascade,
  foreign key (database_id, author_id) references authors(database_id, author_id) on delete cascade
);

create table if not exists paper_instruments (
  database_id text not null default 'main',
  paper_id text,
  instrument_id text,
  instrument_status text,
  primary key (database_id, paper_id, instrument_id),
  foreign key (database_id, paper_id) references papers(database_id, paper_id) on delete cascade,
  foreign key (database_id, instrument_id) references instruments(database_id, instrument_id) on delete cascade
);

create table if not exists verification (
  database_id text not null default 'main',
  paper_id text,
  instrument_id text,
  status text,
  evidence_quote text,
  checked_date text,
  notes text,
  primary key (database_id, paper_id, instrument_id),
  foreign key (database_id, paper_id) references papers(database_id, paper_id) on delete cascade,
  foreign key (database_id, instrument_id) references instruments(database_id, instrument_id) on delete cascade
);

create table if not exists paper_sources (
  database_id text not null default 'main',
  paper_id text,
  source_id text,
  primary key (database_id, paper_id, source_id),
  foreign key (database_id, paper_id) references papers(database_id, paper_id) on delete cascade,
  foreign key (database_id, source_id) references sources(database_id, source_id) on delete cascade
);

create table if not exists global_presets (
  preset_name text primary key,
  preset_json text not null,
  updated_at text
);
