-- Run once in the Supabase SQL Editor to enable isolated dashboard databases.
-- Existing rows are assigned to the main database.

alter table papers add column if not exists database_id text;
alter table authors add column if not exists database_id text;
alter table instruments add column if not exists database_id text;
alter table sources add column if not exists database_id text;
alter table paper_authors add column if not exists database_id text;
alter table paper_instruments add column if not exists database_id text;
alter table verification add column if not exists database_id text;
alter table paper_sources add column if not exists database_id text;

update papers set database_id = 'main' where database_id is null or database_id = '';
update authors set database_id = 'main' where database_id is null or database_id = '';
update instruments set database_id = 'main' where database_id is null or database_id = '';
update sources set database_id = 'main' where database_id is null or database_id = '';
update paper_authors set database_id = 'main' where database_id is null or database_id = '';
update paper_instruments set database_id = 'main' where database_id is null or database_id = '';
update verification set database_id = 'main' where database_id is null or database_id = '';
update paper_sources set database_id = 'main' where database_id is null or database_id = '';

alter table papers alter column database_id set default 'main';
alter table authors alter column database_id set default 'main';
alter table instruments alter column database_id set default 'main';
alter table sources alter column database_id set default 'main';
alter table paper_authors alter column database_id set default 'main';
alter table paper_instruments alter column database_id set default 'main';
alter table verification alter column database_id set default 'main';
alter table paper_sources alter column database_id set default 'main';

alter table papers alter column database_id set not null;
alter table authors alter column database_id set not null;
alter table instruments alter column database_id set not null;
alter table sources alter column database_id set not null;
alter table paper_authors alter column database_id set not null;
alter table paper_instruments alter column database_id set not null;
alter table verification alter column database_id set not null;
alter table paper_sources alter column database_id set not null;

alter table paper_sources drop constraint if exists paper_sources_paper_id_fkey;
alter table paper_sources drop constraint if exists paper_sources_source_id_fkey;
alter table verification drop constraint if exists verification_paper_id_fkey;
alter table verification drop constraint if exists verification_instrument_id_fkey;
alter table paper_instruments drop constraint if exists paper_instruments_paper_id_fkey;
alter table paper_instruments drop constraint if exists paper_instruments_instrument_id_fkey;
alter table paper_authors drop constraint if exists paper_authors_paper_id_fkey;
alter table paper_authors drop constraint if exists paper_authors_author_id_fkey;

alter table paper_sources drop constraint if exists paper_sources_database_paper_fkey;
alter table paper_sources drop constraint if exists paper_sources_database_source_fkey;
alter table verification drop constraint if exists verification_database_paper_fkey;
alter table verification drop constraint if exists verification_database_instrument_fkey;
alter table paper_instruments drop constraint if exists paper_instruments_database_paper_fkey;
alter table paper_instruments drop constraint if exists paper_instruments_database_instrument_fkey;
alter table paper_authors drop constraint if exists paper_authors_database_paper_fkey;
alter table paper_authors drop constraint if exists paper_authors_database_author_fkey;

alter table paper_sources drop constraint if exists paper_sources_pkey;
alter table verification drop constraint if exists verification_pkey;
alter table paper_instruments drop constraint if exists paper_instruments_pkey;
alter table paper_authors drop constraint if exists paper_authors_pkey;
alter table papers drop constraint if exists papers_pkey;
alter table sources drop constraint if exists sources_pkey;
alter table instruments drop constraint if exists instruments_pkey;
alter table authors drop constraint if exists authors_pkey;

alter table papers add constraint papers_pkey primary key (database_id, paper_id);
alter table authors add constraint authors_pkey primary key (database_id, author_id);
alter table instruments add constraint instruments_pkey primary key (database_id, instrument_id);
alter table sources add constraint sources_pkey primary key (database_id, source_id);

alter table paper_authors
  add constraint paper_authors_pkey primary key (database_id, paper_id, author_id, author_order),
  add constraint paper_authors_database_paper_fkey
    foreign key (database_id, paper_id) references papers(database_id, paper_id) on delete cascade,
  add constraint paper_authors_database_author_fkey
    foreign key (database_id, author_id) references authors(database_id, author_id) on delete cascade;

alter table paper_instruments
  add constraint paper_instruments_pkey primary key (database_id, paper_id, instrument_id),
  add constraint paper_instruments_database_paper_fkey
    foreign key (database_id, paper_id) references papers(database_id, paper_id) on delete cascade,
  add constraint paper_instruments_database_instrument_fkey
    foreign key (database_id, instrument_id) references instruments(database_id, instrument_id) on delete cascade;

alter table verification
  add constraint verification_pkey primary key (database_id, paper_id, instrument_id),
  add constraint verification_database_paper_fkey
    foreign key (database_id, paper_id) references papers(database_id, paper_id) on delete cascade,
  add constraint verification_database_instrument_fkey
    foreign key (database_id, instrument_id) references instruments(database_id, instrument_id) on delete cascade;

alter table paper_sources
  add constraint paper_sources_pkey primary key (database_id, paper_id, source_id),
  add constraint paper_sources_database_paper_fkey
    foreign key (database_id, paper_id) references papers(database_id, paper_id) on delete cascade,
  add constraint paper_sources_database_source_fkey
    foreign key (database_id, source_id) references sources(database_id, source_id) on delete cascade;
