# GO-Canada Publication Analytics Dashboard MVP

This is a Streamlit dashboard for filtering and analyzing an existing GO-Canada publication database.
It does not search the web.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
streamlit run app.py
```

## Deploy Online

This project is ready for Streamlit Community Cloud. See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the full step-by-step deployment workflow.

For a hosted public version, set this Streamlit Cloud secret:

```toml
GO_CANADA_READ_ONLY = "true"
```

Read-only hosted mode keeps filtering, graphs, data quality checks, exports, and session-only exclusions enabled. If Supabase is configured, password-protected admins can still edit the online database from the hosted app.

For password-protected online editing, add these Streamlit Cloud secrets:

```toml
GO_CANADA_READ_ONLY = "true"
GO_CANADA_ADMIN_PASSWORD = "choose-a-password"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"
```

Create the Supabase tables with [`docs/supabase_schema.sql`](docs/supabase_schema.sql), then use the app's **Admin Editor** page to seed Supabase from the repository CSVs.

## CSV structure

The dashboard loads the normalized CSV database in the `data/` folder:

- `papers.csv`
- `authors.csv`
- `paper_authors.csv`
- `instruments.csv`
- `paper_instruments.csv`
- `verification.csv`
- `sources.csv`
- `paper_sources.csv`

The included CSV files are generated from the GO-Canada DOI post-processing workflow.
To rebuild them after updating the source exports, run:

```bash
python3 scripts/build_dashboard_data_from_exports.py \
  --import-csv ../output/dashboard_import_ready_standardized.csv \
  --review-csv data/review/paper_instrument_verification_status.csv \
  --data-dir data
```

The static DOI review exports are kept in:

- `data/review/paper_verification_summary.csv`
- `data/review/paper_instrument_verification_status.csv`

These are historical exports from the review workflow. The live dashboard and admin editor use the normalized database tables instead.

## Main features

- Advanced filtering by instrument, author, year range, publisher, journal, paper type, verification status, GO-Canada status, and source.
- Sidebar search across title, DOI, authors, instruments, journal, publisher, and paper type.
- Toggle to remove known false positives.
- Dynamic paper list.
- Per-instrument verification status display for multi-instrument papers.
- Live statistics for the current filtered subset.
- Estimated false-positive rate and estimated clean count.
- Plotly graphs based on current filters.
- CSV export of the current filtered view.
- Optional `filter_summary.csv` export.
- Shared presets that admins can create, update, and delete for everyone.
- Bulk CSV import and manual paper entry for local editing.
- Password-protected online editing through Supabase, including paper metadata, verification status, and shared presets.
- Optional hosted read-only mode for public deployment.
