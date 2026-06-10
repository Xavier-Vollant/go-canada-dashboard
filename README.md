# GO-Canada Publication Dashboard

A Streamlit dashboard for exploring the GO-Canada publication database.

The dashboard lets users search, filter, graph, and export papers by instrument,
year, author, DOI, journal, publisher, verification status, and other metadata.
It also includes shared presets for common instrument/year paper lists.

## Use The Dashboard

Open the deployed Streamlit app and use the sidebar filters to narrow the paper
database. The main pages provide:

- `Dashboard`: summary metrics and overview tables.
- `Filter + Paper List`: searchable paper list with links to papers.
- `Graphs`: visual summaries of the current filtered result.
- `Data Quality`: missing metadata and verification checks.
- `Export`: CSV exports of the current view.

Admins can sign in from the app to update papers, metadata, verification status,
and shared presets.

## Backend Database

The online dashboard is connected to a backend database so approved edits can be
saved directly from the website. Local CSV files in `data/` are kept in the repo
as a snapshot/fallback version of the database.

## Run Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```
