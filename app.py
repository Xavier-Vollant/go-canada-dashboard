"""
GO-Canada Publication Analytics Dashboard - MVP

This app is meant to analyze an existing GO-Canada publication database.
It does NOT search the web. It only loads local CSV files, lets the user filter
those files, and updates tables, statistics, graphs, and CSV exports.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import json
import os
from itertools import combinations
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import networkx as nx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

APP_TITLE = "GO-Canada Publication Analytics Dashboard"
DATA_DIR = Path("data")
REVIEW_DIR = DATA_DIR / "review"
PRESET_DIR = Path("presets")


def is_enabled_flag(value: Any) -> bool:
    """Parse an environment or secrets flag."""
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def read_only_mode_enabled() -> bool:
    """Read hosted read-only mode from environment variables or Streamlit secrets."""
    if is_enabled_flag(os.environ.get("GO_CANADA_READ_ONLY")):
        return True
    try:
        return is_enabled_flag(st.secrets.get("GO_CANADA_READ_ONLY", ""))
    except Exception:
        return False


def get_config_value(name: str, default: str = "") -> str:
    """Read config from environment variables or Streamlit secrets."""
    value = os.environ.get(name)
    if value is not None:
        return str(value).strip()
    try:
        return str(st.secrets.get(name, default)).strip()
    except Exception:
        return default


def admin_password_configured() -> bool:
    """Return whether an admin password has been configured."""
    return bool(get_config_value("GO_CANADA_ADMIN_PASSWORD"))


def admin_is_authenticated() -> bool:
    """Return whether the current Streamlit session passed admin auth."""
    return bool(st.session_state.get("admin_authenticated"))


def supabase_config() -> tuple[str, str] | None:
    """Return Supabase REST config if online persistence is configured."""
    url = get_config_value("SUPABASE_URL").rstrip("/")
    key = get_config_value("SUPABASE_SERVICE_ROLE_KEY") or get_config_value("SUPABASE_ANON_KEY")
    if not url or not key:
        return None
    return url, key


def database_backend_label() -> str:
    """Return a user-facing database backend label."""
    return "Supabase" if supabase_config() else "CSV files"


READ_ONLY_MODE = read_only_mode_enabled()

if not READ_ONLY_MODE:
    PRESET_DIR.mkdir(exist_ok=True)

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "papers": [
        "paper_id",
        "DOI",
        "title",
        "year",
        "journal",
        "publisher",
        "paper_type",
        "go_canada_status",
        "is_known_false_positive",
    ],
    "authors": ["author_id", "author_name"],
    "paper_authors": ["paper_id", "author_id", "author_order"],
    "instruments": ["instrument_id", "instrument_name"],
    "paper_instruments": ["paper_id", "instrument_id", "instrument_status"],
    "verification": [
        "paper_id",
        "instrument_id",
        "status",
        "evidence_quote",
        "checked_date",
        "notes",
    ],
    "sources": ["source_id", "source_name", "source_type", "notes"],
    "paper_sources": ["paper_id", "source_id"],
}

CSV_PATHS = {name: DATA_DIR / f"{name}.csv" for name in REQUIRED_COLUMNS}
SUPABASE_PAGE_SIZE = 1000
SUPABASE_INSERT_CHUNK_SIZE = 500

TABLE_DELETE_FILTER_COLUMN = {
    "papers": "paper_id",
    "authors": "author_id",
    "paper_authors": "paper_id",
    "instruments": "instrument_id",
    "paper_instruments": "paper_id",
    "verification": "paper_id",
    "sources": "source_id",
    "paper_sources": "paper_id",
}

TABLE_PRIMARY_KEY_COLUMNS = {
    "papers": ["paper_id"],
    "authors": ["author_id"],
    "paper_authors": ["paper_id", "author_id", "author_order"],
    "instruments": ["instrument_id"],
    "paper_instruments": ["paper_id", "instrument_id"],
    "verification": ["paper_id", "instrument_id"],
    "sources": ["source_id"],
    "paper_sources": ["paper_id", "source_id"],
}

REVIEW_SUMMARY_COLUMNS = [
    "DOI",
    "title",
    "year",
    "journal",
    "publisher",
    "paper_type",
    "authors",
    "instruments",
    "paper_review_status",
    "reviewed_instruments",
    "total_instruments",
]

REVIEW_DETAIL_COLUMNS = [
    "DOI",
    "title",
    "year",
    "journal",
    "publisher",
    "paper_type",
    "authors",
    "instrument",
    "all_instruments_on_paper",
    "instrument_status",
    "review_status",
    "review_decision",
    "corrected_instrument",
    "evidence_quote",
    "review_notes",
    "reviewed_at",
    "paper_url",
]

REVIEW_PAPER_STATUS_ORDER = ["verified", "partially_verified", "unverified"]
REVIEW_ASSIGNMENT_STATUS_ORDER = ["verified", "unverified"]

FILTER_WIDGET_KEYS = [
    "selected_instruments",
    "selected_authors",
    "selected_publishers",
    "selected_journals",
    "selected_paper_types",
    "selected_verification_statuses",
    "selected_go_canada_statuses",
    "selected_sources",
    "excluded_paper_ids",
    "excluded_instruments",
    "excluded_authors",
    "excluded_publishers",
    "excluded_journals",
    "excluded_paper_types",
    "excluded_verification_statuses",
    "excluded_go_canada_statuses",
    "excluded_sources",
    "excluded_missing_metadata_mode",
    "excluded_missing_metadata_fields",
    "metadata_completeness",
    "selected_missing_metadata_fields",
    "year_range",
    "remove_known_false_positives",
]

VIEW_WIDGET_KEYS = [
    "selected_columns",
    "graph_mode",
    "graph_preset",
    "custom_chart_type",
    "custom_x_variable",
    "custom_stack_variable",
    "custom_heatmap_x",
    "custom_heatmap_y",
    "top_n",
]

DEFAULT_VISIBLE_COLUMNS = [
    "DOI",
    "title",
    "year",
    "display_authors",
    "first_author",
    "journal",
    "publisher",
    "display_instruments",
    "paper_type",
    "verification_status",
    "evidence_quote",
    "display_sources",
    "notes",
]

COLUMN_LABELS = {
    "paper_id": "Paper ID",
    "DOI": "DOI",
    "title": "Title",
    "year": "Year",
    "journal": "Journal",
    "publisher": "Publisher",
    "paper_type": "Paper type",
    "go_canada_status": "GO-Canada status",
    "is_known_false_positive": "Known false positive?",
    "display_authors": "Authors",
    "first_author": "First author",
    "display_instruments": "Instruments",
    "verification_status": "Verification status",
    "evidence_quote": "Evidence quote",
    "checked_date": "Checked date",
    "display_sources": "Source / origin",
    "notes": "Notes",
}

STATUS_ORDER = ["verified_true", "verified_false", "unsure", "unchecked"]
FALSE_POSITIVE_PRIOR_WEIGHT = 20
MISSING_METADATA_FIELDS = [
    "DOI",
    "title",
    "year",
    "journal",
    "publisher",
    "paper_type",
    "authors",
    "instruments",
    "source",
    "verification_status",
]
MISSING_METADATA_FIELD_LABELS = {
    "DOI": "DOI",
    "title": "Title",
    "year": "Year",
    "journal": "Journal",
    "publisher": "Publisher",
    "paper_type": "Paper type",
    "authors": "Authors",
    "instruments": "Instruments",
    "source": "Source / origin",
    "verification_status": "Verification status",
}


# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------

def clean_text(value: Any) -> str:
    """Return a clean string without turning NaN into the string 'nan'."""
    if pd.isna(value):
        return ""
    return str(value).strip()


def parse_bool(value: Any) -> bool:
    """Parse common CSV boolean values."""
    if isinstance(value, bool):
        return value
    return clean_text(value).lower() in {"true", "1", "yes", "y", "known_false_positive"}


def unique_preserve_order(values: Iterable[Any]) -> list[str]:
    """Deduplicate while keeping the original order."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = clean_text(value)
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def join_list(values: list[str]) -> str:
    """Display a list inside the paper table."""
    return "; ".join(values)


def safe_year_series(series: pd.Series) -> pd.Series:
    """Convert year column to numeric years."""
    return pd.to_numeric(series, errors="coerce").astype("Int64")


def normalize_status(status: Any) -> str:
    """
    Normalize many possible verification labels into four dashboard labels.

    You can modify this mapping to match your exact database wording.
    """
    s = clean_text(status).lower().replace("-", "_").replace(" ", "_")

    true_labels = {
        "verified_true",
        "true",
        "uses",
        "uses_data",
        "definitely_uses",
        "definitely_uses_data",
        "uses_go_canada_data",
        "yes",
    }
    false_labels = {
        "verified_false",
        "false",
        "known_false_positive",
        "does_not_use",
        "definitely_does_not_use",
        "definitely_does_not_use_data",
        "mentioned_only",
        "reference_only",
        "no",
    }
    unsure_labels = {
        "unsure",
        "maybe",
        "uncertain",
        "cant_find_paper",
        "can't_find_paper",
        "not_accessible",
        "doi_not_working",
    }
    unchecked_labels = {"", "unchecked", "not_checked", "todo", "pending"}

    if s in true_labels:
        return "verified_true"
    if s in false_labels:
        return "verified_false"
    if s in unsure_labels:
        return "unsure"
    if s in unchecked_labels:
        return "unchecked"

    # Unknown labels are treated as unsure so that they are not hidden as unchecked.
    return "unsure"


def aggregate_status(statuses: Iterable[Any]) -> str:
    """
    Aggregate multiple paper-instrument verification statuses into one paper status.

    Priority rule:
      1. If any instrument is verified true, the paper has at least one true GO-Canada use.
      2. Else if any checked instrument is verified false, classify as verified false.
      3. Else if any checked instrument is unsure, classify as unsure.
      4. Otherwise unchecked.
    """
    normalized = [normalize_status(s) for s in statuses]
    if "verified_true" in normalized:
        return "verified_true"
    if "verified_false" in normalized:
        return "verified_false"
    if "unsure" in normalized:
        return "unsure"
    return "unchecked"


def contains_any(items: list[str], selected: list[str]) -> bool:
    """Return True if a list field contains at least one selected value."""
    if not selected:
        return True
    return any(item in items for item in selected)


def sorted_options(values: Iterable[Any]) -> list[str]:
    """Return clean sorted options for Streamlit widgets."""
    return sorted(unique_preserve_order(values), key=lambda x: x.lower())


# -----------------------------------------------------------------------------
# Data loading and database view construction
# -----------------------------------------------------------------------------

