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

Read-only hosted mode keeps filtering, graphs, data quality checks, exports, and session-only exclusions enabled, but disables features that try to permanently write CSV changes online.

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

The DOI review database is loaded from:

- `data/review/paper_verification_summary.csv`
- `data/review/paper_instrument_verification_status.csv`

These files power the **Review Database** page in the Streamlit app.

## Main features

- Advanced filtering by instrument, author, year range, publisher, journal, paper type, verification status, GO-Canada status, and source.
- Toggle to remove known false positives.
- Dynamic paper list.
- DOI-based review database for verified, partially verified, and unverified papers.
- Live statistics for the current filtered subset.
- Estimated false-positive rate and estimated clean count.
- Plotly graphs based on current filters.
- CSV export of the current filtered view.
- Optional `filter_summary.csv` export.
- Saved views stored as JSON files in `presets/`.
- Bulk CSV import and manual paper entry for local editing.
- Optional hosted read-only mode for online deployment.