def supabase_headers(key: str) -> dict[str, str]:
    """Build Supabase REST headers."""
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def dataframe_for_storage(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Normalize a dataframe before writing to CSV or Supabase."""
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            out[col] = ""
    out = out[columns]
    for col in columns:
        out[col] = out[col].apply(clean_text)
    return out


def fetch_supabase_table(
    table_name: str,
    columns: list[str],
    url: str,
    key: str,
) -> pd.DataFrame:
    """Fetch one Supabase table through the REST API."""
    rows: list[dict[str, Any]] = []
    start = 0
    headers = supabase_headers(key)
    while True:
        end = start + SUPABASE_PAGE_SIZE - 1
        response = requests.get(
            f"{url}/rest/v1/{table_name}",
            params={"select": "*"},
            headers={**headers, "Range": f"{start}-{end}"},
            timeout=30,
        )
        response.raise_for_status()
        page_rows = response.json()
        rows.extend(page_rows)
        if len(page_rows) < SUPABASE_PAGE_SIZE:
            break
        start += SUPABASE_PAGE_SIZE

    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns]


@st.cache_data(show_spinner="Loading Supabase database...")
def load_supabase_database(url: str, key: str) -> dict[str, pd.DataFrame]:
    """Load all normalized tables from Supabase."""
    return {
        name: fetch_supabase_table(name, columns, url, key)
        for name, columns in REQUIRED_COLUMNS.items()
    }


def clear_database_caches() -> None:
    """Clear all cached database reads."""
    read_csv_safe.clear()
    load_csv_database.clear()
    load_database.clear()
    load_supabase_database.clear()


def delete_supabase_table(table_name: str, url: str, key: str) -> None:
    """Delete all rows from one Supabase table."""
    headers = supabase_headers(key)
    delete_column = TABLE_DELETE_FILTER_COLUMN[table_name]
    delete_response = requests.delete(
        f"{url}/rest/v1/{table_name}",
        params={delete_column: "not.is.null"},
        headers=headers,
        timeout=30,
    )
    delete_response.raise_for_status()


def insert_supabase_table(
    table_name: str,
    df: pd.DataFrame,
    columns: list[str],
    url: str,
    key: str,
) -> None:
    """Insert all rows for one Supabase table."""
    headers = supabase_headers(key)
    out = dataframe_for_storage(df, columns)
    primary_key_columns = TABLE_PRIMARY_KEY_COLUMNS.get(table_name, [])
    if primary_key_columns:
        out = out.drop_duplicates(subset=primary_key_columns, keep="last")
    records = out.to_dict("records")
    for start in range(0, len(records), SUPABASE_INSERT_CHUNK_SIZE):
        chunk = records[start : start + SUPABASE_INSERT_CHUNK_SIZE]
        if not chunk:
            continue
        insert_response = requests.post(
            f"{url}/rest/v1/{table_name}",
            json=chunk,
            headers=headers,
            timeout=60,
        )
        insert_response.raise_for_status()


def delete_supabase_verification_row(paper_id: str, instrument_id: str, url: str, key: str) -> None:
    """Delete one paper-instrument verification row from Supabase."""
    delete_response = requests.delete(
        f"{url}/rest/v1/verification",
        params={
            "paper_id": f"eq.{paper_id}",
            "instrument_id": f"eq.{instrument_id}",
        },
        headers=supabase_headers(key),
        timeout=30,
    )
    delete_response.raise_for_status()


def upsert_supabase_verification_row(row: dict[str, Any], url: str, key: str) -> None:
    """Insert or update one paper-instrument verification row in Supabase."""
    headers = {
        **supabase_headers(key),
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    upsert_response = requests.post(
        f"{url}/rest/v1/verification",
        params={"on_conflict": "paper_id,instrument_id"},
        json=[{column: clean_text(row.get(column)) for column in REQUIRED_COLUMNS["verification"]}],
        headers=headers,
        timeout=30,
    )
    upsert_response.raise_for_status()


def save_verification_row(
    tables: dict[str, pd.DataFrame],
    paper_id: str,
    instrument_id: str,
    status: str,
    evidence_quote: str,
    checked_date: str,
    notes: str,
) -> None:
    """Save one paper-instrument verification row to Supabase or CSV storage."""
    row = {
        "paper_id": paper_id,
        "instrument_id": instrument_id,
        "status": status,
        "evidence_quote": evidence_quote,
        "checked_date": checked_date,
        "notes": notes,
    }

    config = supabase_config()
    if config:
        url, key = config
        if status == "unchecked":
            delete_supabase_verification_row(paper_id, instrument_id, url, key)
        else:
            upsert_supabase_verification_row(row, url, key)
        clear_database_caches()
        return

    working_tables = {name: table.copy() for name, table in tables.items()}
    verification = working_tables["verification"].copy()
    keep_mask = ~(
        (verification["paper_id"].fillna("").astype(str) == paper_id)
        & (verification["instrument_id"].fillna("").astype(str) == instrument_id)
    )
    verification = verification[keep_mask].reset_index(drop=True)
    if status != "unchecked":
        verification = append_row(verification, row, REQUIRED_COLUMNS["verification"])
    working_tables["verification"] = verification
    save_database_tables(working_tables)


def replace_supabase_database(tables: dict[str, pd.DataFrame]) -> None:
    """Replace all Supabase normalized tables with current app tables."""
    config = supabase_config()
    if not config:
        raise RuntimeError("Supabase is not configured.")
    url, key = config

    delete_order = [
        "paper_sources",
        "verification",
        "paper_instruments",
        "paper_authors",
        "papers",
        "sources",
        "instruments",
        "authors",
    ]
    insert_order = [
        "papers",
        "authors",
        "instruments",
        "sources",
        "paper_authors",
        "paper_instruments",
        "verification",
        "paper_sources",
    ]
    for name in delete_order:
        delete_supabase_table(name, url, key)
    for name in insert_order:
        insert_supabase_table(name, tables[name], REQUIRED_COLUMNS[name], url, key)
    clear_database_caches()


@st.cache_data(show_spinner=False)
def read_csv_safe(path: Path, required_columns: list[str]) -> pd.DataFrame:
    """Read a CSV file. If it is missing, return an empty table with the expected columns."""
    if not path.exists():
        return pd.DataFrame(columns=required_columns)

    df = pd.read_csv(path)

    # Add missing optional columns so the app does not crash while you evolve the schema.
    for col in required_columns:
        if col not in df.columns:
            df[col] = ""

    return df


def write_csv_table(name: str, df: pd.DataFrame) -> None:
    """Write one normalized table back to disk with the expected column order."""
    if READ_ONLY_MODE:
        raise RuntimeError("CSV writes are disabled in read-only deployment mode.")

    DATA_DIR.mkdir(exist_ok=True)
    required_columns = REQUIRED_COLUMNS[name]
    out = dataframe_for_storage(df, required_columns)
    out.to_csv(CSV_PATHS[name], index=False)


@st.cache_data(show_spinner="Loading CSV database...")
def load_csv_database(data_dir: str = "data") -> dict[str, pd.DataFrame]:
    """Load all normalized CSV files."""
    base_dir = Path(data_dir)
    tables = {}
    for name, required_columns in REQUIRED_COLUMNS.items():
        tables[name] = read_csv_safe(base_dir / f"{name}.csv", required_columns)
    return tables


@st.cache_data(show_spinner="Loading database...")
def load_database(data_dir: str = "data") -> dict[str, pd.DataFrame]:
    """Load all normalized tables from Supabase when configured, otherwise CSV."""
    config = supabase_config()
    if config:
        url, key = config
        return load_supabase_database(url, key)

    return load_csv_database(data_dir)


@st.cache_data(show_spinner="Loading review database...")
def load_review_database(data_dir: str = "data/review") -> dict[str, pd.DataFrame]:
    """Load DOI-based paper review exports."""
    base_dir = Path(data_dir)
    return {
        "summary": read_csv_safe(
            base_dir / "paper_verification_summary.csv",
            REVIEW_SUMMARY_COLUMNS,
        ),
        "detail": read_csv_safe(
            base_dir / "paper_instrument_verification_status.csv",
            REVIEW_DETAIL_COLUMNS,
        ),
    }


def split_review_list(value: Any) -> list[str]:
    """Split review export list fields."""
    text = clean_text(value)
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def review_contains_any(value: Any, selected: list[str]) -> bool:
    """Return True when a semicolon-separated field contains one selected item."""
    if not selected:
        return True
    values = set(split_review_list(value))
    return any(item in values for item in selected)


def build_paper_view(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Build a one-row-per-paper dashboard table from normalized CSV tables.

    This is the main dataframe used by filters, tables, stats, graphs, and exports.
    """
    papers = tables["papers"].copy()
    if papers.empty:
        return pd.DataFrame(columns=list(COLUMN_LABELS.keys()))

    papers["paper_id"] = papers["paper_id"].astype(str)
    papers["year"] = safe_year_series(papers["year"])
    papers["is_known_false_positive"] = papers["is_known_false_positive"].apply(parse_bool)

    # ------------------------- authors -------------------------
    authors = tables["authors"]
    paper_authors = tables["paper_authors"]
    if not authors.empty and not paper_authors.empty:
        pa = paper_authors.merge(authors, on="author_id", how="left")
        pa["author_order"] = pd.to_numeric(pa["author_order"], errors="coerce")
        pa = pa.sort_values(["paper_id", "author_order"], na_position="last")

        authors_grouped = (
            pa.groupby("paper_id")
            .agg(
                authors=("author_name", lambda x: unique_preserve_order(x)),
                first_author=("author_name", lambda x: clean_text(next(iter(x), ""))),
            )
            .reset_index()
        )
    else:
        authors_grouped = pd.DataFrame(columns=["paper_id", "authors", "first_author"])

    # ----------------------- instruments -----------------------
    instruments = tables["instruments"]
    paper_instruments = tables["paper_instruments"]
    if not instruments.empty and not paper_instruments.empty:
        pi = paper_instruments.merge(instruments, on="instrument_id", how="left")
        instruments_grouped = (
            pi.groupby("paper_id")
            .agg(
                instruments=("instrument_name", lambda x: unique_preserve_order(x)),
                instrument_statuses=("instrument_status", lambda x: unique_preserve_order(x)),
            )
            .reset_index()
        )
    else:
        instruments_grouped = pd.DataFrame(
            columns=["paper_id", "instruments", "instrument_statuses"]
        )

    # ---------------------- verification ----------------------
    verification = tables["verification"].copy()
    if not verification.empty:
        verification["normalized_status"] = verification["status"].apply(normalize_status)
        verification_grouped = (
            verification.groupby("paper_id")
            .agg(
                verification_status=("normalized_status", aggregate_status),
                all_verification_statuses=("normalized_status", lambda x: unique_preserve_order(x)),
                evidence_quote=("evidence_quote", lambda x: " | ".join(unique_preserve_order(x))),
                checked_date=("checked_date", lambda x: " | ".join(unique_preserve_order(x))),
                notes=("notes", lambda x: " | ".join(unique_preserve_order(x))),
            )
            .reset_index()
        )
    else:
        verification_grouped = pd.DataFrame(
            columns=[
                "paper_id",
                "verification_status",
                "all_verification_statuses",
                "evidence_quote",
                "checked_date",
                "notes",
            ]
        )

    # ------------------------- sources -------------------------
    sources = tables["sources"]
    paper_sources = tables["paper_sources"]
    if not sources.empty and not paper_sources.empty:
        ps = paper_sources.merge(sources, on="source_id", how="left")
        sources_grouped = (
            ps.groupby("paper_id")
            .agg(
                sources=("source_name", lambda x: unique_preserve_order(x)),
                source_types=("source_type", lambda x: unique_preserve_order(x)),
            )
            .reset_index()
        )
    else:
        sources_grouped = pd.DataFrame(columns=["paper_id", "sources", "source_types"])

    # -------------------- combine into view --------------------
    df = papers.merge(authors_grouped, on="paper_id", how="left")
    df = df.merge(instruments_grouped, on="paper_id", how="left")
    df = df.merge(verification_grouped, on="paper_id", how="left")
    df = df.merge(sources_grouped, on="paper_id", how="left")

    # Fill list columns.
    for col in [
        "authors",
        "instruments",
        "instrument_statuses",
        "all_verification_statuses",
        "sources",
        "source_types",
    ]:
        if col not in df.columns:
            df[col] = [[] for _ in range(len(df))]
        else:
            df[col] = df[col].apply(lambda x: x if isinstance(x, list) else [])

    # Fill scalar columns.
    for col in [
        "first_author",
        "verification_status",
        "evidence_quote",
        "checked_date",
        "notes",
        "go_canada_status",
    ]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)

    df["verification_status"] = df["verification_status"].replace("", "unchecked")

    # Human-readable display columns.
    df["display_authors"] = df["authors"].apply(join_list)
    df["display_instruments"] = df["instruments"].apply(join_list)
    df["display_sources"] = df["sources"].apply(join_list)

    # Use DOI as a clean text field.
    df["DOI"] = df["DOI"].fillna("").astype(str).str.strip()

    return df


# -----------------------------------------------------------------------------
# Paper import and editing helpers
# -----------------------------------------------------------------------------

def split_multi_value(value: Any) -> list[str]:
    """Split semicolon-separated import fields."""
    text = clean_text(value)
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def generate_next_id(df: pd.DataFrame, id_col: str, prefix: str) -> str:
    """Generate the next ID with the table's existing prefix pattern."""
    if df.empty or id_col not in df.columns:
        return f"{prefix}001"

    max_number = 0
    for value in df[id_col].dropna().astype(str):
        if not value.startswith(prefix):
            continue
        suffix = value[len(prefix):]
        if suffix.isdigit():
            max_number = max(max_number, int(suffix))
    return f"{prefix}{max_number + 1:03d}"


def append_row(df: pd.DataFrame, row: dict[str, Any], columns: list[str]) -> pd.DataFrame:
    """Append one row while preserving the normalized table columns."""
    return pd.concat([df, pd.DataFrame([row], columns=columns)], ignore_index=True)


def existing_paper_match(papers: pd.DataFrame, doi: str, title: str) -> str:
    """Return a reason if a paper appears to already exist."""
    doi_key = clean_text(doi).lower()
    title_key = clean_text(title).lower()
    if doi_key:
        doi_matches = papers["DOI"].fillna("").astype(str).str.lower().str.strip() == doi_key
        if bool(doi_matches.any()):
            return "Duplicate DOI"
    if title_key:
        title_matches = normalized_match_key(papers["title"]) == title_key
        if bool(title_matches.any()):
            return "Duplicate title"
    return ""


def get_or_create_author_id(tables: dict[str, pd.DataFrame], author_name: str) -> str:
    """Find or create an author row and return its ID."""
    authors = tables["authors"]
    name_key = clean_text(author_name).lower()
    matches = authors["author_name"].fillna("").astype(str).str.lower().str.strip() == name_key
    if bool(matches.any()):
        return clean_text(authors.loc[matches, "author_id"].iloc[0])

    author_id = generate_next_id(authors, "author_id", "A")
    tables["authors"] = append_row(
        authors,
        {"author_id": author_id, "author_name": clean_text(author_name)},
        REQUIRED_COLUMNS["authors"],
    )
    return author_id


def get_or_create_instrument_id(tables: dict[str, pd.DataFrame], instrument_name: str) -> str:
    """Find or create an instrument row and return its ID."""
    instruments = tables["instruments"]
    name_key = clean_text(instrument_name).lower()
    matches = instruments["instrument_name"].fillna("").astype(str).str.lower().str.strip() == name_key
    if bool(matches.any()):
        return clean_text(instruments.loc[matches, "instrument_id"].iloc[0])

    instrument_id = generate_next_id(instruments, "instrument_id", "I")
    tables["instruments"] = append_row(
        instruments,
        {"instrument_id": instrument_id, "instrument_name": clean_text(instrument_name)},
        REQUIRED_COLUMNS["instruments"],
    )
    return instrument_id


def get_or_create_source_id(
    tables: dict[str, pd.DataFrame],
    source_name: str,
    source_type: str,
    notes: str = "",
) -> str:
    """Find or create a source row and return its ID."""
    sources = tables["sources"]
    name_key = clean_text(source_name).lower()
    matches = sources["source_name"].fillna("").astype(str).str.lower().str.strip() == name_key
    if bool(matches.any()):
        return clean_text(sources.loc[matches, "source_id"].iloc[0])

    source_id = generate_next_id(sources, "source_id", "S")
    tables["sources"] = append_row(
        sources,
        {
            "source_id": source_id,
            "source_name": clean_text(source_name),
            "source_type": clean_text(source_type) or "manual",
            "notes": clean_text(notes),
        },
        REQUIRED_COLUMNS["sources"],
    )
    return source_id


def add_paper_record(tables: dict[str, pd.DataFrame], record: dict[str, Any]) -> tuple[bool, str]:
    """Add one paper and related normalized rows to the in-memory tables."""
    title = clean_text(record.get("title"))
    doi = clean_text(record.get("DOI"))
    if not title:
        return False, "Missing title"

    duplicate_reason = existing_paper_match(tables["papers"], doi, title)
    if duplicate_reason:
        return False, duplicate_reason

    paper_id = generate_next_id(tables["papers"], "paper_id", "P")
    status = normalize_status(record.get("verification_status", "unchecked"))
    known_false_positive = parse_bool(record.get("is_known_false_positive")) or status == "verified_false"

    tables["papers"] = append_row(
        tables["papers"],
        {
            "paper_id": paper_id,
            "DOI": doi,
            "title": title,
            "year": clean_text(record.get("year")),
            "journal": clean_text(record.get("journal")),
            "publisher": clean_text(record.get("publisher")),
            "paper_type": clean_text(record.get("paper_type")),
            "go_canada_status": clean_text(record.get("go_canada_status")),
            "is_known_false_positive": known_false_positive,
        },
        REQUIRED_COLUMNS["papers"],
    )

    for order, author_name in enumerate(split_multi_value(record.get("authors")), start=1):
        author_id = get_or_create_author_id(tables, author_name)
        tables["paper_authors"] = append_row(
            tables["paper_authors"],
            {"paper_id": paper_id, "author_id": author_id, "author_order": order},
            REQUIRED_COLUMNS["paper_authors"],
        )

    instrument_names = split_multi_value(record.get("instruments"))
    instrument_statuses = split_multi_value(record.get("instrument_status"))
    instrument_ids = []
    for index, instrument_name in enumerate(instrument_names):
        instrument_id = get_or_create_instrument_id(tables, instrument_name)
        instrument_ids.append(instrument_id)
        instrument_status = (
            instrument_statuses[index]
            if index < len(instrument_statuses)
            else clean_text(record.get("instrument_status")) or "unchecked"
        )
        tables["paper_instruments"] = append_row(
            tables["paper_instruments"],
            {
                "paper_id": paper_id,
                "instrument_id": instrument_id,
                "instrument_status": instrument_status,
            },
            REQUIRED_COLUMNS["paper_instruments"],
        )

    source_names = split_multi_value(record.get("source_name") or record.get("source"))
    source_types = split_multi_value(record.get("source_type"))
    for index, source_name in enumerate(source_names):
        source_type = source_types[index] if index < len(source_types) else clean_text(record.get("source_type"))
        source_id = get_or_create_source_id(
            tables,
            source_name,
            source_type,
            clean_text(record.get("source_notes")),
        )
        tables["paper_sources"] = append_row(
            tables["paper_sources"],
            {"paper_id": paper_id, "source_id": source_id},
            REQUIRED_COLUMNS["paper_sources"],
        )

    if status != "unchecked":
        verification_instrument_ids = instrument_ids or [""]
        for instrument_id in verification_instrument_ids:
            tables["verification"] = append_row(
                tables["verification"],
                {
                    "paper_id": paper_id,
                    "instrument_id": instrument_id,
                    "status": status,
                    "evidence_quote": clean_text(record.get("evidence_quote")),
                    "checked_date": clean_text(record.get("checked_date")),
                    "notes": clean_text(record.get("notes")),
                },
                REQUIRED_COLUMNS["verification"],
            )

    return True, paper_id


def save_database_tables(tables: dict[str, pd.DataFrame]) -> None:
    """Persist all normalized tables to Supabase or local CSV files."""
    if supabase_config():
        replace_supabase_database(tables)
        return

    for name in REQUIRED_COLUMNS:
        write_csv_table(name, tables[name])
    clear_database_caches()


def normalize_import_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize uploaded CSV column names to the import schema."""
    aliases = {
        "doi": "DOI",
        "paper_doi": "DOI",
        "title": "title",
        "paper_title": "title",
        "year": "year",
        "journal": "journal",
        "publisher": "publisher",
        "paper_type": "paper_type",
        "type": "paper_type",
        "go_canada_status": "go_canada_status",
        "status_go_canada": "go_canada_status",
        "is_known_false_positive": "is_known_false_positive",
        "known_false_positive": "is_known_false_positive",
        "authors": "authors",
        "author": "authors",
        "instruments": "instruments",
        "instrument": "instruments",
        "instrument_status": "instrument_status",
        "verification_status": "verification_status",
        "status": "verification_status",
        "evidence_quote": "evidence_quote",
        "checked_date": "checked_date",
        "notes": "notes",
        "source": "source_name",
        "source_name": "source_name",
        "source_origin": "source_name",
        "source_type": "source_type",
        "source_notes": "source_notes",
    }
    out = df.copy()
    out.columns = [aliases.get(clean_text(col).lower().replace(" ", "_"), col) for col in out.columns]
    out = out.loc[:, ~out.columns.duplicated(keep="first")]
    return out


def import_papers_from_dataframe(
    tables: dict[str, pd.DataFrame],
    import_df: pd.DataFrame,
) -> pd.DataFrame:
    """Import many papers from a flat CSV dataframe."""
    normalized_df = normalize_import_columns(import_df)
    results = []
    for row_number, (_, row) in enumerate(normalized_df.iterrows(), start=2):
        record = {col: row.get(col, "") for col in normalized_df.columns}
        added, message = add_paper_record(tables, record)
        results.append(
            {
                "csv_row": row_number,
                "title": clean_text(record.get("title")),
                "DOI": clean_text(record.get("DOI")),
                "result": "added" if added else "skipped",
                "message": message,
            }
        )
    return pd.DataFrame(results)


# -----------------------------------------------------------------------------
# Filtering
# -----------------------------------------------------------------------------

def get_filter_options(df: pd.DataFrame) -> dict[str, list[str]]:
    """Build options for filter widgets."""
    options = {
        "instruments": sorted_options(item for values in df["instruments"] for item in values),
        "authors": sorted_options(item for values in df["authors"] for item in values),
        "publishers": sorted_options(df["publisher"]),
        "journals": sorted_options(df["journal"]),
        "paper_types": sorted_options(df["paper_type"]),
        "verification_statuses": [s for s in STATUS_ORDER if s in set(df["verification_status"])],
        "go_canada_statuses": sorted_options(df["go_canada_status"]),
        "sources": sorted_options(item for values in df["sources"] for item in values),
    }
    return options


def year_bounds(df: pd.DataFrame) -> tuple[int, int]:
    """Return min and max year for slider."""
    years = pd.to_numeric(df["year"], errors="coerce").dropna()
    if years.empty:
        current_year = datetime.now().year
        return current_year, current_year
    return int(years.min()), int(years.max())


def render_saved_view_controls() -> None:
    """Load and save JSON filter presets in the sidebar."""
    with st.sidebar.expander("Saved views / filter presets", expanded=False):
        preset_files = sorted(PRESET_DIR.glob("*.json"))
        preset_names = [p.stem for p in preset_files]

        if preset_names:
            selected_preset = st.selectbox("Load saved view", [""] + preset_names)
            if st.button("Load selected view", disabled=not selected_preset):
                preset_path = PRESET_DIR / f"{selected_preset}.json"
                with open(preset_path, "r", encoding="utf-8") as f:
                    preset = json.load(f)
                for key, value in preset.items():
                    st.session_state[key] = value
                st.rerun()
        else:
            st.caption("No saved presets yet.")

        if READ_ONLY_MODE:
            st.caption("Preset saving is disabled in the hosted read-only version.")
            return

        preset_name = st.text_input("New preset name")
        if st.button("Save current view", disabled=not preset_name.strip()):
            snapshot = {
                key: st.session_state.get(key)
                for key in FILTER_WIDGET_KEYS + VIEW_WIDGET_KEYS
                if key in st.session_state
            }
            safe_name = "".join(c for c in preset_name.strip() if c.isalnum() or c in "-_ ").strip()
            if safe_name:
                preset_path = PRESET_DIR / f"{safe_name}.json"
                with open(preset_path, "w", encoding="utf-8") as f:
                    json.dump(snapshot, f, indent=2)
                st.success(f"Saved preset: {safe_name}")


def render_filters(df: pd.DataFrame) -> dict[str, Any]:
    """Render sidebar filters and return the selected values."""
    options = get_filter_options(df)
    min_year, max_year = year_bounds(df)
    paper_ids = df["paper_id"].tolist()
    paper_id_to_label = dict(
        zip(
            df["paper_id"],
            df.apply(lambda row: f"{row['paper_id']} | {clean_text(row['title'])[:90]}", axis=1),
        )
    )

    pending_exclusions = st.session_state.pop("pending_excluded_paper_ids", [])
    if pending_exclusions:
        existing_exclusions = st.session_state.get("excluded_paper_ids", [])
        st.session_state["excluded_paper_ids"] = unique_preserve_order(
            existing_exclusions + pending_exclusions
        )
    if "excluded_paper_ids" in st.session_state:
        st.session_state["excluded_paper_ids"] = [
            paper_id
            for paper_id in st.session_state["excluded_paper_ids"]
            if paper_id in paper_ids
        ]

    st.sidebar.header("Filters")

    selected_instruments = st.sidebar.multiselect(
        "Instrument", options["instruments"], key="selected_instruments"
    )
    selected_authors = st.sidebar.multiselect(
        "Author", options["authors"], key="selected_authors"
    )

    if min_year == max_year:
        year_range = (min_year, max_year)
        st.sidebar.caption(f"Year range: {min_year}")
    else:
        default_year_range = st.session_state.get("year_range", (min_year, max_year))
        if not isinstance(default_year_range, (list, tuple)) or len(default_year_range) != 2:
            default_year_range = (min_year, max_year)
        default_year_range = (
            max(min_year, int(default_year_range[0])),
            min(max_year, int(default_year_range[1])),
        )
        year_range = st.sidebar.slider(
            "Year range",
            min_value=min_year,
            max_value=max_year,
            value=default_year_range,
            key="year_range",
        )

    selected_publishers = st.sidebar.multiselect(
        "Publisher", options["publishers"], key="selected_publishers"
    )
    selected_journals = st.sidebar.multiselect(
        "Journal", options["journals"], key="selected_journals"
    )
    selected_paper_types = st.sidebar.multiselect(
        "Paper type", options["paper_types"], key="selected_paper_types"
    )
    selected_verification_statuses = st.sidebar.multiselect(
        "Verification status",
        options["verification_statuses"],
        key="selected_verification_statuses",
    )
    selected_go_canada_statuses = st.sidebar.multiselect(
        "GO-Canada status", options["go_canada_statuses"], key="selected_go_canada_statuses"
    )
    selected_sources = st.sidebar.multiselect(
        "Source / origin", options["sources"], key="selected_sources"
    )

    with st.sidebar.expander("Exclude from results", expanded=False):
        excluded_paper_ids = st.multiselect(
            "Specific papers",
            paper_ids,
            format_func=lambda paper_id: paper_id_to_label.get(paper_id, paper_id),
            key="excluded_paper_ids",
        )

        excluded_instruments = st.multiselect(
            "Instrument", options["instruments"], key="excluded_instruments"
        )
        excluded_authors = st.multiselect(
            "Author", options["authors"], key="excluded_authors"
        )
        excluded_publishers = st.multiselect(
            "Publisher", options["publishers"], key="excluded_publishers"
        )
        excluded_journals = st.multiselect(
            "Journal", options["journals"], key="excluded_journals"
        )
        excluded_paper_types = st.multiselect(
            "Paper type", options["paper_types"], key="excluded_paper_types"
        )
        excluded_verification_statuses = st.multiselect(
            "Verification status",
            options["verification_statuses"],
            key="excluded_verification_statuses",
        )
        excluded_go_canada_statuses = st.multiselect(
            "GO-Canada status",
            options["go_canada_statuses"],
            key="excluded_go_canada_statuses",
        )
        excluded_sources = st.multiselect(
            "Source / origin", options["sources"], key="excluded_sources"
        )
        excluded_missing_metadata_mode = st.selectbox(
            "Missing metadata",
            ["Do not exclude by missing metadata", "Exclude any missing metadata"],
            key="excluded_missing_metadata_mode",
        )
        excluded_missing_metadata_fields = st.multiselect(
            "Missing metadata fields",
            MISSING_METADATA_FIELDS,
            format_func=lambda field: MISSING_METADATA_FIELD_LABELS.get(field, field),
            key="excluded_missing_metadata_fields",
        )

    metadata_completeness = st.sidebar.selectbox(
        "Metadata completeness",
        ["All papers", "Only complete metadata", "Only missing metadata"],
        key="metadata_completeness",
    )
    selected_missing_metadata_fields = st.sidebar.multiselect(
        "Missing metadata fields",
        MISSING_METADATA_FIELDS,
        format_func=lambda field: MISSING_METADATA_FIELD_LABELS.get(field, field),
        key="selected_missing_metadata_fields",
    )

    remove_known_false_positives = st.sidebar.toggle(
        "Remove known false positives",
        value=st.session_state.get("remove_known_false_positives", False),
        key="remove_known_false_positives",
    )

    return {
        "selected_instruments": selected_instruments,
        "selected_authors": selected_authors,
        "selected_publishers": selected_publishers,
        "selected_journals": selected_journals,
        "selected_paper_types": selected_paper_types,
        "selected_verification_statuses": selected_verification_statuses,
        "selected_go_canada_statuses": selected_go_canada_statuses,
        "selected_sources": selected_sources,
        "excluded_paper_ids": excluded_paper_ids,
        "excluded_instruments": excluded_instruments,
        "excluded_authors": excluded_authors,
        "excluded_publishers": excluded_publishers,
        "excluded_journals": excluded_journals,
        "excluded_paper_types": excluded_paper_types,
        "excluded_verification_statuses": excluded_verification_statuses,
        "excluded_go_canada_statuses": excluded_go_canada_statuses,
        "excluded_sources": excluded_sources,
        "excluded_missing_metadata_mode": excluded_missing_metadata_mode,
        "excluded_missing_metadata_fields": excluded_missing_metadata_fields,
        "metadata_completeness": metadata_completeness,
        "selected_missing_metadata_fields": selected_missing_metadata_fields,
        "year_range": year_range,
        "remove_known_false_positives": remove_known_false_positives,
    }


def false_positive_mask(df: pd.DataFrame) -> pd.Series:
    """Return rows that are known false positives in either flag or verification status."""
    return df["is_known_false_positive"].astype(bool) | (
        df["verification_status"] == "verified_false"
    )


def checked_sample_mask(df: pd.DataFrame) -> pd.Series:
    """Return rows that are part of the manually checked sample."""
    return (
        df["verification_status"].isin(["verified_true", "verified_false", "unsure"])
        | df["is_known_false_positive"].astype(bool)
    )


def estimate_false_positive_sample_rate(
    sample_df: pd.DataFrame,
    fallback_df: pd.DataFrame,
) -> tuple[float, int, int, str]:
    """
    Estimate a false-positive rate from sparse labels.

    The current search sample is blended with the global labeled sample so a
    tiny search with zero observed false positives does not imply zero risk for
    unchecked papers.
    """
    labeled_sample = sample_df[checked_sample_mask(sample_df)]
    global_sample = fallback_df[checked_sample_mask(fallback_df)]

    sample_false = int(false_positive_mask(labeled_sample).sum()) if not labeled_sample.empty else 0
    sample_checked = len(labeled_sample)
    global_false = int(false_positive_mask(global_sample).sum()) if not global_sample.empty else 0
    global_checked = len(global_sample)
    global_rate = global_false / global_checked if global_checked else 0.0

    if sample_checked and global_checked:
        adjusted_rate = (
            sample_false + (FALSE_POSITIVE_PRIOR_WEIGHT * global_rate)
        ) / (sample_checked + FALSE_POSITIVE_PRIOR_WEIGHT)
        return (
            adjusted_rate,
            sample_checked,
            sample_false,
            "Current search sample with global prior",
        )

    if sample_checked:
        return sample_false / sample_checked, sample_checked, sample_false, "Current search sample"

    if global_checked:
        return global_rate, global_checked, global_false, "Global sample fallback"

    return 0.0, 0, 0, "No checked sample"


def apply_filters(
    df: pd.DataFrame,
    filters: dict[str, Any],
    *,
    remove_known_false_positives: bool | None = None,
    apply_verification_filter: bool = True,
) -> pd.DataFrame:
    """Apply all sidebar filters to the one-row-per-paper view."""
    out = df.copy()

    out = out[
        out["instruments"].apply(
            lambda values: contains_any(values, filters["selected_instruments"])
        )
    ]
    out = out[
        out["authors"].apply(lambda values: contains_any(values, filters["selected_authors"]))
    ]

    year_start, year_end = filters["year_range"]
    numeric_year = pd.to_numeric(out["year"], errors="coerce")
    known_years = numeric_year.dropna()
    is_full_year_range = (
        known_years.empty
        or (year_start <= int(known_years.min()) and year_end >= int(known_years.max()))
    )
    year_mask = numeric_year.between(year_start, year_end, inclusive="both")
    if is_full_year_range:
        year_mask = year_mask | numeric_year.isna()
    out = out[year_mask]

    if filters["selected_publishers"]:
        out = out[out["publisher"].isin(filters["selected_publishers"])]
    if filters["selected_journals"]:
        out = out[out["journal"].isin(filters["selected_journals"])]
    if filters["selected_paper_types"]:
        out = out[out["paper_type"].isin(filters["selected_paper_types"])]
    if apply_verification_filter and filters["selected_verification_statuses"]:
        out = out[out["verification_status"].isin(filters["selected_verification_statuses"])]
    if filters["selected_go_canada_statuses"]:
        out = out[out["go_canada_status"].isin(filters["selected_go_canada_statuses"])]
    if filters["selected_sources"]:
        out = out[
            out["sources"].apply(lambda values: contains_any(values, filters["selected_sources"]))
        ]

    if filters.get("excluded_paper_ids"):
        out = out[~out["paper_id"].isin(filters["excluded_paper_ids"])]
    if filters.get("excluded_instruments"):
        out = out[
            ~out["instruments"].apply(
                lambda values: contains_any(values, filters["excluded_instruments"])
            )
        ]
    if filters.get("excluded_authors"):
        out = out[
            ~out["authors"].apply(lambda values: contains_any(values, filters["excluded_authors"]))
        ]
    if filters.get("excluded_publishers"):
        out = out[~out["publisher"].isin(filters["excluded_publishers"])]
    if filters.get("excluded_journals"):
        out = out[~out["journal"].isin(filters["excluded_journals"])]
    if filters.get("excluded_paper_types"):
        out = out[~out["paper_type"].isin(filters["excluded_paper_types"])]
    if filters.get("excluded_verification_statuses"):
        out = out[~out["verification_status"].isin(filters["excluded_verification_statuses"])]
    if filters.get("excluded_go_canada_statuses"):
        out = out[~out["go_canada_status"].isin(filters["excluded_go_canada_statuses"])]
    if filters.get("excluded_sources"):
        out = out[
            ~out["sources"].apply(lambda values: contains_any(values, filters["excluded_sources"]))
        ]
    excluded_missing_mode = filters.get(
        "excluded_missing_metadata_mode",
        "Do not exclude by missing metadata",
    )
    excluded_missing_fields = filters.get("excluded_missing_metadata_fields", [])
    if excluded_missing_mode != "Do not exclude by missing metadata" or excluded_missing_fields:
        masks = missing_metadata_masks(out)
        if excluded_missing_mode == "Exclude any missing metadata":
            any_missing = pd.concat(masks.values(), axis=1).any(axis=1)
            out = out[~any_missing]
            masks = missing_metadata_masks(out)

        if excluded_missing_fields:
            selected_masks = [
                masks[field]
                for field in excluded_missing_fields
                if field in masks
            ]
            if selected_masks:
                selected_missing = pd.concat(selected_masks, axis=1).any(axis=1)
                out = out[~selected_missing]

    metadata_completeness = filters.get("metadata_completeness", "All papers")
    selected_missing_fields = filters.get("selected_missing_metadata_fields", [])
    if metadata_completeness != "All papers" or selected_missing_fields:
        masks = missing_metadata_masks(out)
        if masks:
            any_missing = pd.concat(masks.values(), axis=1).any(axis=1)
        else:
            any_missing = pd.Series(False, index=out.index)

        if metadata_completeness == "Only complete metadata":
            out = out[~any_missing]
            masks = missing_metadata_masks(out)
        elif metadata_completeness == "Only missing metadata":
            out = out[any_missing]
            masks = missing_metadata_masks(out)

        if selected_missing_fields:
            selected_masks = [
                masks[field]
                for field in selected_missing_fields
                if field in masks
            ]
            if selected_masks:
                selected_missing = pd.concat(selected_masks, axis=1).any(axis=1)
                out = out[selected_missing]
            else:
                out = out.iloc[0:0]

    if remove_known_false_positives is None:
        remove_known_false_positives = filters["remove_known_false_positives"]

    if remove_known_false_positives:
        out = out[~false_positive_mask(out)]

    return out.reset_index(drop=True)


# -----------------------------------------------------------------------------
# Statistics and summaries
# -----------------------------------------------------------------------------

def compute_statistics(
    df: pd.DataFrame,
    false_positive_reference_df: pd.DataFrame | None = None,
    estimate_population_df: pd.DataFrame | None = None,
    fallback_reference_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Compute all live statistics from the current filtered subset."""
    reference_df = false_positive_reference_df if false_positive_reference_df is not None else df
    population_df = estimate_population_df if estimate_population_df is not None else df
    fallback_df = fallback_reference_df if fallback_reference_df is not None else reference_df

    if df.empty and reference_df.empty and population_df.empty and fallback_df.empty:
        return {
            "total_papers": 0,
            "unique_papers": 0,
            "verified_true_papers": 0,
            "verified_false_papers": 0,
            "unchecked_papers": 0,
            "unsure_papers": 0,
            "checked_papers": 0,
            "estimated_false_positive_rate": 0.0,
            "estimated_clean_count": 0.0,
            "estimated_remaining_false_positives": 0.0,
            "known_false_positives_removed": 0,
            "false_positive_sample_rate": 0.0,
            "false_positive_sample_size": 0,
            "false_positive_sample_false_count": 0,
            "false_positive_sample_source": "No checked sample",
            "estimate_population_size": 0,
            "most_common_instrument": "",
            "most_common_author": "",
            "most_common_publisher": "",
            "most_active_year": "",
        }

    total_papers = len(df)
    unique_papers = df["paper_id"].nunique()
    verified_true = int((df["verification_status"] == "verified_true").sum())
    verified_false = int((df["verification_status"] == "verified_false").sum())
    unsure = int((df["verification_status"] == "unsure").sum())
    unchecked = int((df["verification_status"] == "unchecked").sum())
    checked = verified_true + verified_false + unsure

    sample_fp_rate, sample_checked, sample_false, sample_source = (
        estimate_false_positive_sample_rate(reference_df, fallback_df)
    )

    population_ids = set(population_df["paper_id"])
    removed_known_fp = int((
        false_positive_mask(reference_df)
        & (~reference_df["paper_id"].isin(population_ids))
    ).sum())
    reference_total = len(reference_df)
    estimated_total_fp = reference_total * sample_fp_rate
    estimated_remaining_fp = max(estimated_total_fp - removed_known_fp, 0.0)
    population_total = len(population_df)
    estimated_remaining_fp = min(estimated_remaining_fp, float(population_total))
    fp_rate = estimated_remaining_fp / population_total if population_total else 0.0
    estimated_clean_count = max(population_total - estimated_remaining_fp, 0.0)

    instruments = df["instruments"].explode().dropna()
    authors = df["authors"].explode().dropna()
    publishers = df["publisher"].dropna()
    years = df["year"].dropna()

    return {
        "total_papers": total_papers,
        "unique_papers": unique_papers,
        "verified_true_papers": verified_true,
        "verified_false_papers": verified_false,
        "unchecked_papers": unchecked,
        "unsure_papers": unsure,
        "checked_papers": checked,
        "estimated_false_positive_rate": fp_rate,
        "estimated_clean_count": estimated_clean_count,
        "estimated_remaining_false_positives": estimated_remaining_fp,
        "known_false_positives_removed": removed_known_fp,
        "false_positive_sample_rate": sample_fp_rate,
        "false_positive_sample_size": sample_checked,
        "false_positive_sample_false_count": sample_false,
        "false_positive_sample_source": sample_source,
        "estimate_population_size": population_total,
        "most_common_instrument": instruments.value_counts().idxmax() if not instruments.empty else "",
        "most_common_author": authors.value_counts().idxmax() if not authors.empty else "",
        "most_common_publisher": publishers.value_counts().idxmax() if not publishers.empty else "",
        "most_active_year": int(years.value_counts().idxmax()) if not years.empty else "",
    }


def render_metric_grid(stats: dict[str, Any]) -> None:
    """Render summary cards."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total papers", f"{stats['total_papers']:,}")
    c2.metric("Verified true", f"{stats['verified_true_papers']:,}")
    c3.metric("Verified false", f"{stats['verified_false_papers']:,}")
    c4.metric("Unchecked / unsure", f"{stats['unchecked_papers'] + stats['unsure_papers']:,}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Checked papers", f"{stats['checked_papers']:,}")
    c6.metric("False-positive rate", f"{stats['estimated_false_positive_rate']:.1%}")
    c7.metric("Estimated clean count", f"{stats['estimated_clean_count']:.1f}")
    c8.metric("Most active year", f"{stats['most_active_year']}")

    c9, c10, c11, c12 = st.columns(4)
    c9.metric("Adjusted sample FP rate", f"{stats['false_positive_sample_rate']:.1%}")
    c10.metric("Sample size", f"{stats['false_positive_sample_size']:,}")
    c11.metric("Known FPs removed", f"{stats['known_false_positives_removed']:,}")
    c12.metric(
        "Estimated remaining FPs",
        f"{stats['estimated_remaining_false_positives']:.1f}",
    )
    st.caption(
        "False-positive estimate basis: "
        f"{stats['false_positive_sample_source']} "
        f"over {stats['estimate_population_size']:,} papers in the current search."
    )


def render_top_lists(df: pd.DataFrame, top_n: int = 10) -> None:
    """Show small ranked tables for instruments, authors, and publishers."""
    c1, c2, c3 = st.columns(3)

    with c1:
        st.subheader("Top instruments")
        data = df["instruments"].explode().dropna().value_counts().head(top_n).reset_index()
        data.columns = ["instrument", "papers"] if not data.empty else ["instrument", "papers"]
        st.dataframe(data, use_container_width=True, hide_index=True)

    with c2:
        st.subheader("Top authors")
        data = df["authors"].explode().dropna().value_counts().head(top_n).reset_index()
        data.columns = ["author", "papers"] if not data.empty else ["author", "papers"]
        st.dataframe(data, use_container_width=True, hide_index=True)

    with c3:
        st.subheader("Top publishers")
        data = df["publisher"].dropna().value_counts().head(top_n).reset_index()
        data.columns = ["publisher", "papers"] if not data.empty else ["publisher", "papers"]
        st.dataframe(data, use_container_width=True, hide_index=True)


def filters_to_summary_rows(filters: dict[str, Any], stats: dict[str, Any]) -> list[dict[str, Any]]:
    """Create rows for filter_summary.csv."""
    rows: list[dict[str, Any]] = []

    for key, value in filters.items():
        if isinstance(value, (list, tuple)):
            value = "; ".join(str(v) for v in value)
        rows.append({"field": f"filter_{key}", "value": value})

    summary_fields = [
        "total_papers",
        "checked_papers",
        "verified_true_papers",
        "verified_false_papers",
        "unsure_papers",
        "unchecked_papers",
        "false_positive_sample_rate",
        "false_positive_sample_size",
        "false_positive_sample_false_count",
        "false_positive_sample_source",
        "estimate_population_size",
        "known_false_positives_removed",
        "estimated_remaining_false_positives",
        "estimated_false_positive_rate",
        "estimated_clean_count",
    ]
    for field in summary_fields:
        rows.append({"field": field, "value": stats[field]})

    rows.append({"field": "export_date", "value": datetime.now().isoformat(timespec="seconds")})
    return rows


# -----------------------------------------------------------------------------
# Data quality helpers
# -----------------------------------------------------------------------------

def normalized_match_key(series: pd.Series) -> pd.Series:
    """Normalize text for duplicate checks."""
    return (
        series.fillna("")
        .astype(str)
        .str.lower()
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def missing_metadata_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Return one boolean mask per missing metadata field."""
    if df.empty:
        return {
            field: pd.Series(False, index=df.index)
            for field in MISSING_METADATA_FIELDS
        }

    return {
        "DOI": normalized_match_key(df["DOI"]) == "",
        "title": normalized_match_key(df["title"]) == "",
        "year": pd.to_numeric(df["year"], errors="coerce").isna(),
        "journal": normalized_match_key(df["journal"]) == "",
        "publisher": normalized_match_key(df["publisher"]) == "",
        "paper_type": normalized_match_key(df["paper_type"]) == "",
        "authors": df["authors"].apply(lambda values: len(values) == 0),
        "instruments": df["instruments"].apply(lambda values: len(values) == 0),
        "source": df["sources"].apply(lambda values: len(values) == 0),
        "verification_status": normalized_match_key(df["verification_status"]) == "",
    }


def detect_duplicate_papers(df: pd.DataFrame) -> pd.DataFrame:
    """Find likely duplicate papers by DOI or by normalized title."""
    if df.empty:
        return pd.DataFrame()

    rows = []
    work = df.copy()
    work["doi_key"] = normalized_match_key(work["DOI"])
    work["title_key"] = normalized_match_key(work["title"])

    duplicate_checks = [
        ("DOI", "doi_key"),
        ("Title", "title_key"),
    ]
    for match_type, key_col in duplicate_checks:
        candidates = work[work[key_col] != ""]
        duplicate_keys = candidates[candidates.duplicated(key_col, keep=False)]
        if duplicate_keys.empty:
            continue
        for match_value, group in duplicate_keys.groupby(key_col):
            for _, paper in group.sort_values(["year", "title"], na_position="last").iterrows():
                rows.append(
                    {
                        "match_type": match_type,
                        "match_value": match_value,
                        "paper_id": paper["paper_id"],
                        "DOI": paper["DOI"],
                        "title": paper["title"],
                        "year": paper["year"],
                        "journal": paper["journal"],
                        "authors": paper["display_authors"],
                        "sources": paper["display_sources"],
                    }
                )

    if not rows:
        return pd.DataFrame(
            columns=[
                "match_type",
                "match_value",
                "paper_id",
                "DOI",
                "title",
                "year",
                "journal",
                "authors",
                "sources",
            ]
        )

    return pd.DataFrame(rows).drop_duplicates()


def missing_metadata_report(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return per-paper and summary missing metadata reports."""
    masks = missing_metadata_masks(df)

    rows = []
    for _, paper in df.iterrows():
        missing_fields = [
            field
            for field, mask in masks.items()
            if bool(mask.loc[paper.name])
        ]
        if missing_fields:
            rows.append(
                {
                    "paper_id": paper["paper_id"],
                    "DOI": paper["DOI"],
                    "title": paper["title"],
                    "year": paper["year"],
                    "missing_count": len(missing_fields),
                    "missing_fields": "; ".join(missing_fields),
                    "authors": paper["display_authors"],
                    "instruments": paper["display_instruments"],
                    "sources": paper["display_sources"],
                }
            )

    detail_columns = [
        "paper_id",
        "DOI",
        "title",
        "year",
        "missing_count",
        "missing_fields",
        "authors",
        "instruments",
        "sources",
    ]
    detail = pd.DataFrame(rows, columns=detail_columns)
    summary_rows = []
    for field, mask in masks.items():
        missing_count = int(mask.sum()) if not df.empty else 0
        summary_rows.append(
            {
                "field": MISSING_METADATA_FIELD_LABELS.get(field, field),
                "missing_papers": missing_count,
                "missing_percent": missing_count / len(df) if len(df) else 0.0,
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values("missing_papers", ascending=False)
    return detail, summary


# -----------------------------------------------------------------------------
# Graph helpers
# -----------------------------------------------------------------------------

def explode_for_variable(df: pd.DataFrame, variable: str) -> pd.DataFrame:
    """Return a dataframe where list-valued graph variables are exploded."""
    if variable == "instrument":
        out = df.explode("instruments").rename(columns={"instruments": "instrument"})
        out = out[out["instrument"].notna() & (out["instrument"] != "")]
        return out
    if variable == "author":
        out = df.explode("authors").rename(columns={"authors": "author"})
        out = out[out["author"].notna() & (out["author"] != "")]
        return out
    if variable == "source":
        out = df.explode("sources").rename(columns={"sources": "source"})
        out = out[out["source"].notna() & (out["source"] != "")]
        return out
    return df.copy()


def count_by_variable(df: pd.DataFrame, variable: str, top_n: int | None = None) -> pd.DataFrame:
    """Count unique papers by a categorical or list-valued variable."""
    out = explode_for_variable(df, variable)
    if out.empty or variable not in out.columns:
        return pd.DataFrame(columns=[variable, "papers"])

    counts = (
        out.dropna(subset=[variable])
        .groupby(variable)["paper_id"]
        .nunique()
        .reset_index(name="papers")
        .sort_values("papers", ascending=False)
    )
    if top_n:
        counts = counts.head(top_n)
    return counts


def plot_count_chart(counts: pd.DataFrame, variable: str, chart_type: str, title: str):
    """Plot a count table with the requested chart type."""
    if counts.empty:
        st.info("No data to plot for the current filters.")
        return

    if chart_type == "Bar chart":
        fig = px.bar(counts, x=variable, y="papers", title=title)
    elif chart_type == "Line chart":
        fig = px.line(counts.sort_values(variable), x=variable, y="papers", markers=True, title=title)
    elif chart_type == "Pie chart":
        fig = px.pie(counts, names=variable, values="papers", title=title)
    elif chart_type == "Donut chart":
        fig = px.pie(counts, names=variable, values="papers", hole=0.45, title=title)
    else:
        fig = px.bar(counts, x=variable, y="papers", title=title)

    st.plotly_chart(fig, use_container_width=True)


def cooccurrence_edges(df: pd.DataFrame, list_column: str) -> pd.DataFrame:
    """Count how often pairs of list-valued items appear together on a paper."""
    edge_counts: dict[tuple[str, str], int] = {}

    for _, row in df.iterrows():
        items = unique_preserve_order(row.get(list_column, []))
        if len(items) < 2:
            continue
        for left, right in combinations(sorted(items), 2):
            edge_counts[(left, right)] = edge_counts.get((left, right), 0) + 1

    return pd.DataFrame(
        [
            {"source": source, "target": target, "papers": papers}
            for (source, target), papers in edge_counts.items()
        ]
    )


def plot_cooccurrence_network(
    df: pd.DataFrame,
    list_column: str,
    title: str,
    top_n: int,
) -> None:
    """Plot a network where nodes are authors or instruments and edges are shared papers."""
    edges = cooccurrence_edges(df, list_column)
    node_counts = (
        df.explode(list_column)
        .dropna(subset=[list_column])
        .groupby(list_column)["paper_id"]
        .nunique()
        .sort_values(ascending=False)
    )
    node_counts = node_counts[node_counts.index != ""]

    if edges.empty or node_counts.empty:
        st.info("No co-use or collaboration pairs are available for the current filters.")
        return

    top_nodes = set(node_counts.head(top_n).index)
    edges = edges[edges["source"].isin(top_nodes) & edges["target"].isin(top_nodes)]
    if edges.empty:
        st.info("No pairs remain after applying the Top N limit.")
        return

    graph = nx.Graph()
    for node, papers in node_counts.loc[list(top_nodes)].items():
        graph.add_node(node, papers=int(papers))
    for edge in edges.itertuples(index=False):
        graph.add_edge(edge.source, edge.target, weight=int(edge.papers))

    positions = nx.spring_layout(graph, seed=42, weight="weight")

    edge_traces = []
    for source, target, data in graph.edges(data=True):
        x0, y0 = positions[source]
        x1, y1 = positions[target]
        weight = data["weight"]
        edge_traces.append(
            go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                mode="lines",
                line=dict(width=max(1, min(weight * 1.5, 8)), color="#8a8f98"),
                hoverinfo="text",
                text=f"{source} + {target}<br>{weight} shared papers",
                showlegend=False,
            )
        )

    nodes = list(graph.nodes)
    node_x = [positions[node][0] for node in nodes]
    node_y = [positions[node][1] for node in nodes]
    node_papers = [graph.nodes[node]["papers"] for node in nodes]
    node_text = [f"{node}<br>{papers} papers" for node, papers in zip(nodes, node_papers)]

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        text=nodes,
        textposition="top center",
        hovertext=node_text,
        hoverinfo="text",
        marker=dict(
            size=[12 + min(papers * 4, 28) for papers in node_papers],
            color=node_papers,
            colorscale="Viridis",
            showscale=True,
            colorbar=dict(title="Papers"),
            line=dict(width=1, color="#2f343d"),
        ),
        showlegend=False,
    )

    fig = go.Figure(data=edge_traces + [node_trace])
    fig.update_layout(
        title=title,
        margin=dict(l=10, r=10, t=50, b=10),
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        height=650,
    )
    st.plotly_chart(fig, use_container_width=True)


def plot_instrument_overlap(df: pd.DataFrame, top_n: int) -> None:
    """Plot exact instrument combinations, similar to a compact UpSet summary."""
    rows = []
    for _, row in df.iterrows():
        instruments = unique_preserve_order(row.get("instruments", []))
        if not instruments:
            continue
        rows.append(
            {
                "combination": " + ".join(sorted(instruments)),
                "instrument_count": len(instruments),
                "paper_id": row["paper_id"],
            }
        )

    if not rows:
        st.info("No instrument overlap data available for the current filters.")
        return

    overlap = (
        pd.DataFrame(rows)
        .groupby(["combination", "instrument_count"])["paper_id"]
        .nunique()
        .reset_index(name="papers")
        .sort_values(["papers", "instrument_count"], ascending=[False, False])
        .head(top_n)
    )
    fig = px.bar(
        overlap,
        x="papers",
        y="combination",
        color="instrument_count",
        orientation="h",
        title="Instrument overlap combinations",
        labels={
            "papers": "Papers",
            "combination": "Instrument combination",
            "instrument_count": "Instruments",
        },
    )
    fig.update_layout(yaxis=dict(autorange="reversed"), height=max(420, 28 * len(overlap)))
    st.plotly_chart(fig, use_container_width=True)


def plot_timeline_by_variable(
    df: pd.DataFrame,
    variable: str,
    label: str,
    top_n: int,
) -> None:
    """Plot yearly paper counts for the top authors or instruments."""
    out = explode_for_variable(df, variable)
    if out.empty:
        st.info(f"No {label.lower()} data available for the current filters.")
        return

    out = out.dropna(subset=["year", variable])
    out = out[(out[variable] != "") & pd.to_numeric(out["year"], errors="coerce").notna()]
    if out.empty:
        st.info(f"No {label.lower()} timeline data available for the current filters.")
        return

    top_values = (
        out.groupby(variable)["paper_id"]
        .nunique()
        .sort_values(ascending=False)
        .head(top_n)
        .index
    )
    grouped = (
        out[out[variable].isin(top_values)]
        .groupby(["year", variable])["paper_id"]
        .nunique()
        .reset_index(name="papers")
        .sort_values("year")
    )
    fig = px.line(
        grouped,
        x="year",
        y="papers",
        color=variable,
        markers=True,
        title=f"{label} timeline",
        labels={"year": "Year", "papers": "Papers", variable: label},
    )
    fig.update_xaxes(dtick=1)
    st.plotly_chart(fig, use_container_width=True)


def plot_preset_graph(
    df: pd.DataFrame,
    preset: str,
    chart_type: str,
    top_n: int,
    false_positive_reference_df: pd.DataFrame | None = None,
    estimate_population_df: pd.DataFrame | None = None,
    fallback_reference_df: pd.DataFrame | None = None,
) -> None:
    """Render one of the useful prebuilt graph examples."""
    if df.empty:
        st.info("No papers match the current filters.")
        return

    if preset == "Papers per year":
        counts = count_by_variable(df, "year").sort_values("year")
        plot_count_chart(counts, "year", chart_type, "Papers per year")

    elif preset == "Papers by instrument":
        counts = count_by_variable(df, "instrument", top_n)
        plot_count_chart(counts, "instrument", chart_type, "Papers by instrument")

    elif preset == "Papers by publisher":
        counts = count_by_variable(df, "publisher", top_n)
        plot_count_chart(counts, "publisher", chart_type, "Papers by publisher")

    elif preset == "Papers by journal":
        counts = count_by_variable(df, "journal", top_n)
        plot_count_chart(counts, "journal", chart_type, "Papers by journal")

    elif preset == "Papers by author":
        counts = count_by_variable(df, "author", top_n)
        plot_count_chart(counts, "author", chart_type, "Papers by author")

    elif preset == "Verified vs unchecked papers":
        counts = count_by_variable(df, "verification_status")
        counts["verification_status"] = pd.Categorical(
            counts["verification_status"], categories=STATUS_ORDER, ordered=True
        )
        counts = counts.sort_values("verification_status")
        plot_count_chart(
            counts,
            "verification_status",
            chart_type,
            "Verification status of filtered papers",
        )

    elif preset == "Raw vs cleaned count":
        stats = compute_statistics(
            df,
            false_positive_reference_df,
            estimate_population_df,
            fallback_reference_df,
        )
        counts = pd.DataFrame(
            {
                "count_type": ["Raw filtered count", "Estimated clean count"],
                "papers": [stats["total_papers"], stats["estimated_clean_count"]],
            }
        )
        plot_count_chart(counts, "count_type", "Bar chart", "Raw vs estimated clean count")

    elif preset == "False-positive rate by instrument":
        reference = false_positive_reference_df if false_positive_reference_df is not None else df
        fallback = fallback_reference_df if fallback_reference_df is not None else reference
        exploded_reference = explode_for_variable(reference, "instrument")
        exploded_current = explode_for_variable(df, "instrument")
        if exploded_reference.empty or exploded_current.empty:
            st.info("No instrument data available.")
            return

        exploded_reference = exploded_reference.copy()
        exploded_reference["is_false_positive"] = false_positive_mask(exploded_reference)
        current_ids = set(df["paper_id"])
        exploded_reference["was_removed"] = ~exploded_reference["paper_id"].isin(current_ids)
        grouped = (
            exploded_reference.groupby("instrument")
            .agg(
                reference_total=("paper_id", "nunique"),
                checked=("paper_id", lambda s: checked_sample_mask(exploded_reference.loc[s.index]).sum()),
                verified_false=("is_false_positive", "sum"),
                removed_known_fp=("was_removed", "sum"),
            )
            .reset_index()
        )
        current_totals = (
            exploded_current.groupby("instrument")["paper_id"]
            .nunique()
            .reset_index(name="current_total")
        )
        grouped = grouped.merge(current_totals, on="instrument", how="inner")
        grouped = grouped[grouped["current_total"] > 0]

        rate_estimates = grouped["instrument"].apply(
            lambda instrument: estimate_false_positive_sample_rate(
                exploded_reference[exploded_reference["instrument"] == instrument],
                fallback,
            )
        )
        grouped["sample_fp_rate"] = rate_estimates.apply(lambda estimate: estimate[0])
        grouped["sample_source"] = rate_estimates.apply(lambda estimate: estimate[3])
        grouped["estimated_remaining_fp"] = (
            grouped["reference_total"] * grouped["sample_fp_rate"]
            - grouped["removed_known_fp"]
        ).clip(lower=0)
        grouped["false_positive_rate"] = (
            grouped["estimated_remaining_fp"] / grouped["current_total"]
        )
        grouped = grouped.sort_values("false_positive_rate", ascending=False).head(top_n)
        if grouped.empty:
            st.info("No checked papers available for this false-positive estimate.")
            return
        fig = px.bar(
            grouped,
            x="instrument",
            y="false_positive_rate",
            hover_data=[
                "current_total",
                "checked",
                "verified_false",
                "removed_known_fp",
                "estimated_remaining_fp",
                "sample_source",
            ],
            title="Estimated false-positive rate by instrument",
        )
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig, use_container_width=True)

    elif preset == "Instrument × year heatmap":
        exploded = explode_for_variable(df, "instrument")
        if exploded.empty:
            st.info("No instrument data available.")
            return
        pivot = (
            exploded.groupby(["instrument", "year"])["paper_id"]
            .nunique()
            .reset_index(name="papers")
            .pivot(index="instrument", columns="year", values="papers")
            .fillna(0)
        )
        if pivot.empty:
            st.info("No data to plot for the current filters.")
            return
        fig = px.imshow(
            pivot,
            labels=dict(x="Year", y="Instrument", color="Papers"),
            title="Instrument × year heatmap",
            aspect="auto",
        )
        st.plotly_chart(fig, use_container_width=True)

    elif preset == "Stacked papers per year by verification status":
        grouped = (
            df.groupby(["year", "verification_status"])["paper_id"]
            .nunique()
            .reset_index(name="papers")
        )
        fig = px.bar(
            grouped,
            x="year",
            y="papers",
            color="verification_status",
            title="Papers per year by verification status",
        )
        st.plotly_chart(fig, use_container_width=True)

    elif preset == "Author collaboration network":
        plot_cooccurrence_network(
            df,
            "authors",
            "Author collaboration network",
            top_n,
        )

    elif preset == "Instrument co-use network":
        plot_cooccurrence_network(
            df,
            "instruments",
            "Instrument co-use network",
            top_n,
        )

    elif preset == "Instrument overlap combinations":
        plot_instrument_overlap(df, top_n)

    elif preset == "Author timeline":
        plot_timeline_by_variable(df, "author", "Author", top_n)

    elif preset == "Instrument timeline":
        plot_timeline_by_variable(df, "instrument", "Instrument", top_n)


def plot_custom_graph(df: pd.DataFrame) -> None:
    """Simple user-selected graph builder."""
    variables = {
        "Year": "year",
        "Instrument": "instrument",
        "Author": "author",
        "Publisher": "publisher",
        "Journal": "journal",
        "Paper type": "paper_type",
        "Verification status": "verification_status",
        "GO-Canada status": "go_canada_status",
        "Source": "source",
    }

    chart_type = st.selectbox(
        "Chart type",
        ["Bar chart", "Line chart", "Pie chart", "Donut chart", "Stacked bar chart", "Heatmap"],
        key="custom_chart_type",
    )

    if chart_type == "Heatmap":
        c1, c2 = st.columns(2)
        with c1:
            x_label = st.selectbox("X variable", list(variables), index=0, key="custom_heatmap_x")
        with c2:
            y_label = st.selectbox("Y variable", list(variables), index=1, key="custom_heatmap_y")
        x_var = variables[x_label]
        y_var = variables[y_label]

        out = explode_for_variable(df, x_var)
        out = explode_for_variable(out, y_var)
        grouped = (
            out.groupby([y_var, x_var])["paper_id"].nunique().reset_index(name="papers")
        )
        if grouped.empty:
            st.info("No data to plot.")
            return
        pivot = grouped.pivot(index=y_var, columns=x_var, values="papers").fillna(0)
        fig = px.imshow(
            pivot,
            labels=dict(x=x_label, y=y_label, color="Papers"),
            title=f"{y_label} × {x_label} heatmap",
            aspect="auto",
        )
        st.plotly_chart(fig, use_container_width=True)
        return

    x_label = st.selectbox("Main variable", list(variables), key="custom_x_variable")
    x_var = variables[x_label]
    top_n = st.number_input("Top N categories", min_value=3, max_value=100, value=20, key="top_n")

    if chart_type == "Stacked bar chart":
        stack_options = [label for label in variables if label != x_label]
        stack_label = st.selectbox("Stack by", stack_options, key="custom_stack_variable")
        stack_var = variables[stack_label]

        out = explode_for_variable(df, x_var)
        out = explode_for_variable(out, stack_var)
        grouped = (
            out.groupby([x_var, stack_var])["paper_id"]
            .nunique()
            .reset_index(name="papers")
        )
        if grouped.empty:
            st.info("No data to plot.")
            return

        # Keep only top categories on the main x-axis.
        top_categories = (
            grouped.groupby(x_var)["papers"].sum().sort_values(ascending=False).head(top_n).index
        )
        grouped = grouped[grouped[x_var].isin(top_categories)]
        fig = px.bar(
            grouped,
            x=x_var,
            y="papers",
            color=stack_var,
            title=f"Papers by {x_label}, stacked by {stack_label}",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        counts = count_by_variable(df, x_var, int(top_n))
        plot_count_chart(counts, x_var, chart_type, f"Papers by {x_label}")


# -----------------------------------------------------------------------------
# Page rendering
# -----------------------------------------------------------------------------

def render_dashboard_page(
    filtered_df: pd.DataFrame,
    false_positive_reference_df: pd.DataFrame,
    estimate_population_df: pd.DataFrame,
    fallback_reference_df: pd.DataFrame,
) -> None:
    st.header("Dashboard")
    stats = compute_statistics(
        filtered_df,
        false_positive_reference_df,
        estimate_population_df,
        fallback_reference_df,
    )
    render_metric_grid(stats)

    st.subheader("Current filtered subset")
    st.write(
        "All summary cards, ranked lists, and graphs are calculated from the current filtered view."
    )

    render_top_lists(filtered_df, top_n=10)

    st.subheader("Fast visual summary")
    plot_preset_graph(
        filtered_df,
        "Papers per year",
        "Line chart",
        top_n=20,
        false_positive_reference_df=false_positive_reference_df,
        estimate_population_df=estimate_population_df,
        fallback_reference_df=fallback_reference_df,
    )


def render_filter_table_page(
    filtered_df: pd.DataFrame,
    false_positive_reference_df: pd.DataFrame,
    estimate_population_df: pd.DataFrame,
    fallback_reference_df: pd.DataFrame,
) -> None:
    st.header("Filter + Paper List")
    stats = compute_statistics(
        filtered_df,
        false_positive_reference_df,
        estimate_population_df,
        fallback_reference_df,
    )
    render_metric_grid(stats)

    st.subheader("Visible/exported columns")
    all_display_columns = [col for col in COLUMN_LABELS if col in filtered_df.columns]
    default_columns = [col for col in DEFAULT_VISIBLE_COLUMNS if col in all_display_columns]

    selected_columns = st.multiselect(
        "Choose columns",
        options=all_display_columns,
        default=st.session_state.get("selected_columns", default_columns) or default_columns,
        format_func=lambda col: COLUMN_LABELS.get(col, col),
        key="selected_columns",
    )

    st.subheader("Matching papers")
    if filtered_df.empty:
        st.info("No papers match the current filters.")
        return

    with st.expander("Manually exclude papers from this view", expanded=False):
        exclude_columns = [
            col
            for col in ["paper_id", "title", "year", "display_authors", "display_instruments"]
            if col in filtered_df.columns
        ]
        exclude_editor = filtered_df[exclude_columns].copy()
        exclude_editor.insert(0, "Exclude", False)
        edited_exclusions = st.data_editor(
            exclude_editor.rename(columns=COLUMN_LABELS),
            hide_index=True,
            use_container_width=True,
            disabled=[COLUMN_LABELS.get(col, col) for col in exclude_columns],
            key="manual_exclusion_editor",
        )
        selected_ids = edited_exclusions.loc[
            edited_exclusions["Exclude"],
            COLUMN_LABELS.get("paper_id", "paper_id"),
        ].astype(str).tolist()
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("Exclude selected", disabled=not selected_ids):
                st.session_state["pending_excluded_paper_ids"] = selected_ids
                st.rerun()
        with c2:
            if st.button(
                "Clear all manual paper exclusions",
                disabled=not st.session_state.get("excluded_paper_ids"),
            ):
                st.session_state["excluded_paper_ids"] = []
                st.rerun()

    table_df = filtered_df[selected_columns].rename(columns=COLUMN_LABELS)
    st.dataframe(table_df, use_container_width=True, hide_index=True)


def render_graphs_page(
    filtered_df: pd.DataFrame,
    false_positive_reference_df: pd.DataFrame,
    estimate_population_df: pd.DataFrame,
    fallback_reference_df: pd.DataFrame,
) -> None:
    st.header("Graphs")
    st.write("Graphs update automatically based on the current filters.")

    graph_mode = st.radio(
        "Graph mode",
        ["Preset graph", "Custom graph builder"],
        horizontal=True,
        key="graph_mode",
    )

    if graph_mode == "Preset graph":
        preset_options = [
            "Papers per year",
            "Papers by instrument",
            "Papers by publisher",
            "Papers by journal",
            "Papers by author",
            "Verified vs unchecked papers",
            "False-positive rate by instrument",
            "Raw vs cleaned count",
            "Instrument × year heatmap",
            "Stacked papers per year by verification status",
            "Author collaboration network",
            "Instrument co-use network",
            "Instrument overlap combinations",
            "Author timeline",
            "Instrument timeline",
        ]
        preset = st.selectbox("Graph preset", preset_options, key="graph_preset")

        chart_options = ["Bar chart", "Line chart", "Pie chart", "Donut chart"]
        if preset in {"False-positive rate by instrument", "Raw vs cleaned count"}:
            chart_options = ["Bar chart"]
        elif preset == "Instrument × year heatmap":
            chart_options = ["Heatmap"]
        elif preset == "Stacked papers per year by verification status":
            chart_options = ["Stacked bar chart"]
        elif preset in {"Author collaboration network", "Instrument co-use network"}:
            chart_options = ["Network"]
        elif preset == "Instrument overlap combinations":
            chart_options = ["Overlap bar chart"]
        elif preset in {"Author timeline", "Instrument timeline"}:
            chart_options = ["Line chart"]
        elif preset == "Papers per year":
            chart_options = ["Line chart", "Bar chart"]

        chart_type = st.selectbox("Chart type", chart_options)
        top_n = st.number_input("Top N categories", min_value=3, max_value=100, value=20, key="top_n")
        plot_preset_graph(
            filtered_df,
            preset,
            chart_type,
            int(top_n),
            false_positive_reference_df=false_positive_reference_df,
            estimate_population_df=estimate_population_df,
            fallback_reference_df=fallback_reference_df,
        )
    else:
        plot_custom_graph(filtered_df)

    with st.expander("Advanced graph notes"):
        st.markdown(
            """
            These advanced views use the same filtered paper set as the rest of the app:

            - **Author collaboration network** connects authors who appear on the same paper.
            - **Instrument co-use network** connects instruments used in the same paper.
            - **Instrument overlap combinations** shows exact instrument combinations across papers.
            """
        )


def render_data_quality_page(filtered_df: pd.DataFrame) -> None:
    st.header("Data Quality")

    duplicates = detect_duplicate_papers(filtered_df)
    missing_detail, missing_summary = missing_metadata_report(filtered_df)

    c1, c2, c3 = st.columns(3)
    c1.metric("Possible duplicate rows", f"{len(duplicates):,}")
    c2.metric("Papers missing metadata", f"{len(missing_detail):,}")
    c3.metric("Papers scanned", f"{len(filtered_df):,}")

    st.subheader("Possible duplicates")
    if duplicates.empty:
        st.success("No duplicate DOI or exact-title matches found in the current filtered view.")
    else:
        st.dataframe(duplicates, use_container_width=True, hide_index=True)
        st.download_button(
            label="Download duplicate_report.csv",
            data=duplicates.to_csv(index=False).encode("utf-8"),
            file_name="duplicate_report.csv",
            mime="text/csv",
        )

    st.subheader("Missing metadata summary")
    summary_display = missing_summary.copy()
    summary_display["missing_percent"] = summary_display["missing_percent"].map("{:.1%}".format)
    st.dataframe(summary_display, use_container_width=True, hide_index=True)

    st.subheader("Papers with missing metadata")
    if missing_detail.empty:
        st.success("No missing metadata found in the current filtered view.")
    else:
        st.dataframe(missing_detail, use_container_width=True, hide_index=True)
        st.download_button(
            label="Download missing_metadata_report.csv",
            data=missing_detail.to_csv(index=False).encode("utf-8"),
            file_name="missing_metadata_report.csv",
            mime="text/csv",
        )


def review_year_bounds(summary_df: pd.DataFrame, detail_df: pd.DataFrame) -> tuple[int, int] | None:
    """Return usable year bounds for the review database."""
    years = pd.concat(
        [
            pd.to_numeric(summary_df.get("year", pd.Series(dtype="object")), errors="coerce"),
            pd.to_numeric(detail_df.get("year", pd.Series(dtype="object")), errors="coerce"),
        ],
        ignore_index=True,
    ).dropna()
    if years.empty:
        return None
    return int(years.min()), int(years.max())


def apply_review_filters(
    summary_df: pd.DataFrame,
    detail_df: pd.DataFrame,
    *,
    text_query: str,
    paper_statuses: list[str],
    instruments: list[str],
    year_range: tuple[int, int] | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply shared review database filters to paper and assignment exports."""
    summary = summary_df.copy()
    detail = detail_df.copy()

    if text_query:
        query = text_query.lower().strip()
        summary_text = (
            summary["DOI"].fillna("").astype(str)
            + " "
            + summary["title"].fillna("").astype(str)
            + " "
            + summary["authors"].fillna("").astype(str)
        ).str.lower()
        detail_text = (
            detail["DOI"].fillna("").astype(str)
            + " "
            + detail["title"].fillna("").astype(str)
            + " "
            + detail["authors"].fillna("").astype(str)
        ).str.lower()
        summary = summary[summary_text.str.contains(query, na=False)]
        detail = detail[detail_text.str.contains(query, na=False)]

    if paper_statuses:
        summary = summary[summary["paper_review_status"].isin(paper_statuses)]
        status_dois = set(summary["DOI"].fillna("").astype(str))
        detail = detail[detail["DOI"].fillna("").astype(str).isin(status_dois)]

    if instruments:
        summary = summary[summary["instruments"].apply(lambda value: review_contains_any(value, instruments))]
        detail = detail[detail["instrument"].isin(instruments)]

    if year_range:
        year_start, year_end = year_range
        summary_year = pd.to_numeric(summary["year"], errors="coerce")
        detail_year = pd.to_numeric(detail["year"], errors="coerce")
        summary = summary[summary_year.between(year_start, year_end, inclusive="both")]
        detail = detail[detail_year.between(year_start, year_end, inclusive="both")]

    return summary.reset_index(drop=True), detail.reset_index(drop=True)


def render_review_database_page(review_tables: dict[str, pd.DataFrame]) -> None:
    st.header("Review Database")
    summary_df = review_tables["summary"]
    detail_df = review_tables["detail"]

    if summary_df.empty and detail_df.empty:
        st.info("No review database CSVs were found in data/review.")
        return

    all_instruments = sorted_options(
        list(detail_df.get("instrument", pd.Series(dtype="object")))
        + [
            item
            for value in summary_df.get("instruments", pd.Series(dtype="object"))
            for item in split_review_list(value)
        ]
    )
    paper_status_options = [
        status
        for status in REVIEW_PAPER_STATUS_ORDER
        if status in set(summary_df.get("paper_review_status", pd.Series(dtype="object")))
    ]
    if not paper_status_options:
        paper_status_options = sorted_options(summary_df.get("paper_review_status", []))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Papers", f"{len(summary_df):,}")
    c2.metric("Verified papers", f"{int((summary_df['paper_review_status'] == 'verified').sum()):,}")
    c3.metric(
        "Partially verified",
        f"{int((summary_df['paper_review_status'] == 'partially_verified').sum()):,}",
    )
    c4.metric("Unverified papers", f"{int((summary_df['paper_review_status'] == 'unverified').sum()):,}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Paper-instrument rows", f"{len(detail_df):,}")
    c6.metric("Verified assignments", f"{int((detail_df['review_status'] == 'verified').sum()):,}")
    c7.metric("Unverified assignments", f"{int((detail_df['review_status'] == 'unverified').sum()):,}")
    c8.metric("Instruments", f"{len(all_instruments):,}")

    with st.expander("Review database filters", expanded=True):
        f1, f2 = st.columns(2)
        with f1:
            text_query = st.text_input("Search DOI, title, or author", key="review_text_query")
            selected_statuses = st.multiselect(
                "Paper review status",
                paper_status_options,
                key="review_paper_statuses",
            )
        with f2:
            selected_instruments = st.multiselect(
                "Instrument",
                all_instruments,
                key="review_instruments",
            )
            bounds = review_year_bounds(summary_df, detail_df)
            if bounds and bounds[0] != bounds[1]:
                default_range = st.session_state.get("review_year_range", bounds)
                if not isinstance(default_range, (list, tuple)) or len(default_range) != 2:
                    default_range = bounds
                year_range = st.slider(
                    "Year range",
                    min_value=bounds[0],
                    max_value=bounds[1],
                    value=(max(bounds[0], int(default_range[0])), min(bounds[1], int(default_range[1]))),
                    key="review_year_range",
                )
            else:
                year_range = bounds

    filtered_summary, filtered_detail = apply_review_filters(
        summary_df,
        detail_df,
        text_query=text_query,
        paper_statuses=selected_statuses,
        instruments=selected_instruments,
        year_range=year_range,
    )

    st.caption(
        f"Showing {len(filtered_summary):,} papers and "
        f"{len(filtered_detail):,} paper-instrument assignments."
    )

    summary_tab, detail_tab = st.tabs(["Paper DOI list", "Paper-instrument list"])
    with summary_tab:
        summary_columns = [
            "DOI",
            "title",
            "year",
            "journal",
            "publisher",
            "paper_type",
            "authors",
            "instruments",
            "paper_review_status",
            "reviewed_instruments",
            "total_instruments",
        ]
        st.dataframe(
            filtered_summary[summary_columns],
            use_container_width=True,
            hide_index=True,
        )
        st.download_button(
            label="Download paper_verification_summary.csv",
            data=filtered_summary.to_csv(index=False).encode("utf-8"),
            file_name="paper_verification_summary.csv",
            mime="text/csv",
        )

    with detail_tab:
        assignment_status_options = [
            status
            for status in REVIEW_ASSIGNMENT_STATUS_ORDER
            if status in set(filtered_detail.get("review_status", pd.Series(dtype="object")))
        ]
        if not assignment_status_options:
            assignment_status_options = sorted_options(filtered_detail.get("review_status", []))
        selected_assignment_statuses = st.multiselect(
            "Assignment review status",
            assignment_status_options,
            key="review_assignment_statuses",
        )
        detail_display = filtered_detail.copy()
        if selected_assignment_statuses:
            detail_display = detail_display[
                detail_display["review_status"].isin(selected_assignment_statuses)
            ]

        detail_columns = [
            "DOI",
            "title",
            "year",
            "instrument",
            "all_instruments_on_paper",
            "instrument_status",
            "review_status",
            "review_decision",
            "corrected_instrument",
            "reviewed_at",
            "paper_url",
        ]
        st.dataframe(
            detail_display[detail_columns],
            use_container_width=True,
            hide_index=True,
            column_config={"paper_url": st.column_config.LinkColumn("paper_url")},
        )
        st.download_button(
            label="Download paper_instrument_verification_status.csv",
            data=detail_display.to_csv(index=False).encode("utf-8"),
            file_name="paper_instrument_verification_status.csv",
            mime="text/csv",
        )


def render_add_import_papers_page(
    tables: dict[str, pd.DataFrame],
    *,
    admin_mode: bool = False,
) -> None:
    st.header("Add / Import Papers")
    if READ_ONLY_MODE and not supabase_config():
        st.info(
            "Adding and importing papers is disabled in the hosted read-only version. "
            "Configure Supabase to save online edits permanently."
        )
        return
    if READ_ONLY_MODE and not admin_mode:
        st.info("Use the password-protected Admin Editor to make online changes.")
        return

    if "last_import_results" in st.session_state:
        results = pd.DataFrame(st.session_state.pop("last_import_results"))
        added = int((results["result"] == "added").sum()) if not results.empty else 0
        skipped = int((results["result"] == "skipped").sum()) if not results.empty else 0
        st.success(f"Import complete: {added} added, {skipped} skipped.")
        st.dataframe(results, use_container_width=True, hide_index=True)

    bulk_tab, manual_tab = st.tabs(["Bulk CSV import", "Manual entry"])

    with bulk_tab:
        st.subheader("Bulk CSV import")
        template = pd.DataFrame(
            [
                {
                    "DOI": "10.0000/example-new",
                    "title": "Example imported paper",
                    "year": "2026",
                    "journal": "Example Journal",
                    "publisher": "Example Publisher",
                    "paper_type": "Research article",
                    "go_canada_status": "candidate",
                    "is_known_false_positive": "false",
                    "authors": "First Author; Second Author",
                    "instruments": "REGO; NORSTAR Riometers",
                    "instrument_status": "uses; uses",
                    "verification_status": "unchecked",
                    "evidence_quote": "",
                    "checked_date": "",
                    "notes": "",
                    "source_name": "New import batch",
                    "source_type": "csv_import",
                    "source_notes": "Imported from interface",
                }
            ]
        )
        st.download_button(
            label="Download import template CSV",
            data=template.to_csv(index=False).encode("utf-8"),
            file_name="paper_import_template.csv",
            mime="text/csv",
        )

        uploaded_file = st.file_uploader("Upload paper CSV", type=["csv"])
        if uploaded_file is not None:
            try:
                uploaded_df = pd.read_csv(uploaded_file)
                normalized_preview = normalize_import_columns(uploaded_df)
                st.caption(f"Rows detected: {len(normalized_preview):,}")
                st.dataframe(normalized_preview.head(25), use_container_width=True, hide_index=True)

                if st.button("Import uploaded CSV", type="primary"):
                    working_tables = {name: table.copy() for name, table in tables.items()}
                    results = import_papers_from_dataframe(working_tables, uploaded_df)
                    if (results["result"] == "added").any():
                        save_database_tables(working_tables)
                    st.session_state["last_import_results"] = results.to_dict("records")
                    st.rerun()
            except Exception as exc:
                st.error(f"Could not import CSV: {exc}")

    with manual_tab:
        st.subheader("Manual paper entry")
        with st.form("manual_paper_form", clear_on_submit=False):
            c1, c2 = st.columns(2)
            with c1:
                title = st.text_input("Title *")
                doi = st.text_input("DOI")
                year = st.number_input("Year", min_value=1800, max_value=2200, value=datetime.now().year)
                journal = st.text_input("Journal")
                publisher = st.text_input("Publisher")
            with c2:
                paper_type = st.text_input("Paper type", value="Research article")
                go_canada_status = st.text_input("GO-Canada status", value="candidate")
                is_known_false_positive = st.checkbox("Known false positive")
                verification_status = st.selectbox(
                    "Verification status",
                    ["unchecked", "verified_true", "verified_false", "unsure"],
                )
                checked_date = st.date_input("Checked date", value=datetime.now().date())

            authors = st.text_input("Authors", help="Separate multiple authors with semicolons.")
            instruments = st.text_input("Instruments", help="Separate multiple instruments with semicolons.")
            instrument_status = st.text_input(
                "Instrument status",
                value="unchecked",
                help="Use one value or semicolon-separated values matching the instruments.",
            )
            source_name = st.text_input("Source / origin", value="Manual entry")
            source_type = st.text_input("Source type", value="manual")
            evidence_quote = st.text_area("Evidence quote")
            notes = st.text_area("Notes")

            submitted = st.form_submit_button("Add paper", type="primary")
            if submitted:
                record = {
                    "DOI": doi,
                    "title": title,
                    "year": year,
                    "journal": journal,
                    "publisher": publisher,
                    "paper_type": paper_type,
                    "go_canada_status": go_canada_status,
                    "is_known_false_positive": is_known_false_positive,
                    "authors": authors,
                    "instruments": instruments,
                    "instrument_status": instrument_status,
                    "verification_status": verification_status,
                    "checked_date": checked_date.isoformat(),
                    "evidence_quote": evidence_quote,
                    "notes": notes,
                    "source_name": source_name,
                    "source_type": source_type,
                    "source_notes": "Added through manual entry form",
                }
                working_tables = {name: table.copy() for name, table in tables.items()}
                added, message = add_paper_record(working_tables, record)
                if added:
                    save_database_tables(working_tables)
                    st.session_state["last_import_results"] = [
                        {
                            "csv_row": "",
                            "title": title,
                            "DOI": doi,
                            "result": "added",
                            "message": message,
                        }
                    ]
                    st.rerun()
                else:
                    st.error(f"Paper was not added: {message}")


def render_admin_login() -> bool:
    """Render admin login and return whether this session is authenticated."""
    if not admin_password_configured():
        st.warning(
            "Admin editing is disabled because GO_CANADA_ADMIN_PASSWORD is not configured."
        )
        return False

    if admin_is_authenticated():
        c1, c2 = st.columns([3, 1])
        c1.success("Admin access unlocked for this session.")
        if c2.button("Log out"):
            st.session_state["admin_authenticated"] = False
            st.rerun()
        return True

    with st.form("admin_login_form"):
        password = st.text_input("Admin password", type="password")
        submitted = st.form_submit_button("Unlock editor", type="primary")
        if submitted:
            expected_password = get_config_value("GO_CANADA_ADMIN_PASSWORD")
            if password == expected_password:
                st.session_state["admin_authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    return False


def paper_label(row: pd.Series) -> str:
    """Build a compact label for selecting papers."""
    title = clean_text(row.get("title"))
    doi = clean_text(row.get("DOI"))
    year = clean_text(row.get("year"))
    left = f"{year} | " if year else ""
    right = f" | {doi}" if doi else ""
    return f"{left}{title[:110]}{right}"


def render_verification_editor(tables: dict[str, pd.DataFrame], paper_view: pd.DataFrame) -> None:
    """Render a simple editor for paper-instrument verification rows."""
    st.subheader("Change Verification Status")
    if paper_view.empty:
        st.info("No papers are loaded.")
        return

    search_text = st.text_input("Find paper by title, DOI, or author", key="admin_verify_search")
    candidates = paper_view.copy()
    if search_text.strip():
        query = search_text.lower().strip()
        haystack = (
            candidates["DOI"].fillna("").astype(str)
            + " "
            + candidates["title"].fillna("").astype(str)
            + " "
            + candidates["display_authors"].fillna("").astype(str)
        ).str.lower()
        candidates = candidates[haystack.str.contains(query, na=False)]

    candidates = candidates.sort_values(["year", "title"], ascending=[False, True]).head(250)
    if candidates.empty:
        st.info("No papers match that search.")
        return

    paper_options = candidates["paper_id"].tolist()
    label_by_id = {
        row["paper_id"]: paper_label(row)
        for _, row in candidates.iterrows()
    }
    selected_paper_id = st.selectbox(
        "Paper",
        paper_options,
        format_func=lambda paper_id: label_by_id.get(paper_id, paper_id),
        key="admin_verify_paper",
    )

    selected_paper = paper_view[paper_view["paper_id"] == selected_paper_id].iloc[0]
    st.write(f"**Title:** {clean_text(selected_paper['title'])}")
    st.write(f"**DOI:** {clean_text(selected_paper['DOI']) or 'Missing'}")
    st.write(f"**Current paper status:** {clean_text(selected_paper['verification_status'])}")

    paper_instruments = tables["paper_instruments"]
    instruments = tables["instruments"]
    assignments = paper_instruments[
        paper_instruments["paper_id"].fillna("").astype(str) == selected_paper_id
    ].merge(instruments, on="instrument_id", how="left")
    if assignments.empty:
        st.info("This paper has no instrument assignments.")
        return

    instrument_options = assignments["instrument_id"].astype(str).tolist()
    instrument_labels = dict(
        zip(
            assignments["instrument_id"].astype(str),
            assignments["instrument_name"].fillna("").astype(str),
        )
    )
    selected_instrument_id = st.selectbox(
        "Instrument assignment",
        instrument_options,
        format_func=lambda instrument_id: instrument_labels.get(instrument_id, instrument_id),
        key="admin_verify_instrument",
    )

    existing = tables["verification"].copy()
    existing = existing[
        (existing["paper_id"].fillna("").astype(str) == selected_paper_id)
        & (existing["instrument_id"].fillna("").astype(str) == selected_instrument_id)
    ]
    existing_row = existing.iloc[0] if not existing.empty else pd.Series(dtype="object")
    current_status = normalize_status(existing_row.get("status", "unchecked"))
    status_options = ["unchecked", "verified_true", "verified_false", "unsure"]
    default_status_index = status_options.index(current_status) if current_status in status_options else 0

    with st.form("admin_verification_form"):
        new_status = st.selectbox(
            "Verification status",
            status_options,
            index=default_status_index,
        )
        evidence_quote = st.text_area(
            "Evidence quote",
            value=clean_text(existing_row.get("evidence_quote")),
        )
        notes = st.text_area("Notes", value=clean_text(existing_row.get("notes")))
        checked_date = st.text_input(
            "Checked date/time",
            value=clean_text(existing_row.get("checked_date")) or datetime.now().isoformat(timespec="seconds"),
        )
        submitted = st.form_submit_button("Save verification status", type="primary")

    if submitted:
        try:
            save_verification_row(
                tables,
                selected_paper_id,
                selected_instrument_id,
                new_status,
                evidence_quote,
                checked_date,
                notes,
            )
            st.success("Verification status saved.")
            st.rerun()
        except requests.HTTPError as exc:
            response = exc.response
            detail = response.text if response is not None else str(exc)
            st.error(f"Supabase rejected the verification update: {detail}")
        except Exception as exc:
            st.error(f"Could not save verification status: {exc}")


def render_database_sync_page(tables: dict[str, pd.DataFrame]) -> None:
    """Render backend setup and sync controls."""
    st.subheader("Online Database")
    st.write(f"Current backend: **{database_backend_label()}**")

    if not supabase_config():
        st.info(
            "Supabase is not configured yet. The editor can still work locally, "
            "but hosted online changes need Supabase secrets."
        )
        st.code(
            "\n".join(
                [
                    'GO_CANADA_ADMIN_PASSWORD = "choose-a-password"',
                    'SUPABASE_URL = "https://your-project.supabase.co"',
                    'SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"',
                ]
            ),
            language="toml",
        )
        return

    st.success("Supabase is configured. Admin saves will update the online database.")
    st.warning(
        "The sync button replaces the Supabase tables with the CSV database currently in this repository."
    )
    if st.button("Seed / replace Supabase from repository CSVs", type="primary"):
        csv_tables = load_csv_database(str(DATA_DIR))
        replace_supabase_database(csv_tables)
        st.success("Supabase was replaced with the repository CSV database.")
        st.rerun()

    st.download_button(
        label="Download current papers table",
        data=tables["papers"].to_csv(index=False).encode("utf-8"),
        file_name="papers.csv",
        mime="text/csv",
    )


def render_admin_editor_page(tables: dict[str, pd.DataFrame], paper_view: pd.DataFrame) -> None:
    """Render password-protected database editing tools."""
    st.header("Admin Editor")
    if not render_admin_login():
        return

    if READ_ONLY_MODE and not supabase_config():
        st.warning(
            "Hosted read-only mode is enabled and Supabase is not configured, "
            "so changes cannot be saved permanently online yet."
        )

    st.caption(f"Database backend: {database_backend_label()}")
    add_tab, verify_tab, sync_tab = st.tabs(
        ["Add / Import Papers", "Verification Status", "Online Database"]
    )
    with add_tab:
        render_add_import_papers_page(tables, admin_mode=True)
    with verify_tab:
        render_verification_editor(tables, paper_view)
    with sync_tab:
        render_database_sync_page(tables)


def render_export_page(
    filtered_df: pd.DataFrame,
    filters: dict[str, Any],
    false_positive_reference_df: pd.DataFrame,
    estimate_population_df: pd.DataFrame,
    fallback_reference_df: pd.DataFrame,
) -> None:
    st.header("Export")
    stats = compute_statistics(
        filtered_df,
        false_positive_reference_df,
        estimate_population_df,
        fallback_reference_df,
    )
    render_metric_grid(stats)

    all_display_columns = [col for col in COLUMN_LABELS if col in filtered_df.columns]
    default_columns = [col for col in DEFAULT_VISIBLE_COLUMNS if col in all_display_columns]

    selected_columns = st.multiselect(
        "Columns to export",
        options=all_display_columns,
        default=st.session_state.get("selected_columns", default_columns) or default_columns,
        format_func=lambda col: COLUMN_LABELS.get(col, col),
        key="export_selected_columns",
    )

    export_df = filtered_df[selected_columns].rename(columns=COLUMN_LABELS) if selected_columns else filtered_df
    csv_bytes = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download current filtered view as CSV",
        data=csv_bytes,
        file_name="go_canada_filtered_papers.csv",
        mime="text/csv",
    )

    st.subheader("Optional filter summary CSV")
    summary_df = pd.DataFrame(filters_to_summary_rows(filters, stats))
    st.dataframe(summary_df, use_container_width=True, hide_index=True)
    summary_bytes = summary_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download filter_summary.csv",
        data=summary_bytes,
        file_name="filter_summary.csv",
        mime="text/csv",
    )


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="📊", layout="wide")
    st.title(APP_TITLE)
    st.caption(
        "Filter and analyze an existing GO-Canada publication database. No online searching is performed."
    )
    if READ_ONLY_MODE:
        st.info(
            "Hosted read-only mode is enabled. Filtering, graphs, data quality checks, "
            "and exports work normally. Password-protected online editing works when Supabase is configured."
        )

    tables = load_database(str(DATA_DIR))
    paper_view = build_paper_view(tables)
    review_tables = load_review_database(str(REVIEW_DIR))
    review_summary = review_tables["summary"]
    review_detail = review_tables["detail"]

    if paper_view.empty and review_summary.empty and review_detail.empty:
        st.error(
            "No papers loaded. Add CSV files to the data/ folder, starting with data/papers.csv."
        )
        st.stop()

    page_options = [
        "Dashboard",
        "Review Database",
        "Filter + Paper List",
        "Graphs",
        "Data Quality",
        "Export",
    ]
    if paper_view.empty:
        page_options = ["Review Database"]
    elif not READ_ONLY_MODE:
        page_options.insert(4, "Add / Import Papers")
    if admin_password_configured():
        page_options.append("Admin Editor")
    page = st.sidebar.radio("Page", page_options)

    if page == "Review Database":
        st.sidebar.divider()
        st.sidebar.caption(f"Review papers: {len(review_summary):,}")
        st.sidebar.caption(f"Review assignments: {len(review_detail):,}")
        render_review_database_page(review_tables)
        return
    if page == "Admin Editor":
        st.sidebar.divider()
        st.sidebar.caption(f"Database backend: {database_backend_label()}")
        render_admin_editor_page(tables, paper_view)
        return

    render_saved_view_controls()
    filters = render_filters(paper_view)
    false_positive_reference_df = apply_filters(
        paper_view,
        filters,
        remove_known_false_positives=False,
        apply_verification_filter=False,
    )
    estimate_population_df = apply_filters(
        paper_view,
        filters,
        apply_verification_filter=False,
    )
    filtered_df = apply_filters(paper_view, filters)

    st.sidebar.divider()
    st.sidebar.caption(f"Loaded papers: {len(paper_view):,}")
    st.sidebar.caption(f"Current filtered papers: {len(filtered_df):,}")

    if page == "Dashboard":
        render_dashboard_page(
            filtered_df,
            false_positive_reference_df,
            estimate_population_df,
            paper_view,
        )
    elif page == "Filter + Paper List":
        render_filter_table_page(
            filtered_df,
            false_positive_reference_df,
            estimate_population_df,
            paper_view,
        )
    elif page == "Graphs":
        render_graphs_page(
            filtered_df,
            false_positive_reference_df,
            estimate_population_df,
            paper_view,
        )
    elif page == "Data Quality":
        render_data_quality_page(filtered_df)
    elif page == "Add / Import Papers":
        render_add_import_papers_page(tables)
    elif page == "Export":
        render_export_page(
            filtered_df,
            filters,
            false_positive_reference_df,
            estimate_population_df,
            paper_view,
        )


if __name__ == "__main__":
    main()
