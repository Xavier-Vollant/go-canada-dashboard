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
import inspect
import random
import re
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
DEFAULT_DATABASE_ID = "main"
DATABASE_ID_COLUMN = "database_id"
DATABASES = [
    {
        "id": "main",
        "label": "Main database",
        "description": "Current GO-Canada dashboard database.",
    },
    {
        "id": "library",
        "label": "Library database",
        "description": "Empty database reserved for library records.",
    },
    {
        "id": "john",
        "label": "John database",
        "description": "Empty database reserved for John's records.",
    },
]
DATABASE_LABELS = {database["id"]: database["label"] for database in DATABASES}
VALID_DATABASE_IDS = {database["id"] for database in DATABASES}


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
SUPABASE_DASHBOARD_VIEW_NAME = "paper_dashboard_view"
GLOBAL_PRESET_COLUMNS = ["preset_name", "preset_json", "updated_at"]

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

SUPABASE_SCOPED_PRIMARY_KEY_COLUMNS = {
    name: [DATABASE_ID_COLUMN] + columns
    for name, columns in TABLE_PRIMARY_KEY_COLUMNS.items()
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
ADDITIONAL_INSTRUMENT_FILTER_OPTIONS = ["SMILE ASI", "IRIS"]

FILTER_WIDGET_KEYS = [
    "selected_instruments",
    "selected_authors",
    "selected_publishers",
    "selected_journals",
    "selected_paper_types",
    "selected_verification_statuses",
    "selected_go_canada_statuses",
    "selected_sources",
    "paper_search_query",
    "combined_filter_groups",
    "combined_filter_result_mode",
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
    "display_instrument_verification",
    "paper_type",
    "verification_status",
    "evidence_quote",
    "paper_url",
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
    "display_instrument_verification": "Instrument verification",
    "verification_status": "Verification status",
    "evidence_quote": "Evidence quote",
    "checked_date": "Checked date",
    "paper_url": "Open paper",
    "display_sources": "Source / origin",
    "notes": "Notes",
}

PAPER_VIEW_COLUMNS = list(
    dict.fromkeys(
        list(COLUMN_LABELS.keys())
        + [
            "authors",
            "instruments",
            "instrument_statuses",
            "all_verification_statuses",
            "instrument_verification_pairs",
            "sources",
            "source_types",
        ]
    )
)

STATUS_ORDER = ["verified_true", "verified_false", "unsure", "unchecked"]
INHERITABLE_VERIFICATION_STATUSES = {"verified_true", "verified_false", "unsure"}
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
    if isinstance(value, (list, tuple, set)):
        return "; ".join(clean_text(item) for item in value if clean_text(item))
    if isinstance(value, dict):
        return json.dumps(value)
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        if not value:
            return ""
    if value is None:
        return ""
    return str(value).strip()


def parse_bool(value: Any) -> bool:
    """Parse common CSV boolean values."""
    if isinstance(value, bool):
        return value
    return clean_text(value).lower() in {"true", "1", "yes", "y", "known_false_positive"}


def bool_storage_text(value: Any) -> str:
    """Return a stable text value for boolean fields stored in CSV/Supabase tables."""
    return "true" if parse_bool(value) else "false"


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


def paper_level_verification_from_go_canada_status(value: Any) -> str:
    """Map paper-level GO Canada labels to dashboard verification labels."""
    status = clean_text(value).lower().replace("-", "_").replace(" ", "_")
    if status in {"yes", "go_canada", "verified_true", "true", "confirmed"}:
        return "verified_true"
    if status in {"no", "not_go_canada", "verified_false", "false", "excluded"}:
        return "verified_false"
    if status in {"unsure", "maybe", "uncertain"}:
        return "unsure"
    return "unchecked"


def go_canada_status_from_paper_level_verification(value: Any) -> str:
    """Store paper-level verification in the existing GO Canada status field."""
    status = normalize_status(value)
    if status == "verified_true":
        return "yes"
    if status == "verified_false":
        return "no"
    if status == "unsure":
        return "unsure"
    return "unknown"


def contains_any(items: list[str], selected: list[str]) -> bool:
    """Return True if a list field contains at least one selected value."""
    if not selected:
        return True
    return any(item in items for item in selected)


def sorted_options(values: Iterable[Any]) -> list[str]:
    """Return clean sorted options for Streamlit widgets."""
    return sorted(unique_preserve_order(values), key=lambda x: x.lower())


def streamlit_widget_accepts_new_options(widget: Any) -> bool:
    """Return whether this Streamlit version supports typed custom options."""
    try:
        return "accept_new_options" in inspect.signature(widget).parameters
    except (TypeError, ValueError):
        return False


def ensure_options_include(options: Iterable[Any], values: Iterable[Any]) -> list[str]:
    """Return sorted options that include current/default values."""
    return sorted_options(list(options) + list(values))


def metadata_selectbox(
    label: str,
    options: Iterable[Any],
    value: Any = "",
    *,
    key: str,
    help: str | None = None,
) -> str:
    """Render a searchable single-value metadata picker that can accept new text."""
    current_value = clean_text(value)
    option_list = ensure_options_include(options, [current_value])
    if not option_list:
        option_list = [""]
    index = option_list.index(current_value) if current_value in option_list else 0
    kwargs = {
        "label": label,
        "options": option_list,
        "index": index,
        "key": key,
        "help": help,
        "placeholder": f"Search or add {label.lower()}",
    }
    if streamlit_widget_accepts_new_options(st.selectbox):
        kwargs["accept_new_options"] = True
    return clean_text(st.selectbox(**kwargs))


def metadata_multiselect(
    label: str,
    options: Iterable[Any],
    values: Any = "",
    *,
    key: str,
    help: str | None = None,
) -> str:
    """Render a searchable multi-value metadata picker that stores semicolon text."""
    selected_values = unique_preserve_order(split_multi_value(values))
    option_list = ensure_options_include(options, selected_values)
    if not option_list:
        option_list = []
    kwargs = {
        "label": label,
        "options": option_list,
        "default": selected_values,
        "key": key,
        "help": help,
        "placeholder": f"Search or add {label.lower()}",
    }
    if streamlit_widget_accepts_new_options(st.multiselect):
        kwargs["accept_new_options"] = True
    return join_list(st.multiselect(**kwargs))


def doi_to_url(doi: Any) -> str:
    """Build a DOI landing-page URL when a DOI exists."""
    text = clean_text(doi)
    if not text:
        return ""
    if text.lower().startswith(("http://", "https://")):
        return text
    return f"https://doi.org/{text}"


def doi_match_key(value: Any) -> str:
    """Normalize DOI values for matching the same paper across databases."""
    text = clean_text(value).lower()
    text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text)
    text = re.sub(r"^doi:\s*", "", text)
    return text.strip()


def paper_search_mask(df: pd.DataFrame, query: str) -> pd.Series:
    """Return rows matching a simple text search across paper metadata."""
    if not query.strip():
        return pd.Series(True, index=df.index)

    query = query.lower().strip()
    searchable = (
        df["DOI"].fillna("").astype(str)
        + " "
        + df["title"].fillna("").astype(str)
        + " "
        + df["journal"].fillna("").astype(str)
        + " "
        + df["publisher"].fillna("").astype(str)
        + " "
        + df["paper_type"].fillna("").astype(str)
        + " "
        + df["display_authors"].fillna("").astype(str)
        + " "
        + df["display_instruments"].fillna("").astype(str)
    ).str.lower()
    return searchable.str.contains(query, na=False)


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


def normalize_database_id(database_id: Any) -> str:
    """Return a known database id, falling back to the main database."""
    database_id = clean_text(database_id) or DEFAULT_DATABASE_ID
    if database_id not in VALID_DATABASE_IDS:
        return DEFAULT_DATABASE_ID
    return database_id


def database_label(database_id: Any) -> str:
    """Return the display label for a database id."""
    return DATABASE_LABELS.get(normalize_database_id(database_id), DATABASE_LABELS[DEFAULT_DATABASE_ID])


def active_database_id() -> str:
    """Return the currently selected dashboard database."""
    return normalize_database_id(st.session_state.get("active_database_id", DEFAULT_DATABASE_ID))


def database_data_dir(database_id: Any) -> Path:
    """Return the CSV directory for one dashboard database."""
    database_id = normalize_database_id(database_id)
    if database_id == DEFAULT_DATABASE_ID:
        return DATA_DIR
    return DATA_DIR / "databases" / database_id


def clear_database_view_state() -> None:
    """Clear filter/view widgets when switching isolated databases."""
    keys_to_clear = (
        FILTER_WIDGET_KEYS
        + VIEW_WIDGET_KEYS
        + [
            "last_import_results",
            "pending_excluded_paper_ids",
            "selected_columns",
        ]
    )
    for key in keys_to_clear:
        st.session_state.pop(key, None)


def render_database_selector() -> str:
    """Render the sidebar database selector and return the active database id."""
    st.sidebar.subheader("Database")
    show_other_databases = st.sidebar.toggle(
        "Show other databases",
        value=bool(st.session_state.get("show_other_databases", False)),
        key="show_other_databases",
        help="Library database and John database are hidden until this is enabled.",
    )

    previous_database_id = active_database_id()
    if show_other_databases:
        database_ids = [database["id"] for database in DATABASES]
        selected_database_id = st.sidebar.selectbox(
            "Active database",
            database_ids,
            index=database_ids.index(previous_database_id)
            if previous_database_id in database_ids
            else database_ids.index(DEFAULT_DATABASE_ID),
            format_func=database_label,
            key="database_selector",
        )
    else:
        selected_database_id = DEFAULT_DATABASE_ID
        st.sidebar.caption(f"Active database: {database_label(selected_database_id)}")

    selected_database_id = normalize_database_id(selected_database_id)
    if previous_database_id != selected_database_id:
        st.session_state["active_database_id"] = selected_database_id
        clear_database_view_state()
        st.rerun()

    st.session_state["active_database_id"] = selected_database_id
    description = next(
        (
            database["description"]
            for database in DATABASES
            if database["id"] == selected_database_id
        ),
        "",
    )
    if description:
        st.sidebar.caption(description)
    return selected_database_id


@st.cache_data(show_spinner=False)
def supabase_supports_database_scoping(url: str, key: str) -> bool:
    """Return whether Supabase normalized tables have a database_id column."""
    response = requests.get(
        f"{url}/rest/v1/papers",
        params={"select": DATABASE_ID_COLUMN, "limit": "1"},
        headers=supabase_headers(key),
        timeout=30,
    )
    return response.ok


def require_supabase_database_scoping(url: str, key: str, database_id: str) -> bool:
    """Return Supabase scoping support or raise for non-main databases."""
    supports_scoping = supabase_supports_database_scoping(url, key)
    if database_id != DEFAULT_DATABASE_ID and not supports_scoping:
        raise RuntimeError(
            "Supabase needs the multi-database migration before Library database "
            "or John database can save independently. Run "
            "docs/supabase_multi_database_migration.sql in Supabase SQL Editor."
        )
    return supports_scoping


def fetch_supabase_table(
    table_name: str,
    columns: list[str],
    url: str,
    key: str,
    database_id: str = DEFAULT_DATABASE_ID,
    *,
    scoped: bool = False,
) -> pd.DataFrame:
    """Fetch one Supabase table through the REST API."""
    rows: list[dict[str, Any]] = []
    start = 0
    headers = supabase_headers(key)
    database_id = normalize_database_id(database_id)
    while True:
        end = start + SUPABASE_PAGE_SIZE - 1
        params = {"select": "*"}
        if scoped:
            params[DATABASE_ID_COLUMN] = f"eq.{database_id}"
        response = requests.get(
            f"{url}/rest/v1/{table_name}",
            params=params,
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
    if DATABASE_ID_COLUMN in df.columns:
        df[DATABASE_ID_COLUMN] = df[DATABASE_ID_COLUMN].fillna("").astype(str)
        if not scoped:
            if database_id == DEFAULT_DATABASE_ID:
                df = df[
                    (df[DATABASE_ID_COLUMN] == DEFAULT_DATABASE_ID)
                    | (df[DATABASE_ID_COLUMN] == "")
                ]
            else:
                df = df[df[DATABASE_ID_COLUMN] == database_id]
    elif normalize_database_id(database_id) != DEFAULT_DATABASE_ID:
        df = pd.DataFrame(columns=columns)

    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns]


def fetch_supabase_filtered_table(
    table_name: str,
    columns: list[str],
    url: str,
    key: str,
    filters: dict[str, str],
) -> pd.DataFrame:
    """Fetch one filtered Supabase table through the REST API."""
    rows: list[dict[str, Any]] = []
    start = 0
    headers = supabase_headers(key)
    while True:
        end = start + SUPABASE_PAGE_SIZE - 1
        params = {"select": "*", **filters}
        response = requests.get(
            f"{url}/rest/v1/{table_name}",
            params=params,
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


def split_dashboard_list(value: Any) -> list[str]:
    """Split semicolon text from the Supabase dashboard view into a clean list."""
    if isinstance(value, (list, tuple, set)):
        return unique_preserve_order(value)
    text = clean_text(value)
    if not text:
        return []
    return unique_preserve_order(part.strip() for part in text.split(";") if part.strip())


def normalize_paper_view_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a one-row-per-paper dataframe to the dashboard paper view shape."""
    if df.empty:
        return pd.DataFrame(columns=PAPER_VIEW_COLUMNS)

    out = df.copy()
    for col in PAPER_VIEW_COLUMNS:
        if col not in out.columns:
            out[col] = ""

    list_columns = [
        "authors",
        "instruments",
        "instrument_statuses",
        "all_verification_statuses",
        "instrument_verification_pairs",
        "sources",
        "source_types",
    ]
    for col in list_columns:
        out[col] = out[col].apply(split_dashboard_list)

    scalar_columns = [
        "paper_id",
        "DOI",
        "title",
        "journal",
        "publisher",
        "paper_type",
        "go_canada_status",
        "display_authors",
        "first_author",
        "display_instruments",
        "display_instrument_verification",
        "verification_status",
        "evidence_quote",
        "checked_date",
        "paper_url",
        "display_sources",
        "notes",
    ]
    for col in scalar_columns:
        out[col] = out[col].apply(clean_text)

    out["year"] = safe_year_series(out["year"])
    out["is_known_false_positive"] = out["is_known_false_positive"].apply(parse_bool)
    out["verification_status"] = out["verification_status"].apply(normalize_status)
    no_instrument_mask = out["instruments"].apply(lambda values: len(values) == 0)
    unchecked_mask = out["verification_status"].isin(["", "unchecked"])
    paper_level_status = out["go_canada_status"].apply(
        paper_level_verification_from_go_canada_status
    )
    out.loc[no_instrument_mask & unchecked_mask, "verification_status"] = paper_level_status[
        no_instrument_mask & unchecked_mask
    ]

    missing_author_display = out["display_authors"] == ""
    out.loc[missing_author_display, "display_authors"] = out.loc[
        missing_author_display, "authors"
    ].apply(join_list)

    missing_first_author = out["first_author"] == ""
    out.loc[missing_first_author, "first_author"] = out.loc[
        missing_first_author, "authors"
    ].apply(lambda values: values[0] if values else "")

    missing_instrument_display = out["display_instruments"] == ""
    out.loc[missing_instrument_display, "display_instruments"] = out.loc[
        missing_instrument_display, "instruments"
    ].apply(join_list)

    missing_instrument_verification = out["display_instrument_verification"] == ""
    out.loc[missing_instrument_verification, "display_instrument_verification"] = out.loc[
        missing_instrument_verification, "instrument_verification_pairs"
    ].apply(join_list)

    missing_source_display = out["display_sources"] == ""
    out.loc[missing_source_display, "display_sources"] = out.loc[
        missing_source_display, "sources"
    ].apply(join_list)

    missing_paper_url = out["paper_url"] == ""
    out.loc[missing_paper_url, "paper_url"] = out.loc[missing_paper_url, "DOI"].apply(doi_to_url)

    return out[PAPER_VIEW_COLUMNS]


def fetch_supabase_dashboard_view(
    url: str,
    key: str,
    database_id: str = DEFAULT_DATABASE_ID,
) -> pd.DataFrame:
    """Fetch the prebuilt one-row-per-paper Supabase dashboard view."""
    rows: list[dict[str, Any]] = []
    start = 0
    headers = supabase_headers(key)
    database_id = normalize_database_id(database_id)
    while True:
        end = start + SUPABASE_PAGE_SIZE - 1
        response = requests.get(
            f"{url}/rest/v1/{SUPABASE_DASHBOARD_VIEW_NAME}",
            params={"select": "*", DATABASE_ID_COLUMN: f"eq.{database_id}"},
            headers={**headers, "Range": f"{start}-{end}"},
            timeout=30,
        )
        response.raise_for_status()
        page_rows = response.json()
        rows.extend(page_rows)
        if len(page_rows) < SUPABASE_PAGE_SIZE:
            break
        start += SUPABASE_PAGE_SIZE

    return normalize_paper_view_df(pd.DataFrame(rows))


@st.cache_data(show_spinner="Loading Supabase database...")
def load_supabase_database(
    url: str,
    key: str,
    database_id: str = DEFAULT_DATABASE_ID,
) -> dict[str, pd.DataFrame]:
    """Load all normalized tables from Supabase."""
    database_id = normalize_database_id(database_id)
    scoped = supabase_supports_database_scoping(url, key)
    return {
        name: fetch_supabase_table(name, columns, url, key, database_id, scoped=scoped)
        for name, columns in REQUIRED_COLUMNS.items()
    }


@st.cache_data(show_spinner="Loading selected paper verification...")
def load_supabase_verification_context(
    url: str,
    key: str,
    database_id: str,
    paper_id: str,
) -> dict[str, pd.DataFrame]:
    """Load only the rows needed to verify one selected paper."""
    database_id = normalize_database_id(database_id)
    paper_id = clean_text(paper_id)
    scoped = require_supabase_database_scoping(url, key, database_id)
    base_filters = {"paper_id": f"eq.{paper_id}"}
    if scoped:
        base_filters[DATABASE_ID_COLUMN] = f"eq.{database_id}"

    paper_instruments = fetch_supabase_filtered_table(
        "paper_instruments",
        REQUIRED_COLUMNS["paper_instruments"],
        url,
        key,
        base_filters,
    )
    verification = fetch_supabase_filtered_table(
        "verification",
        REQUIRED_COLUMNS["verification"],
        url,
        key,
        base_filters,
    )

    instrument_ids = unique_preserve_order(paper_instruments.get("instrument_id", []))
    instrument_filters: dict[str, str] = {}
    if instrument_ids:
        if scoped:
            instrument_filters[DATABASE_ID_COLUMN] = f"eq.{database_id}"
        instrument_filters["instrument_id"] = f"in.({','.join(instrument_ids)})"

    instruments = (
        fetch_supabase_filtered_table(
            "instruments",
            REQUIRED_COLUMNS["instruments"],
            url,
            key,
            instrument_filters,
        )
        if instrument_filters
        else pd.DataFrame(columns=REQUIRED_COLUMNS["instruments"])
    )

    tables = {
        name: pd.DataFrame(columns=columns)
        for name, columns in REQUIRED_COLUMNS.items()
    }
    tables["paper_instruments"] = paper_instruments
    tables["verification"] = verification
    tables["instruments"] = instruments
    return tables


@st.cache_data(show_spinner="Loading dashboard view...")
def load_supabase_paper_view(
    url: str,
    key: str,
    database_id: str = DEFAULT_DATABASE_ID,
) -> pd.DataFrame:
    """Load the lightweight Supabase paper view used by normal dashboard pages."""
    return fetch_supabase_dashboard_view(url, key, database_id)


def clear_database_caches() -> None:
    """Clear all cached database reads."""
    read_csv_safe.clear()
    load_csv_database.clear()
    load_database.clear()
    load_supabase_database.clear()
    load_supabase_verification_context.clear()
    load_supabase_paper_view.clear()
    load_paper_view_base.clear()
    load_paper_view.clear()
    supabase_supports_database_scoping.clear()
    load_shared_presets.clear()


def delete_supabase_table(
    table_name: str,
    url: str,
    key: str,
    database_id: str = DEFAULT_DATABASE_ID,
    *,
    scoped: bool = False,
) -> None:
    """Delete all rows from one Supabase table."""
    headers = supabase_headers(key)
    delete_column = DATABASE_ID_COLUMN if scoped else TABLE_DELETE_FILTER_COLUMN[table_name]
    delete_value = f"eq.{database_id}" if scoped else "not.is.null"
    delete_response = requests.delete(
        f"{url}/rest/v1/{table_name}",
        params={delete_column: delete_value},
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
    database_id: str = DEFAULT_DATABASE_ID,
    *,
    scoped: bool = False,
) -> None:
    """Insert all rows for one Supabase table."""
    headers = supabase_headers(key)
    storage_columns = [DATABASE_ID_COLUMN] + columns if scoped else columns
    out = df.copy()
    if scoped:
        out[DATABASE_ID_COLUMN] = database_id
    out = dataframe_for_storage(out, storage_columns)
    primary_key_columns = (
        SUPABASE_SCOPED_PRIMARY_KEY_COLUMNS.get(table_name, [])
        if scoped
        else TABLE_PRIMARY_KEY_COLUMNS.get(table_name, [])
    )
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


def delete_supabase_verification_row(
    paper_id: str,
    instrument_id: str,
    url: str,
    key: str,
    database_id: str = DEFAULT_DATABASE_ID,
    *,
    scoped: bool = False,
) -> None:
    """Delete one paper-instrument verification row from Supabase."""
    params = {
        "paper_id": f"eq.{paper_id}",
        "instrument_id": f"eq.{instrument_id}",
    }
    if scoped:
        params[DATABASE_ID_COLUMN] = f"eq.{database_id}"
    delete_response = requests.delete(
        f"{url}/rest/v1/verification",
        params=params,
        headers=supabase_headers(key),
        timeout=30,
    )
    delete_response.raise_for_status()


def upsert_supabase_verification_row(
    row: dict[str, Any],
    url: str,
    key: str,
    database_id: str = DEFAULT_DATABASE_ID,
    *,
    scoped: bool = False,
) -> None:
    """Insert or update one paper-instrument verification row in Supabase."""
    headers = {
        **supabase_headers(key),
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    storage_columns = REQUIRED_COLUMNS["verification"]
    if scoped:
        storage_columns = [DATABASE_ID_COLUMN] + storage_columns
        row = {**row, DATABASE_ID_COLUMN: database_id}
    upsert_response = requests.post(
        f"{url}/rest/v1/verification",
        params={
            "on_conflict": "database_id,paper_id,instrument_id"
            if scoped
            else "paper_id,instrument_id"
        },
        json=[{column: clean_text(row.get(column)) for column in storage_columns}],
        headers=headers,
        timeout=30,
    )
    upsert_response.raise_for_status()


def update_supabase_paper_fields(
    paper_id: str,
    fields: dict[str, Any],
    url: str,
    key: str,
    database_id: str = DEFAULT_DATABASE_ID,
    *,
    scoped: bool = False,
) -> None:
    """Patch scalar fields for one paper in Supabase."""
    params = {"paper_id": f"eq.{paper_id}"}
    if scoped:
        params[DATABASE_ID_COLUMN] = f"eq.{database_id}"
    patch_response = requests.patch(
        f"{url}/rest/v1/papers",
        params=params,
        json={field: clean_text(value) for field, value in fields.items()},
        headers=supabase_headers(key),
        timeout=30,
    )
    patch_response.raise_for_status()


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
    database_id = active_database_id()
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
        scoped = require_supabase_database_scoping(url, key, database_id)
        if status == "unchecked":
            delete_supabase_verification_row(
                paper_id,
                instrument_id,
                url,
                key,
                database_id,
                scoped=scoped,
            )
        else:
            upsert_supabase_verification_row(row, url, key, database_id, scoped=scoped)
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
    save_database_tables(working_tables, database_id)


def replace_supabase_database(
    tables: dict[str, pd.DataFrame],
    database_id: str = DEFAULT_DATABASE_ID,
) -> None:
    """Replace one Supabase normalized database with current app tables."""
    config = supabase_config()
    if not config:
        raise RuntimeError("Supabase is not configured.")
    url, key = config
    database_id = normalize_database_id(database_id)
    scoped = require_supabase_database_scoping(url, key, database_id)

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
        delete_supabase_table(name, url, key, database_id, scoped=scoped)
    for name in insert_order:
        insert_supabase_table(
            name,
            tables[name],
            REQUIRED_COLUMNS[name],
            url,
            key,
            database_id,
            scoped=scoped,
        )
    clear_database_caches()


def clean_preset_name(name: str) -> str:
    """Return a safe shared preset name."""
    return "".join(c for c in name.strip() if c.isalnum() or c in "-_ ").strip()


def local_preset_path(name: str) -> Path:
    """Return the JSON path for a local fallback preset."""
    return PRESET_DIR / f"{clean_preset_name(name)}.json"


def fetch_supabase_presets(url: str, key: str) -> dict[str, dict[str, Any]]:
    """Fetch shared presets from Supabase."""
    response = requests.get(
        f"{url}/rest/v1/global_presets",
        params={"select": "*", "order": "preset_name.asc"},
        headers=supabase_headers(key),
        timeout=30,
    )
    response.raise_for_status()
    presets: dict[str, dict[str, Any]] = {}
    for row in response.json():
        name = clean_text(row.get("preset_name"))
        if not name:
            continue
        try:
            presets[name] = json.loads(clean_text(row.get("preset_json")))
        except json.JSONDecodeError:
            presets[name] = {}
    return presets


def load_local_presets() -> dict[str, dict[str, Any]]:
    """Load bundled or local fallback shared presets."""
    presets: dict[str, dict[str, Any]] = {}
    for path in sorted(PRESET_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                presets[path.stem] = json.load(handle)
        except Exception:
            continue
    return presets


@st.cache_data(show_spinner=False)
def load_shared_presets() -> dict[str, dict[str, Any]]:
    """Load public shared presets from bundled JSON and Supabase when configured."""
    presets = load_local_presets()
    config = supabase_config()
    if config:
        try:
            url, key = config
            presets.update(fetch_supabase_presets(url, key))
            return presets
        except requests.HTTPError:
            return presets
        except Exception:
            return presets
    return presets


def save_shared_preset(name: str, preset: dict[str, Any]) -> None:
    """Create or update one shared preset."""
    safe_name = clean_preset_name(name)
    if not safe_name:
        raise ValueError("Preset name is required.")

    config = supabase_config()
    if config:
        url, key = config
        headers = {
            **supabase_headers(key),
            "Prefer": "resolution=merge-duplicates,return=minimal",
        }
        response = requests.post(
            f"{url}/rest/v1/global_presets",
            params={"on_conflict": "preset_name"},
            json=[
                {
                    "preset_name": safe_name,
                    "preset_json": json.dumps(preset),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
            ],
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        load_shared_presets.clear()
        return

    if READ_ONLY_MODE:
        raise RuntimeError("Local preset saving is disabled in read-only mode without Supabase.")
    PRESET_DIR.mkdir(exist_ok=True)
    with open(local_preset_path(safe_name), "w", encoding="utf-8") as handle:
        json.dump(preset, handle, indent=2)
    load_shared_presets.clear()


def delete_shared_preset(name: str) -> None:
    """Delete one shared preset."""
    safe_name = clean_preset_name(name)
    if not safe_name:
        return

    config = supabase_config()
    if config:
        url, key = config
        response = requests.delete(
            f"{url}/rest/v1/global_presets",
            params={"preset_name": f"eq.{safe_name}"},
            headers=supabase_headers(key),
            timeout=30,
        )
        response.raise_for_status()
        load_shared_presets.clear()
        return

    if READ_ONLY_MODE:
        raise RuntimeError("Local preset deletion is disabled in read-only mode without Supabase.")
    path = local_preset_path(safe_name)
    if path.exists():
        path.unlink()
    load_shared_presets.clear()


def current_view_snapshot() -> dict[str, Any]:
    """Capture current filter and view widget state for a preset."""
    return {
        key: st.session_state.get(key)
        for key in FILTER_WIDGET_KEYS + VIEW_WIDGET_KEYS
        if key in st.session_state
    }


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


def write_csv_table(
    name: str,
    df: pd.DataFrame,
    database_id: str = DEFAULT_DATABASE_ID,
) -> None:
    """Write one normalized table back to disk with the expected column order."""
    if READ_ONLY_MODE:
        raise RuntimeError("CSV writes are disabled in read-only deployment mode.")

    out_dir = database_data_dir(database_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    required_columns = REQUIRED_COLUMNS[name]
    out = dataframe_for_storage(df, required_columns)
    out.to_csv(out_dir / f"{name}.csv", index=False)


@st.cache_data(show_spinner="Loading CSV database...")
def load_csv_database(data_dir: str = "data") -> dict[str, pd.DataFrame]:
    """Load all normalized CSV files."""
    base_dir = Path(data_dir)
    tables = {}
    for name, required_columns in REQUIRED_COLUMNS.items():
        tables[name] = read_csv_safe(base_dir / f"{name}.csv", required_columns)
    return tables


@st.cache_data(show_spinner="Loading database...")
def load_database(
    database_id: str = DEFAULT_DATABASE_ID,
    data_dir: str = "data",
) -> dict[str, pd.DataFrame]:
    """Load all normalized tables from Supabase when configured, otherwise CSV."""
    database_id = normalize_database_id(database_id)
    config = supabase_config()
    if config:
        url, key = config
        return load_supabase_database(url, key, database_id)

    return load_csv_database(str(database_data_dir(database_id)))


@st.cache_data(show_spinner="Loading dashboard data...")
def load_paper_view_base(
    database_id: str = DEFAULT_DATABASE_ID,
    data_dir: str = "data",
) -> pd.DataFrame:
    """
    Load the lightweight paper view for normal dashboard pages.

    Supabase deployments should use paper_dashboard_view. CSV/local runs and
    Supabase projects that have not installed the view fall back to building the
    same shape from normalized tables.
    """
    database_id = normalize_database_id(database_id)
    config = supabase_config()
    if config:
        url, key = config
        try:
            return load_supabase_paper_view(url, key, database_id)
        except requests.RequestException:
            pass

    return build_paper_view(load_database(database_id, data_dir))


def inherit_main_verification_status(
    paper_view: pd.DataFrame,
    main_paper_view: pd.DataFrame,
) -> pd.DataFrame:
    """Fill unchecked non-main statuses from matching verified Main DOI records."""
    if paper_view.empty or main_paper_view.empty:
        return paper_view

    out = paper_view.copy()
    if "DOI" not in out.columns or "verification_status" not in out.columns:
        return out
    if (
        "DOI" not in main_paper_view.columns
        or "verification_status" not in main_paper_view.columns
    ):
        return out

    main_statuses = main_paper_view[["DOI", "verification_status"]].copy()
    main_statuses["doi_key"] = main_statuses["DOI"].apply(doi_match_key)
    main_statuses["verification_status"] = main_statuses["verification_status"].apply(
        normalize_status
    )
    main_statuses = main_statuses[
        (main_statuses["doi_key"] != "")
        & main_statuses["verification_status"].isin(INHERITABLE_VERIFICATION_STATUSES)
    ].drop_duplicates("doi_key", keep="first")
    if main_statuses.empty:
        return out

    inherited_status_by_doi = dict(
        zip(main_statuses["doi_key"], main_statuses["verification_status"])
    )
    out_status = out["verification_status"].apply(normalize_status)
    out_doi_key = out["DOI"].apply(doi_match_key)
    inherited_status = out_doi_key.map(inherited_status_by_doi).fillna("")
    should_inherit = out_status.eq("unchecked") & inherited_status.isin(
        INHERITABLE_VERIFICATION_STATUSES
    )
    out.loc[should_inherit, "verification_status"] = inherited_status[should_inherit]
    return out


@st.cache_data(show_spinner="Loading dashboard data...")
def load_paper_view(
    database_id: str = DEFAULT_DATABASE_ID,
    data_dir: str = "data",
) -> pd.DataFrame:
    """Load the dashboard paper view, inheriting Main verification when needed."""
    database_id = normalize_database_id(database_id)
    paper_view = load_paper_view_base(database_id, data_dir)
    if database_id == DEFAULT_DATABASE_ID:
        return paper_view

    main_paper_view = load_paper_view_base(DEFAULT_DATABASE_ID, data_dir)
    return inherit_main_verification_status(paper_view, main_paper_view)


def load_verification_context(
    database_id: str,
    paper_id: str,
    data_dir: str = "data",
) -> dict[str, pd.DataFrame]:
    """Load the smallest table set needed by the verification editor."""
    database_id = normalize_database_id(database_id)
    config = supabase_config()
    if config:
        url, key = config
        return load_supabase_verification_context(url, key, database_id, paper_id)
    return load_database(database_id, data_dir)


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
        return pd.DataFrame(columns=PAPER_VIEW_COLUMNS)

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
    instrument_verification_grouped = pd.DataFrame(
        columns=["paper_id", "instrument_verification_pairs"]
    )
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

    if not paper_instruments.empty and not instruments.empty:
        pi_status = paper_instruments.merge(instruments, on="instrument_id", how="left")
        if not verification.empty:
            pi_status = pi_status.merge(
                verification[["paper_id", "instrument_id", "normalized_status"]],
                on=["paper_id", "instrument_id"],
                how="left",
            )
        else:
            pi_status["normalized_status"] = ""
        pi_status["normalized_status"] = pi_status["normalized_status"].fillna("").replace("", "unchecked")
        rows = []
        for paper_id, group in pi_status.groupby("paper_id"):
            pairs = [
                f"{clean_text(row.get('instrument_name'))}: {clean_text(row.get('normalized_status'))}"
                for _, row in group.iterrows()
                if clean_text(row.get("instrument_name"))
            ]
            rows.append(
                {
                    "paper_id": paper_id,
                    "instrument_verification_pairs": unique_preserve_order(pairs),
                }
            )
        instrument_verification_grouped = pd.DataFrame(rows)

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
    df = df.merge(instrument_verification_grouped, on="paper_id", how="left")
    df = df.merge(sources_grouped, on="paper_id", how="left")

    # Fill list columns.
    for col in [
        "authors",
        "instruments",
        "instrument_statuses",
        "all_verification_statuses",
        "instrument_verification_pairs",
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
    no_instrument_mask = df["instruments"].apply(lambda values: len(values) == 0)
    unchecked_mask = df["verification_status"].isin(["", "unchecked"])
    paper_level_status = df["go_canada_status"].apply(
        paper_level_verification_from_go_canada_status
    )
    df.loc[no_instrument_mask & unchecked_mask, "verification_status"] = paper_level_status[
        no_instrument_mask & unchecked_mask
    ]

    # Human-readable display columns.
    df["display_authors"] = df["authors"].apply(join_list)
    df["display_instruments"] = df["instruments"].apply(join_list)
    df["display_instrument_verification"] = df["instrument_verification_pairs"].apply(join_list)
    df["display_sources"] = df["sources"].apply(join_list)

    # Use DOI as a clean text field.
    df["DOI"] = df["DOI"].fillna("").astype(str).str.strip()
    df["paper_url"] = df["DOI"].apply(doi_to_url)

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
    width = 3
    for value in df[id_col].dropna().astype(str):
        if not value.startswith(prefix):
            continue
        suffix = value[len(prefix):]
        if suffix.isdigit():
            width = max(width, len(suffix))
            max_number = max(max_number, int(suffix))
    return f"{prefix}{max_number + 1:0{width}d}"


def append_row(df: pd.DataFrame, row: dict[str, Any], columns: list[str]) -> pd.DataFrame:
    """Append one row while preserving the normalized table columns."""
    return pd.concat([df, pd.DataFrame([row], columns=columns)], ignore_index=True)


def existing_paper_match(papers: pd.DataFrame, doi: str, title: str) -> str:
    """Return a reason if a paper appears to already exist."""
    paper_id, reason = find_existing_paper(papers, doi, title)
    return reason if paper_id else ""


def find_existing_paper(papers: pd.DataFrame, doi: str, title: str) -> tuple[str, str]:
    """Return an existing paper_id and match reason for a DOI/title import row."""
    doi_key = clean_text(doi).lower()
    if doi_key:
        doi_matches = papers["DOI"].fillna("").astype(str).str.lower().str.strip() == doi_key
        if bool(doi_matches.any()):
            return clean_text(papers.loc[doi_matches, "paper_id"].iloc[0]), "Duplicate DOI"

    title_key = normalized_match_key(pd.Series([title])).iloc[0]
    if title_key:
        title_matches = normalized_match_key(papers["title"]) == title_key
        if bool(title_matches.any()):
            return clean_text(papers.loc[title_matches, "paper_id"].iloc[0]), "Duplicate title"

    return "", ""


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
        source_id = clean_text(sources.loc[matches, "source_id"].iloc[0])
        source_mask = sources["source_id"].fillna("").astype(str) == source_id
        if clean_text(source_type):
            sources.loc[source_mask, "source_type"] = clean_text(source_type)
        if clean_text(notes):
            sources.loc[source_mask, "notes"] = clean_text(notes)
        tables["sources"] = sources
        return source_id

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


def link_author_to_paper(tables: dict[str, pd.DataFrame], paper_id: str, author_name: str, order: int) -> None:
    """Create one paper-author link."""
    author_id = get_or_create_author_id(tables, author_name)
    tables["paper_authors"] = append_row(
        tables["paper_authors"],
        {"paper_id": paper_id, "author_id": author_id, "author_order": order},
        REQUIRED_COLUMNS["paper_authors"],
    )


def add_or_update_paper_instrument(
    tables: dict[str, pd.DataFrame],
    paper_id: str,
    instrument_name: str,
    instrument_status: str,
) -> tuple[str, bool]:
    """Create or update one paper-instrument link and return whether it was new."""
    instrument_id = get_or_create_instrument_id(tables, instrument_name)
    paper_instruments = tables["paper_instruments"]
    existing = (
        (paper_instruments["paper_id"].fillna("").astype(str) == paper_id)
        & (paper_instruments["instrument_id"].fillna("").astype(str) == instrument_id)
    )
    if bool(existing.any()):
        if clean_text(instrument_status):
            paper_instruments.loc[existing, "instrument_status"] = clean_text(instrument_status)
            tables["paper_instruments"] = paper_instruments
        return instrument_id, False

    tables["paper_instruments"] = append_row(
        paper_instruments,
        {
            "paper_id": paper_id,
            "instrument_id": instrument_id,
            "instrument_status": clean_text(instrument_status) or "unchecked",
        },
        REQUIRED_COLUMNS["paper_instruments"],
    )
    return instrument_id, True


def link_source_to_paper(tables: dict[str, pd.DataFrame], paper_id: str, source_id: str) -> bool:
    """Create a paper-source link if it does not already exist."""
    paper_sources = tables["paper_sources"]
    existing = (
        (paper_sources["paper_id"].fillna("").astype(str) == paper_id)
        & (paper_sources["source_id"].fillna("").astype(str) == source_id)
    )
    if bool(existing.any()):
        return False

    tables["paper_sources"] = append_row(
        paper_sources,
        {"paper_id": paper_id, "source_id": source_id},
        REQUIRED_COLUMNS["paper_sources"],
    )
    return True


def upsert_verification_link(
    tables: dict[str, pd.DataFrame],
    paper_id: str,
    instrument_id: str,
    status: str,
    evidence_quote: str,
    checked_date: str,
    notes: str,
) -> bool:
    """Create or update one verification row and return whether it was new."""
    verification = tables["verification"]
    existing = (
        (verification["paper_id"].fillna("").astype(str) == paper_id)
        & (verification["instrument_id"].fillna("").astype(str) == instrument_id)
    )
    row = {
        "paper_id": paper_id,
        "instrument_id": instrument_id,
        "status": status,
        "evidence_quote": clean_text(evidence_quote),
        "checked_date": clean_text(checked_date),
        "notes": clean_text(notes),
    }
    if bool(existing.any()):
        for column, value in row.items():
            if column in {"paper_id", "instrument_id"}:
                continue
            if clean_text(value):
                verification.loc[existing, column] = value
        tables["verification"] = verification
        return False

    tables["verification"] = append_row(
        verification,
        row,
        REQUIRED_COLUMNS["verification"],
    )
    return True


def update_existing_paper_record(
    tables: dict[str, pd.DataFrame],
    paper_id: str,
    record: dict[str, Any],
    match_reason: str,
) -> tuple[str, str]:
    """Update an existing paper from an import row and merge related records."""
    papers = tables["papers"]
    paper_mask = papers["paper_id"].fillna("").astype(str) == paper_id
    if not bool(paper_mask.any()):
        return "skipped", "Matched paper no longer exists"

    changed_fields: list[str] = []
    for field in ["DOI", "title", "year", "journal", "publisher", "paper_type", "go_canada_status"]:
        incoming = clean_text(record.get(field))
        if incoming and clean_text(papers.loc[paper_mask, field].iloc[0]) != incoming:
            papers.loc[paper_mask, field] = incoming
            changed_fields.append(field)

    status = normalize_status(record.get("verification_status", "unchecked"))
    false_positive_text = clean_text(record.get("is_known_false_positive"))
    if false_positive_text or status == "verified_false":
        incoming_false_positive = parse_bool(false_positive_text) or status == "verified_false"
        stored_false_positive = bool_storage_text(incoming_false_positive)
        if clean_text(papers.loc[paper_mask, "is_known_false_positive"].iloc[0]) != stored_false_positive:
            papers.loc[paper_mask, "is_known_false_positive"] = stored_false_positive
            changed_fields.append("is_known_false_positive")
    tables["papers"] = papers

    imported_authors = unique_preserve_order(split_multi_value(record.get("authors")))
    if imported_authors:
        existing_authors = tables["paper_authors"]
        tables["paper_authors"] = existing_authors[
            existing_authors["paper_id"].fillna("").astype(str) != paper_id
        ].reset_index(drop=True)
        for order, author_name in enumerate(imported_authors, start=1):
            link_author_to_paper(tables, paper_id, author_name, order)
        changed_fields.append("authors")

    instrument_names = unique_preserve_order(split_multi_value(record.get("instruments")))
    instrument_statuses = split_multi_value(record.get("instrument_status"))
    instrument_ids: list[str] = []
    added_instruments: list[str] = []
    for index, instrument_name in enumerate(instrument_names):
        instrument_status = (
            instrument_statuses[index]
            if index < len(instrument_statuses)
            else clean_text(record.get("instrument_status")) or "unchecked"
        )
        instrument_id, was_added = add_or_update_paper_instrument(
            tables,
            paper_id,
            instrument_name,
            instrument_status,
        )
        instrument_ids.append(instrument_id)
        if was_added:
            added_instruments.append(instrument_name)
    if added_instruments:
        changed_fields.append(f"instruments +{', '.join(added_instruments)}")
    elif instrument_names:
        changed_fields.append("instrument_status")

    source_names = unique_preserve_order(split_multi_value(record.get("source_name") or record.get("source")))
    source_types = split_multi_value(record.get("source_type"))
    linked_sources = 0
    for index, source_name in enumerate(source_names):
        source_type = source_types[index] if index < len(source_types) else clean_text(record.get("source_type"))
        source_id = get_or_create_source_id(
            tables,
            source_name,
            source_type,
            clean_text(record.get("source_notes")),
        )
        if link_source_to_paper(tables, paper_id, source_id):
            linked_sources += 1
    if linked_sources:
        changed_fields.append("sources")

    if status != "unchecked":
        verification_instrument_ids = instrument_ids
        if not verification_instrument_ids:
            verification_instrument_ids = (
                tables["paper_instruments"]
                .loc[
                    tables["paper_instruments"]["paper_id"].fillna("").astype(str) == paper_id,
                    "instrument_id",
                ]
                .fillna("")
                .astype(str)
                .tolist()
            )
        for instrument_id in verification_instrument_ids or [""]:
            upsert_verification_link(
                tables,
                paper_id,
                instrument_id,
                status,
                clean_text(record.get("evidence_quote")),
                clean_text(record.get("checked_date")),
                clean_text(record.get("notes")),
            )
        changed_fields.append("verification")

    if not changed_fields:
        return "updated", f"{paper_id}: already up to date ({match_reason})"
    return "updated", f"{paper_id}: updated {', '.join(unique_preserve_order(changed_fields))} ({match_reason})"


def add_paper_record(tables: dict[str, pd.DataFrame], record: dict[str, Any]) -> tuple[str, str]:
    """Add or update one paper and related normalized rows in memory."""
    title = clean_text(record.get("title"))
    doi = clean_text(record.get("DOI"))
    if not title:
        return "skipped", "Missing title"

    existing_paper_id, duplicate_reason = find_existing_paper(tables["papers"], doi, title)
    if existing_paper_id:
        return update_existing_paper_record(tables, existing_paper_id, record, duplicate_reason)

    paper_id = generate_next_id(tables["papers"], "paper_id", "P")
    status = normalize_status(record.get("verification_status", "unchecked"))
    known_false_positive = (
        parse_bool(record.get("is_known_false_positive")) or status == "verified_false"
    )

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
            "is_known_false_positive": bool_storage_text(known_false_positive),
        },
        REQUIRED_COLUMNS["papers"],
    )

    for order, author_name in enumerate(unique_preserve_order(split_multi_value(record.get("authors"))), start=1):
        link_author_to_paper(tables, paper_id, author_name, order)

    instrument_names = unique_preserve_order(split_multi_value(record.get("instruments")))
    instrument_statuses = split_multi_value(record.get("instrument_status"))
    instrument_ids = []
    for index, instrument_name in enumerate(instrument_names):
        instrument_status = (
            instrument_statuses[index]
            if index < len(instrument_statuses)
            else clean_text(record.get("instrument_status")) or "unchecked"
        )
        instrument_id, _ = add_or_update_paper_instrument(
            tables,
            paper_id,
            instrument_name,
            instrument_status,
        )
        instrument_ids.append(instrument_id)

    source_names = unique_preserve_order(split_multi_value(record.get("source_name") or record.get("source")))
    source_types = split_multi_value(record.get("source_type"))
    for index, source_name in enumerate(source_names):
        source_type = source_types[index] if index < len(source_types) else clean_text(record.get("source_type"))
        source_id = get_or_create_source_id(
            tables,
            source_name,
            source_type,
            clean_text(record.get("source_notes")),
        )
        link_source_to_paper(tables, paper_id, source_id)

    if status != "unchecked":
        verification_instrument_ids = instrument_ids or [""]
        for instrument_id in verification_instrument_ids:
            upsert_verification_link(
                tables,
                paper_id,
                instrument_id,
                status,
                clean_text(record.get("evidence_quote")),
                clean_text(record.get("checked_date")),
                clean_text(record.get("notes")),
            )

    return "added", paper_id


def save_database_tables(
    tables: dict[str, pd.DataFrame],
    database_id: str | None = None,
) -> None:
    """Persist all normalized tables to Supabase or local CSV files."""
    database_id = normalize_database_id(database_id or active_database_id())
    if supabase_config():
        replace_supabase_database(tables, database_id)
        return

    for name in REQUIRED_COLUMNS:
        write_csv_table(name, tables[name], database_id)
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
        action, message = add_paper_record(tables, record)
        results.append(
            {
                "csv_row": row_number,
                "title": clean_text(record.get("title")),
                "DOI": clean_text(record.get("DOI")),
                "result": action,
                "message": message,
            }
        )
    return pd.DataFrame(results)


# -----------------------------------------------------------------------------
# Filtering
# -----------------------------------------------------------------------------

def get_filter_options(
    df: pd.DataFrame,
    instruments_table: pd.DataFrame | None = None,
) -> dict[str, list[str]]:
    """Build options for filter widgets."""
    instrument_values = [item for values in df["instruments"] for item in values]
    if instruments_table is not None and "instrument_name" in instruments_table.columns:
        instrument_values.extend(instruments_table["instrument_name"].fillna("").astype(str))
    instrument_values.extend(ADDITIONAL_INSTRUMENT_FILTER_OPTIONS)

    options = {
        "instruments": sorted_options(instrument_values),
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


def normalize_year_range_value(value: Any, default: tuple[int, int]) -> tuple[int, int]:
    """Normalize a stored year range value."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    return default


def current_filter_group(filters: dict[str, Any]) -> dict[str, Any]:
    """Capture the positive current filters as one reusable group."""
    group_keys = [
        "paper_search_query",
        "selected_instruments",
        "selected_authors",
        "selected_publishers",
        "selected_journals",
        "selected_paper_types",
        "selected_verification_statuses",
        "selected_go_canada_statuses",
        "selected_sources",
        "year_range",
    ]
    return {
        key: filters.get(key, [] if key.startswith("selected_") else "")
        for key in group_keys
    }


def filter_group_summary(group: dict[str, Any]) -> str:
    """Build a compact user-facing summary for one filter group."""
    stored_count = group.get("paper_count")
    parts = []
    labels = [
        ("paper_search_query", "Search"),
        ("selected_instruments", "Instrument"),
        ("selected_authors", "Author"),
        ("selected_publishers", "Publisher"),
        ("selected_journals", "Journal"),
        ("selected_paper_types", "Type"),
        ("selected_verification_statuses", "Verification"),
        ("selected_go_canada_statuses", "GO status"),
        ("selected_sources", "Source"),
    ]
    for key, label in labels:
        value = group.get(key)
        if isinstance(value, (list, tuple, set)) and value:
            value_list = [clean_text(item) for item in value if clean_text(item)]
            if value_list:
                parts.append(
                    f"{label}: {', '.join(value_list[:3])}{'...' if len(value_list) > 3 else ''}"
                )
        else:
            text_value = clean_text(value)
            if text_value:
                parts.append(f"{label}: {text_value}")

    year_range = group.get("year_range")
    if isinstance(year_range, (list, tuple)) and len(year_range) == 2:
        parts.append(f"Years: {year_range[0]}-{year_range[1]}")

    summary = " | ".join(parts) if parts else "All papers"
    if stored_count is not None:
        summary = f"{summary} ({stored_count} stored papers)"
    return summary


def render_combined_filter_controls(df: pd.DataFrame, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Render controls for combining multiple stored paper lists by union."""
    groups = st.session_state.get("combined_filter_groups", [])
    if not isinstance(groups, list):
        groups = []
        st.session_state["combined_filter_groups"] = groups

    with st.sidebar.expander("Combined filter groups", expanded=bool(groups)):
        st.caption(
            "Add the current filter result as a stored paper list. "
            "Results become List 1 OR List 2 OR List 3."
        )
        current_group_name = st.text_input(
            "List name",
            key="combined_filter_group_name",
            placeholder="Example: REGO 2012-2014",
        )
        current_group = current_filter_group(filters)
        current_group_df = apply_positive_filter_set(df, current_group)
        st.caption(f"Current filter would store {len(current_group_df):,} papers.")
        if st.button("Add current filter result as list"):
            group = current_group
            group["name"] = clean_text(current_group_name) or f"Group {len(groups) + 1}"
            group["paper_ids"] = current_group_df["paper_id"].astype(str).tolist()
            group["paper_count"] = len(group["paper_ids"])
            groups = groups + [group]
            st.session_state["combined_filter_groups"] = groups
            st.session_state["combined_filter_result_mode"] = "Current filter preview"
            st.rerun()

        if groups:
            result_mode = st.radio(
                "Dashboard result mode",
                ["Current filter preview", "Combined stored lists"],
                key="combined_filter_result_mode",
            )
            if result_mode == "Current filter preview":
                st.info("Use current filters to search the full database and store more lists.")
            else:
                st.info("Showing the union of all stored lists.")
            st.write("Stored lists:")
            remove_index = None
            for index, group in enumerate(groups):
                label = clean_text(group.get("name")) or f"Group {index + 1}"
                st.caption(f"{index + 1}. {label}: {filter_group_summary(group)}")
                if st.button(f"Remove list {index + 1}", key=f"remove_filter_group_{index}"):
                    remove_index = index
            if remove_index is not None:
                st.session_state["combined_filter_groups"] = [
                    group for index, group in enumerate(groups) if index != remove_index
                ]
                st.rerun()
            if st.button("Clear all stored lists"):
                st.session_state["combined_filter_groups"] = []
                st.session_state["combined_filter_result_mode"] = "Current filter preview"
                st.rerun()
        else:
            st.caption("No stored lists yet. The app is using the current single filter.")
            st.session_state["combined_filter_result_mode"] = "Current filter preview"

    return st.session_state.get("combined_filter_groups", [])


def render_saved_view_controls() -> None:
    """Load shared filter presets in the sidebar."""
    with st.sidebar.expander("Shared presets", expanded=False):
        presets = load_shared_presets()
        preset_names = sorted(presets, key=str.lower)

        if preset_names:
            selected_preset = st.selectbox("Load saved view", [""] + preset_names)
            if st.button("Load selected view", disabled=not selected_preset):
                preset = presets.get(selected_preset, {})
                for key, value in preset.items():
                    st.session_state[key] = value
                st.rerun()
        else:
            st.caption("No shared presets yet.")

        if admin_password_configured():
            st.caption("Admins can create and change shared presets in Admin Editor.")


def render_filters(
    df: pd.DataFrame,
    instruments_table: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Render sidebar filters and return the selected values."""
    options = get_filter_options(df, instruments_table)
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
    paper_search_query = st.sidebar.text_input(
        "Search papers",
        key="paper_search_query",
        placeholder="Title, DOI, author, instrument...",
    )

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

    filters = {
        "selected_instruments": selected_instruments,
        "selected_authors": selected_authors,
        "selected_publishers": selected_publishers,
        "selected_journals": selected_journals,
        "selected_paper_types": selected_paper_types,
        "selected_verification_statuses": selected_verification_statuses,
        "selected_go_canada_statuses": selected_go_canada_statuses,
        "selected_sources": selected_sources,
        "paper_search_query": paper_search_query,
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
    filters["combined_filter_groups"] = render_combined_filter_controls(df, filters)
    filters["combined_filter_result_mode"] = st.session_state.get(
        "combined_filter_result_mode",
        "Current filter preview",
    )
    return filters


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


def apply_positive_filter_set(
    df: pd.DataFrame,
    filters: dict[str, Any],
    *,
    apply_verification_filter: bool = True,
) -> pd.DataFrame:
    """Apply one positive filter set to the paper view."""
    out = df.copy()

    search_query = clean_text(filters.get("paper_search_query"))
    if search_query:
        out = out[paper_search_mask(out, search_query)]

    instrument_mask = out["instruments"].apply(
        lambda values: contains_any(values, filters.get("selected_instruments", []))
    )
    out = out.loc[instrument_mask.astype(bool)]
    author_mask = out["authors"].apply(
        lambda values: contains_any(values, filters.get("selected_authors", []))
    )
    out = out.loc[author_mask.astype(bool)]

    year_start, year_end = normalize_year_range_value(
        filters.get("year_range"),
        year_bounds(df),
    )
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

    if filters.get("selected_publishers"):
        out = out[out["publisher"].isin(filters.get("selected_publishers", []))]
    if filters.get("selected_journals"):
        out = out[out["journal"].isin(filters.get("selected_journals", []))]
    if filters.get("selected_paper_types"):
        out = out[out["paper_type"].isin(filters.get("selected_paper_types", []))]
    if apply_verification_filter and filters.get("selected_verification_statuses"):
        out = out[out["verification_status"].isin(filters.get("selected_verification_statuses", []))]
    if filters.get("selected_go_canada_statuses"):
        out = out[out["go_canada_status"].isin(filters.get("selected_go_canada_statuses", []))]
    if filters.get("selected_sources"):
        source_mask = out["sources"].apply(
            lambda values: contains_any(values, filters.get("selected_sources", []))
        )
        out = out.loc[source_mask.astype(bool)]

    return out


def apply_global_filter_cleanup(
    out: pd.DataFrame,
    filters: dict[str, Any],
    *,
    remove_known_false_positives: bool | None = None,
) -> pd.DataFrame:
    """Apply exclusions, metadata completeness, and false-positive cleanup."""
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


def apply_filters(
    df: pd.DataFrame,
    filters: dict[str, Any],
    *,
    remove_known_false_positives: bool | None = None,
    apply_verification_filter: bool = True,
) -> pd.DataFrame:
    """Apply current filters, supporting OR-combined filter groups."""
    groups = filters.get("combined_filter_groups") or []
    use_combined_lists = (
        groups
        and filters.get("combined_filter_result_mode") == "Combined stored lists"
    )
    if use_combined_lists:
        group_frames = []
        for group in groups:
            paper_ids = [clean_text(paper_id) for paper_id in group.get("paper_ids", []) if clean_text(paper_id)]
            if "paper_ids" in group:
                group_frames.append(df[df["paper_id"].astype(str).isin(paper_ids)])
            else:
                group_frames.append(
                    apply_positive_filter_set(
                        df,
                        group,
                        apply_verification_filter=apply_verification_filter,
                    )
                )
        group_frames = [frame for frame in group_frames if not frame.empty]
        if group_frames:
            out = (
                pd.concat(group_frames, ignore_index=True)
                .drop_duplicates("paper_id", keep="first")
                .reset_index(drop=True)
            )
        else:
            out = df.iloc[0:0].copy()
    else:
        out = apply_positive_filter_set(
            df,
            filters,
            apply_verification_filter=apply_verification_filter,
        )

    return apply_global_filter_cleanup(
        out,
        filters,
        remove_known_false_positives=remove_known_false_positives,
    )


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
# Database comparison helpers
# -----------------------------------------------------------------------------

def comparison_doi_key(value: Any) -> str:
    """Normalize DOI values for cross-database comparisons."""
    return doi_match_key(value)


def comparison_text_key(value: Any) -> str:
    """Normalize scalar text values for comparison."""
    text = clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def comparison_title_key(value: Any) -> str:
    """Normalize titles for optional no-DOI matching."""
    return comparison_text_key(value)


def prepare_comparison_frame(database_id: str, df: pd.DataFrame) -> pd.DataFrame:
    """Add comparison helper columns to one paper view."""
    out = df.copy()
    out["database_id"] = database_id
    out["database"] = database_label(database_id)
    out["doi_key"] = out["DOI"].apply(comparison_doi_key)
    out["title_key"] = out["title"].apply(comparison_title_key)
    out["author_count"] = out["authors"].apply(len)
    out["instrument_count"] = out["instruments"].apply(len)
    return out


def load_comparison_frames(database_ids: list[str]) -> dict[str, pd.DataFrame]:
    """Load lightweight paper views for the selected databases."""
    frames = {}
    for database_id in database_ids:
        frames[database_id] = prepare_comparison_frame(
            database_id,
            load_paper_view(database_id, str(DATA_DIR)),
        )
    return frames


def comparison_summary(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return one summary row per selected database."""
    rows = []
    for database_id, df in frames.items():
        masks = missing_metadata_masks(df)
        any_missing = pd.concat(masks.values(), axis=1).any(axis=1) if masks else pd.Series(False)
        rows.append(
            {
                "database": database_label(database_id),
                "database_id": database_id,
                "papers": len(df),
                "papers_with_doi": int((df["doi_key"] != "").sum()),
                "missing_doi": int((df["doi_key"] == "").sum()),
                "unique_dois": df.loc[df["doi_key"] != "", "doi_key"].nunique(),
                "unique_titles": df.loc[df["title_key"] != "", "title_key"].nunique(),
                "authors": int(df["authors"].explode().dropna().nunique()) if not df.empty else 0,
                "papers_with_authors": int(df["authors"].apply(bool).sum()) if not df.empty else 0,
                "papers_with_instruments": int(df["instruments"].apply(bool).sum()) if not df.empty else 0,
                "papers_missing_any_metadata": int(any_missing.sum()) if len(df) else 0,
            }
        )
    return pd.DataFrame(rows)


def comparison_overlap_matrix(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build a pairwise DOI overlap matrix for selected databases."""
    doi_sets = {
        database_id: set(df.loc[df["doi_key"] != "", "doi_key"])
        for database_id, df in frames.items()
    }
    rows = []
    for row_id in frames:
        row = {"database": database_label(row_id)}
        for col_id in frames:
            row[database_label(col_id)] = len(doi_sets[row_id] & doi_sets[col_id])
        rows.append(row)
    return pd.DataFrame(rows)


def comparison_combined_frame(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Concatenate selected database views for comparison charts and tables."""
    if not frames:
        return pd.DataFrame(columns=PAPER_VIEW_COLUMNS + ["database_id", "database", "doi_key"])
    return pd.concat(frames.values(), ignore_index=True)


def doi_presence_table(combined: pd.DataFrame) -> pd.DataFrame:
    """Return one row per DOI with database presence flags."""
    rows = []
    with_doi = combined[combined["doi_key"] != ""].copy()
    if with_doi.empty:
        return pd.DataFrame()

    database_labels = list(dict.fromkeys(with_doi["database"].tolist()))
    for doi_key, group in with_doi.groupby("doi_key"):
        databases = sorted(group["database"].unique())
        example = group.iloc[0]
        row = {
            "DOI": example["DOI"],
            "database_count": len(databases),
            "databases": "; ".join(databases),
            "title": example["title"],
            "year": example["year"],
            "journal": example["journal"],
            "publisher": example["publisher"],
        }
        for label in database_labels:
            row[label] = "yes" if label in databases else ""
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["database_count", "DOI"], ascending=[False, True])


def doi_uniqueness_table(presence: pd.DataFrame) -> pd.DataFrame:
    """Return DOI rows that appear in exactly one selected database."""
    if presence.empty:
        return presence
    return presence[presence["database_count"] == 1].copy()


def shared_doi_table(presence: pd.DataFrame) -> pd.DataFrame:
    """Return DOI rows that appear in multiple selected databases."""
    if presence.empty:
        return presence
    return presence[presence["database_count"] > 1].copy()


def metadata_conflict_table(combined: pd.DataFrame) -> pd.DataFrame:
    """Find shared DOI rows where selected metadata differs across databases."""
    rows = []
    with_doi = combined[combined["doi_key"] != ""].copy()
    if with_doi.empty:
        return pd.DataFrame()

    fields = [
        "title",
        "year",
        "journal",
        "publisher",
        "paper_type",
        "go_canada_status",
        "display_authors",
    ]
    for doi_key, group in with_doi.groupby("doi_key"):
        if group["database"].nunique() < 2:
            continue
        conflict_fields = [
            field
            for field in fields
            if group[field].map(comparison_text_key).nunique() > 1
        ]
        if not conflict_fields:
            continue
        for _, row in group.sort_values("database").iterrows():
            rows.append(
                {
                    "DOI": row["DOI"],
                    "conflict_fields": "; ".join(conflict_fields),
                    "database": row["database"],
                    "title": row["title"],
                    "year": row["year"],
                    "journal": row["journal"],
                    "publisher": row["publisher"],
                    "paper_type": row["paper_type"],
                    "go_canada_status": row["go_canada_status"],
                    "authors": row["display_authors"],
                }
            )
    return pd.DataFrame(rows)


def missing_metadata_comparison(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return missing metadata counts by database and field."""
    rows = []
    for database_id, df in frames.items():
        masks = missing_metadata_masks(df)
        for field, mask in masks.items():
            rows.append(
                {
                    "database": database_label(database_id),
                    "field": MISSING_METADATA_FIELD_LABELS.get(field, field),
                    "missing_papers": int(mask.sum()) if len(df) else 0,
                    "missing_percent": int(mask.sum()) / len(df) if len(df) else 0.0,
                }
            )
    return pd.DataFrame(rows)


def comparison_year_counts(combined: pd.DataFrame) -> pd.DataFrame:
    """Return paper counts by database and year."""
    work = combined.copy()
    work["year"] = pd.to_numeric(work["year"], errors="coerce")
    work = work.dropna(subset=["year"])
    if work.empty:
        return pd.DataFrame(columns=["database", "year", "papers"])
    work["year"] = work["year"].astype(int)
    return (
        work.groupby(["database", "year"])["paper_id"]
        .nunique()
        .reset_index(name="papers")
        .sort_values(["year", "database"])
    )


def comparison_category_counts(
    combined: pd.DataFrame,
    field: str,
    *,
    top_n: int = 20,
) -> pd.DataFrame:
    """Return per-database counts for a scalar or list-valued comparison field."""
    if field in {"authors", "instruments", "sources"}:
        out = combined.explode(field).rename(columns={field: "category"})
        out = out[out["category"].notna() & (out["category"] != "")]
    else:
        out = combined.rename(columns={field: "category"}).copy()
        out["category"] = out["category"].fillna("").astype(str).replace("", "Unknown")
    if out.empty:
        return pd.DataFrame(columns=["database", "category", "papers"])

    counts = (
        out.groupby(["database", "category"])["paper_id"]
        .nunique()
        .reset_index(name="papers")
    )
    top_categories = (
        counts.groupby("category")["papers"]
        .sum()
        .sort_values(ascending=False)
        .head(top_n)
        .index
    )
    return counts[counts["category"].isin(top_categories)].sort_values(["category", "database"])


def download_dataframe_button(df: pd.DataFrame, label: str, file_name: str) -> None:
    """Render a CSV download button for a dataframe."""
    st.download_button(
        label=label,
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=file_name,
        mime="text/csv",
    )


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

def render_compare_databases_page(active_db: str) -> None:
    """Render cross-database comparison tables and charts."""
    st.header("Compare Databases")

    database_ids = [database["id"] for database in DATABASES]
    default_ids = unique_preserve_order([active_db] + [db for db in database_ids if db != active_db])
    selected_ids = st.multiselect(
        "Databases",
        database_ids,
        default=st.session_state.get("comparison_database_ids", default_ids) or default_ids,
        format_func=database_label,
        key="comparison_database_ids",
    )
    selected_ids = [normalize_database_id(database_id) for database_id in selected_ids]

    if not selected_ids:
        st.info("Select at least one database.")
        return

    frames = load_comparison_frames(selected_ids)
    combined = comparison_combined_frame(frames)
    presence = doi_presence_table(combined)
    shared = shared_doi_table(presence)
    unique_only = doi_uniqueness_table(presence)
    conflicts = metadata_conflict_table(combined)
    summary = comparison_summary(frames)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Databases", f"{len(selected_ids):,}")
    c2.metric("Total paper rows", f"{len(combined):,}")
    c3.metric("Unique DOIs", f"{presence['DOI'].nunique() if not presence.empty else 0:,}")
    c4.metric("Shared DOI rows", f"{len(shared):,}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Only in one database", f"{len(unique_only):,}")
    c6.metric("Metadata conflict rows", f"{len(conflicts):,}")
    c7.metric("Rows without DOI", f"{int((combined['doi_key'] == '').sum()) if not combined.empty else 0:,}")
    c8.metric(
        "Rows with authors",
        f"{int(combined['authors'].apply(bool).sum()) if not combined.empty else 0:,}",
    )

    tabs = st.tabs(["Overview", "Graphs", "Overlap", "Metadata Quality"])

    with tabs[0]:
        st.subheader("Database Summary")
        summary_display = summary.copy()
        if not summary_display.empty:
            summary_display["metadata_missing_percent"] = (
                summary_display["papers_missing_any_metadata"] / summary_display["papers"]
            ).fillna(0.0)
        st.dataframe(summary_display, use_container_width=True, hide_index=True)
        download_dataframe_button(
            summary_display,
            "Download database summary",
            "database_comparison_summary.csv",
        )

        st.subheader("Pairwise DOI Overlap")
        overlap = comparison_overlap_matrix(frames)
        st.dataframe(overlap, use_container_width=True, hide_index=True)
        if len(overlap) > 1:
            heatmap_data = overlap.set_index("database")
            fig = px.imshow(
                heatmap_data,
                text_auto=True,
                aspect="auto",
                title="Shared DOI count by database pair",
            )
            st.plotly_chart(fig, use_container_width=True)

    with tabs[1]:
        st.subheader("Timeline")
        year_counts = comparison_year_counts(combined)
        if year_counts.empty:
            st.info("No year data available for the selected databases.")
        else:
            timeline_mode = st.radio(
                "Timeline chart",
                ["Line", "Stacked bar"],
                horizontal=True,
                key="comparison_timeline_mode",
            )
            if timeline_mode == "Line":
                fig = px.line(
                    year_counts,
                    x="year",
                    y="papers",
                    color="database",
                    markers=True,
                    title="Papers per year by database",
                )
            else:
                fig = px.bar(
                    year_counts,
                    x="year",
                    y="papers",
                    color="database",
                    title="Papers per year by database",
                )
            st.plotly_chart(fig, use_container_width=True)

        st.subheader("Category Comparison")
        c1, c2 = st.columns([2, 1])
        with c1:
            category_field = st.selectbox(
                "Compare by",
                [
                    "paper_type",
                    "go_canada_status",
                    "verification_status",
                    "publisher",
                    "journal",
                    "authors",
                    "instruments",
                    "sources",
                ],
                format_func=lambda value: {
                    "paper_type": "Paper type",
                    "go_canada_status": "GO Canada status",
                    "verification_status": "Verification status",
                    "publisher": "Publisher",
                    "journal": "Journal",
                    "authors": "Author",
                    "instruments": "Instrument/component",
                    "sources": "Source",
                }.get(value, value),
                key="comparison_category_field",
            )
        with c2:
            top_n = st.number_input(
                "Top N",
                min_value=3,
                max_value=100,
                value=20,
                key="comparison_top_n",
            )
        category_counts = comparison_category_counts(combined, category_field, top_n=int(top_n))
        if category_counts.empty:
            st.info("No category data available for the selected databases.")
        else:
            fig = px.bar(
                category_counts,
                x="category",
                y="papers",
                color="database",
                barmode="group",
                title="Papers by category and database",
            )
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(category_counts, use_container_width=True, hide_index=True)

    with tabs[2]:
        st.subheader("Shared DOIs")
        if shared.empty:
            st.info("No shared DOIs among the selected databases.")
        else:
            st.dataframe(shared, use_container_width=True, hide_index=True)
            download_dataframe_button(shared, "Download shared DOI report", "shared_dois.csv")

        st.subheader("Only in One Database")
        if unique_only.empty:
            st.info("No DOI appears in only one selected database.")
        else:
            database_options = ["All"] + sorted(unique_only["databases"].dropna().unique().tolist())
            selected_unique_database = st.selectbox(
                "Only-in database",
                database_options,
                key="comparison_unique_database",
            )
            unique_display = unique_only
            if selected_unique_database != "All":
                unique_display = unique_only[unique_only["databases"] == selected_unique_database]
            st.dataframe(unique_display, use_container_width=True, hide_index=True)
            download_dataframe_button(
                unique_display,
                "Download only-in-one-database report",
                "database_unique_dois.csv",
            )

        st.subheader("Metadata Conflicts on Shared DOIs")
        if conflicts.empty:
            st.info("No metadata conflicts found for shared DOIs.")
        else:
            conflict_fields = sorted(
                {
                    field
                    for value in conflicts["conflict_fields"].dropna()
                    for field in split_multi_value(value)
                }
            )
            selected_conflict_fields = st.multiselect(
                "Conflict fields",
                conflict_fields,
                default=conflict_fields,
                key="comparison_conflict_fields",
            )
            conflict_display = conflicts
            if selected_conflict_fields:
                conflict_display = conflicts[
                    conflicts["conflict_fields"].apply(
                        lambda value: contains_any(
                            split_multi_value(value),
                            selected_conflict_fields,
                        )
                    )
                ]
            st.dataframe(conflict_display, use_container_width=True, hide_index=True)
            download_dataframe_button(
                conflict_display,
                "Download metadata conflict report",
                "database_metadata_conflicts.csv",
            )

    with tabs[3]:
        st.subheader("Missing Metadata by Database")
        missing = missing_metadata_comparison(frames)
        if missing.empty:
            st.info("No metadata quality data available.")
        else:
            fig = px.bar(
                missing,
                x="field",
                y="missing_papers",
                color="database",
                barmode="group",
                title="Missing metadata fields by database",
            )
            st.plotly_chart(fig, use_container_width=True)
            missing_display = missing.copy()
            missing_display["missing_percent"] = missing_display["missing_percent"].map(
                lambda value: f"{value:.1%}"
            )
            st.dataframe(missing_display, use_container_width=True, hide_index=True)
            download_dataframe_button(
                missing,
                "Download missing metadata comparison",
                "database_missing_metadata_comparison.csv",
            )


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
    st.dataframe(
        table_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            COLUMN_LABELS["paper_url"]: st.column_config.LinkColumn(
                COLUMN_LABELS["paper_url"],
                display_text="Open paper",
            )
        },
    )


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
        updated = int((results["result"] == "updated").sum()) if not results.empty else 0
        skipped = int((results["result"] == "skipped").sum()) if not results.empty else 0
        st.success(f"Import complete: {added} added, {updated} updated, {skipped} skipped.")
        st.dataframe(results, use_container_width=True, hide_index=True)

    metadata_options = admin_metadata_options(tables)
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
                    if results["result"].isin(["added", "updated"]).any():
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
                journal = metadata_selectbox(
                    "Journal",
                    metadata_options["journals"],
                    key="manual_journal",
                )
                publisher = metadata_selectbox(
                    "Publisher",
                    metadata_options["publishers"],
                    key="manual_publisher",
                )
            with c2:
                paper_type = metadata_selectbox(
                    "Paper type",
                    metadata_options["paper_types"],
                    value="Research article",
                    key="manual_paper_type",
                )
                go_canada_status = metadata_selectbox(
                    "GO-Canada status",
                    metadata_options["go_canada_statuses"],
                    value="candidate",
                    key="manual_go_canada_status",
                )
                is_known_false_positive = st.checkbox("Known false positive")
                verification_status = st.selectbox(
                    "Verification status",
                    ["unchecked", "verified_true", "verified_false", "unsure"],
                )
                checked_date = st.date_input("Checked date", value=datetime.now().date())

            authors = metadata_multiselect(
                "Authors",
                metadata_options["authors"],
                key="manual_authors",
                help="Search existing authors or type a new author name.",
            )
            instruments = metadata_multiselect(
                "Instruments",
                metadata_options["instruments"],
                key="manual_instruments",
                help="Search existing instruments or type a new instrument name.",
            )
            instrument_status = st.text_input(
                "Instrument status",
                value="unchecked",
                help="Use one value or semicolon-separated values matching the instruments.",
            )
            source_name = metadata_multiselect(
                "Source name(s)",
                metadata_options["source_names"],
                values="Manual entry",
                key="manual_source_name",
                help="Search existing source names or type a new one.",
            )
            source_type = metadata_multiselect(
                "Source type(s)",
                metadata_options["source_types"],
                values="manual",
                key="manual_source_type",
                help="Search existing source types or type a new one.",
            )
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
                action, message = add_paper_record(working_tables, record)
                if action in {"added", "updated"}:
                    save_database_tables(working_tables)
                    st.session_state["last_import_results"] = [
                        {
                            "csv_row": "",
                            "title": title,
                            "DOI": doi,
                            "result": action,
                            "message": message,
                        }
                    ]
                    st.rerun()
                else:
                    st.error(f"Paper was not saved: {message}")


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


def find_paper_candidates(paper_view: pd.DataFrame, search_text: str, limit: int = 250) -> pd.DataFrame:
    """Return candidate papers for admin selectors."""
    candidates = paper_view.copy()
    if search_text.strip():
        candidates = candidates[paper_search_mask(candidates, search_text)]
    return candidates.sort_values(["year", "title"], ascending=[False, True]).head(limit)


def selected_paper_from_search(
    paper_view: pd.DataFrame,
    *,
    search_key: str,
    select_key: str,
    label: str = "Paper",
) -> str:
    """Render a paper search + select control and return the selected paper ID."""
    search_text = st.text_input("Find paper by title, DOI, author, or instrument", key=search_key)
    candidates = find_paper_candidates(paper_view, search_text)
    selected_state = clean_text(st.session_state.get(select_key))
    if selected_state and selected_state not in set(candidates.get("paper_id", [])):
        selected_row = paper_view[paper_view["paper_id"].fillna("").astype(str) == selected_state]
        if not selected_row.empty:
            candidates = pd.concat([selected_row, candidates], ignore_index=True)
    if candidates.empty:
        st.info("No papers match that search.")
        return ""

    paper_options = candidates["paper_id"].tolist()
    label_by_id = {
        row["paper_id"]: paper_label(row)
        for _, row in candidates.iterrows()
    }
    return st.selectbox(
        label,
        paper_options,
        format_func=lambda paper_id: label_by_id.get(paper_id, paper_id),
        key=select_key,
    )


def render_open_paper_button(selected_paper: pd.Series) -> None:
    """Render a button-like link to the paper landing page when available."""
    paper_url = clean_text(selected_paper.get("paper_url")) or doi_to_url(selected_paper.get("DOI"))
    if paper_url:
        st.link_button("Open paper page", paper_url)
    else:
        st.caption("No DOI or paper URL is available for this paper.")


def cross_database_matches_for_paper(
    selected_paper: pd.Series,
    current_database_id: str,
    data_dir: str = "data",
) -> pd.DataFrame:
    """Return matching papers in other databases by DOI."""
    doi_key = doi_match_key(selected_paper.get("DOI"))
    columns = [
        "database",
        "paper_id",
        "title",
        "verification_status",
        "components",
        "component_statuses",
    ]
    if not doi_key:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    current_database_id = normalize_database_id(current_database_id)
    for database in DATABASES:
        database_id = normalize_database_id(database["id"])
        if database_id == current_database_id:
            continue

        other_view = load_paper_view(database_id, data_dir)
        if other_view.empty or "DOI" not in other_view.columns:
            continue

        matches = other_view[other_view["DOI"].apply(doi_match_key) == doi_key]
        for _, match in matches.iterrows():
            rows.append(
                {
                    "database": database_label(database_id),
                    "paper_id": clean_text(match.get("paper_id")),
                    "title": clean_text(match.get("title")),
                    "verification_status": clean_text(match.get("verification_status"))
                    or "unchecked",
                    "components": join_list(match.get("instruments", []))
                    or "No components",
                    "component_statuses": join_list(match.get("instrument_statuses", []))
                    or "No component statuses",
                }
            )

    return pd.DataFrame(rows, columns=columns)


def render_cross_database_verification_context(
    selected_paper: pd.Series,
    current_database_id: str,
) -> None:
    """Show where the selected paper appears in other databases."""
    matches = cross_database_matches_for_paper(
        selected_paper,
        current_database_id,
        str(DATA_DIR),
    )

    st.markdown("#### Other Database Matches")
    if matches.empty:
        st.caption("No matching DOI found in the other databases.")
        return

    st.dataframe(
        matches.rename(
            columns={
                "database": "Database",
                "paper_id": "Paper ID",
                "title": "Title",
                "verification_status": "Verification status",
                "components": "Components",
                "component_statuses": "Component statuses",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )


def set_random_paper_selection(
    paper_view: pd.DataFrame,
    *,
    search_key: str,
    select_key: str,
    instrument_name: str = "",
) -> None:
    """Select a random paper, optionally limited to one instrument."""
    candidates = paper_view.copy()
    instrument_name = clean_text(instrument_name)
    if instrument_name:
        candidates = candidates[
            candidates["instruments"].apply(lambda values: instrument_name in values)
        ]
    if candidates.empty:
        st.warning("No papers match that random selection.")
        return

    selected_paper_id = random.choice(candidates["paper_id"].astype(str).tolist())
    st.session_state[search_key] = ""
    st.session_state[select_key] = selected_paper_id
    st.rerun()


def render_random_paper_controls(
    paper_view: pd.DataFrame,
    *,
    search_key: str,
    select_key: str,
) -> None:
    """Render quick random-paper controls for the admin verification workflow."""
    instrument_options = sorted_options(
        item
        for values in paper_view.get("instruments", pd.Series(dtype="object"))
        for item in values
    )
    random_cols = st.columns([1, 2, 1])
    with random_cols[0]:
        if st.button("Random paper", key=f"{select_key}_random_any"):
            set_random_paper_selection(
                paper_view,
                search_key=search_key,
                select_key=select_key,
            )
    with random_cols[1]:
        if instrument_options:
            random_instrument = st.selectbox(
                "Random within instrument",
                instrument_options,
                key=f"{select_key}_random_instrument",
            )
        else:
            random_instrument = ""
            st.caption("No instruments are available in this database.")
    with random_cols[2]:
        if st.button(
            "Random in instrument",
            key=f"{select_key}_random_instrument_button",
            disabled=not instrument_options,
        ):
            set_random_paper_selection(
                paper_view,
                search_key=search_key,
                select_key=select_key,
                instrument_name=random_instrument,
            )


def admin_metadata_options(tables: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    """Build controlled-vocabulary suggestions for admin metadata editors."""
    papers = tables.get("papers", pd.DataFrame())
    authors = tables.get("authors", pd.DataFrame())
    instruments = tables.get("instruments", pd.DataFrame())
    sources = tables.get("sources", pd.DataFrame())

    return {
        "authors": sorted_options(authors.get("author_name", [])),
        "instruments": ensure_options_include(
            instruments.get("instrument_name", []),
            ADDITIONAL_INSTRUMENT_FILTER_OPTIONS,
        ),
        "journals": sorted_options(papers.get("journal", [])),
        "publishers": sorted_options(papers.get("publisher", [])),
        "paper_types": ensure_options_include(
            papers.get("paper_type", []),
            ["Research article"],
        ),
        "go_canada_statuses": ensure_options_include(
            papers.get("go_canada_status", []),
            ["candidate", "confirmed", "excluded"],
        ),
        "source_names": ensure_options_include(
            sources.get("source_name", []),
            ["Manual entry", "New import batch"],
        ),
        "source_types": ensure_options_include(
            sources.get("source_type", []),
            ["manual", "csv_import"],
        ),
    }


def update_paper_metadata(
    tables: dict[str, pd.DataFrame],
    paper_id: str,
    record: dict[str, Any],
) -> tuple[bool, str]:
    """Update scalar paper metadata and normalized paper relationships."""
    title = clean_text(record.get("title"))
    doi = clean_text(record.get("DOI"))
    if not title:
        return False, "Missing title"

    working = tables
    papers = working["papers"].copy()
    for col in REQUIRED_COLUMNS["papers"]:
        if col in papers.columns:
            papers[col] = papers[col].astype("object")
    current_mask = papers["paper_id"].fillna("").astype(str) == paper_id
    if not bool(current_mask.any()):
        return False, "Paper not found"

    other_papers = papers[~current_mask].copy()
    duplicate_reason = existing_paper_match(other_papers, doi, title)
    if duplicate_reason:
        return False, duplicate_reason

    papers.loc[current_mask, "DOI"] = doi
    papers.loc[current_mask, "title"] = title
    papers.loc[current_mask, "year"] = clean_text(record.get("year"))
    papers.loc[current_mask, "journal"] = clean_text(record.get("journal"))
    papers.loc[current_mask, "publisher"] = clean_text(record.get("publisher"))
    papers.loc[current_mask, "paper_type"] = clean_text(record.get("paper_type"))
    papers.loc[current_mask, "go_canada_status"] = clean_text(record.get("go_canada_status"))
    papers.loc[current_mask, "is_known_false_positive"] = bool_storage_text(
        record.get("is_known_false_positive")
    )
    working["papers"] = papers

    paper_authors = working["paper_authors"].copy()
    paper_authors = paper_authors[
        paper_authors["paper_id"].fillna("").astype(str) != paper_id
    ].reset_index(drop=True)
    for order, author_name in enumerate(unique_preserve_order(split_multi_value(record.get("authors"))), start=1):
        author_id = get_or_create_author_id(working, author_name)
        paper_authors = append_row(
            paper_authors,
            {"paper_id": paper_id, "author_id": author_id, "author_order": order},
            REQUIRED_COLUMNS["paper_authors"],
        )
    working["paper_authors"] = paper_authors

    paper_instruments = working["paper_instruments"].copy()
    old_assignments = paper_instruments[
        paper_instruments["paper_id"].fillna("").astype(str) == paper_id
    ].copy()
    old_instrument_ids = set(old_assignments["instrument_id"].fillna("").astype(str))
    paper_instruments = paper_instruments[
        paper_instruments["paper_id"].fillna("").astype(str) != paper_id
    ].reset_index(drop=True)

    instrument_names = unique_preserve_order(split_multi_value(record.get("instruments")))
    instrument_statuses = split_multi_value(record.get("instrument_status"))
    new_instrument_ids: list[str] = []
    for index, instrument_name in enumerate(instrument_names):
        instrument_id = get_or_create_instrument_id(working, instrument_name)
        new_instrument_ids.append(instrument_id)
        instrument_status = (
            instrument_statuses[index]
            if index < len(instrument_statuses)
            else clean_text(record.get("instrument_status")) or "uses"
        )
        paper_instruments = append_row(
            paper_instruments,
            {
                "paper_id": paper_id,
                "instrument_id": instrument_id,
                "instrument_status": instrument_status,
            },
            REQUIRED_COLUMNS["paper_instruments"],
        )
    working["paper_instruments"] = paper_instruments

    removed_instrument_ids = old_instrument_ids - set(new_instrument_ids)
    if removed_instrument_ids:
        verification = working["verification"].copy()
        keep_mask = ~(
            (verification["paper_id"].fillna("").astype(str) == paper_id)
            & (verification["instrument_id"].fillna("").astype(str).isin(removed_instrument_ids))
        )
        working["verification"] = verification[keep_mask].reset_index(drop=True)

    paper_sources = working["paper_sources"].copy()
    paper_sources = paper_sources[
        paper_sources["paper_id"].fillna("").astype(str) != paper_id
    ].reset_index(drop=True)
    source_names = unique_preserve_order(split_multi_value(record.get("source_name") or record.get("source")))
    source_types = split_multi_value(record.get("source_type"))
    source_notes = split_multi_value(record.get("source_notes"))
    for index, source_name in enumerate(source_names):
        source_type = source_types[index] if index < len(source_types) else clean_text(record.get("source_type"))
        notes = source_notes[index] if index < len(source_notes) else clean_text(record.get("source_notes"))
        source_id = get_or_create_source_id(working, source_name, source_type, notes)
        paper_sources = append_row(
            paper_sources,
            {"paper_id": paper_id, "source_id": source_id},
            REQUIRED_COLUMNS["paper_sources"],
        )
    working["paper_sources"] = paper_sources

    return True, paper_id


def delete_paper_record(tables: dict[str, pd.DataFrame], paper_id: str) -> None:
    """Delete one paper and all normalized relationship rows."""
    tables["papers"] = tables["papers"][
        tables["papers"]["paper_id"].fillna("").astype(str) != paper_id
    ].reset_index(drop=True)
    for table_name in [
        "paper_authors",
        "paper_instruments",
        "verification",
        "paper_sources",
    ]:
        tables[table_name] = tables[table_name][
            tables[table_name]["paper_id"].fillna("").astype(str) != paper_id
        ].reset_index(drop=True)


def source_details_for_paper(tables: dict[str, pd.DataFrame], paper_id: str) -> tuple[str, str, str]:
    """Return semicolon-separated source fields for a paper."""
    paper_sources = tables["paper_sources"]
    sources = tables["sources"]
    if paper_sources.empty or sources.empty:
        return "", "", ""
    rows = paper_sources[
        paper_sources["paper_id"].fillna("").astype(str) == paper_id
    ].merge(sources, on="source_id", how="left")
    return (
        join_list(unique_preserve_order(rows.get("source_name", []))),
        join_list(unique_preserve_order(rows.get("source_type", []))),
        join_list(unique_preserve_order(rows.get("notes", []))),
    )


def paper_instrument_assignments(tables: dict[str, pd.DataFrame], paper_id: str) -> pd.DataFrame:
    """Return instrument assignments for one paper with instrument names attached."""
    paper_instruments = tables["paper_instruments"]
    instruments = tables["instruments"]
    if paper_instruments.empty:
        return pd.DataFrame(columns=["paper_id", "instrument_id", "instrument_status", "instrument_name"])
    assignments = paper_instruments[
        paper_instruments["paper_id"].fillna("").astype(str) == paper_id
    ].merge(instruments, on="instrument_id", how="left")
    return assignments.sort_values("instrument_name", na_position="last").reset_index(drop=True)


def add_instrument_assignment_to_paper(
    tables: dict[str, pd.DataFrame],
    paper_id: str,
    instrument_name: str,
    instrument_status: str = "uses",
) -> tuple[bool, str]:
    """Add one instrument assignment to a paper."""
    instrument_name = clean_text(instrument_name)
    if not instrument_name:
        return False, "Choose or type an instrument name."

    working_tables = {name: table.copy() for name, table in tables.items()}
    instrument_id = get_or_create_instrument_id(working_tables, instrument_name)
    paper_instruments = working_tables["paper_instruments"].copy()
    existing_mask = (
        (paper_instruments["paper_id"].fillna("").astype(str) == paper_id)
        & (paper_instruments["instrument_id"].fillna("").astype(str) == instrument_id)
    )
    if bool(existing_mask.any()):
        return False, f"{instrument_name} is already assigned to this paper."

    working_tables["paper_instruments"] = append_row(
        paper_instruments,
        {
            "paper_id": paper_id,
            "instrument_id": instrument_id,
            "instrument_status": clean_text(instrument_status) or "uses",
        },
        REQUIRED_COLUMNS["paper_instruments"],
    )
    save_database_tables(working_tables)
    return True, instrument_name


def save_paper_go_canada_status(
    tables: dict[str, pd.DataFrame],
    paper_id: str,
    go_canada_status: str,
) -> None:
    """Save paper-level GO Canada status without requiring instruments."""
    database_id = active_database_id()
    paper_id = clean_text(paper_id)
    go_canada_status = clean_text(go_canada_status) or "unknown"
    if not paper_id:
        return

    config = supabase_config()
    if config:
        url, key = config
        scoped = require_supabase_database_scoping(url, key, database_id)
        update_supabase_paper_fields(
            paper_id,
            {"go_canada_status": go_canada_status},
            url,
            key,
            database_id,
            scoped=scoped,
        )
        clear_database_caches()
        return

    papers = tables["papers"].copy()
    mask = papers["paper_id"].fillna("").astype(str) == paper_id
    if not bool(mask.any()):
        return
    papers.loc[mask, "go_canada_status"] = go_canada_status
    tables["papers"] = papers
    write_csv_table("papers", papers, database_id)
    clear_database_caches()


def save_paper_level_verification_status(
    tables: dict[str, pd.DataFrame],
    paper_id: str,
    verification_status: str,
) -> None:
    """Save paper-level verification for no-instrument databases."""
    save_paper_go_canada_status(
        tables,
        paper_id,
        go_canada_status_from_paper_level_verification(verification_status),
    )


def save_paper_verification_updates(
    tables: dict[str, pd.DataFrame],
    updates: list[dict[str, Any]],
) -> None:
    """Save multiple paper-instrument verification rows without replacing the database."""
    database_id = active_database_id()
    normalized_updates = []
    for update in updates:
        paper_id = clean_text(update.get("paper_id"))
        instrument_id = clean_text(update.get("instrument_id"))
        status = normalize_status(update.get("status"))
        if not paper_id or not instrument_id:
            continue
        normalized_updates.append(
            {
                "paper_id": paper_id,
                "instrument_id": instrument_id,
                "status": status,
                "evidence_quote": clean_text(update.get("evidence_quote")),
                "checked_date": clean_text(update.get("checked_date"))
                or datetime.now().isoformat(timespec="seconds"),
                "notes": clean_text(update.get("notes")),
            }
        )

    if not normalized_updates:
        return

    config = supabase_config()
    if config:
        url, key = config
        scoped = require_supabase_database_scoping(url, key, database_id)
        for row in normalized_updates:
            if row["status"] == "unchecked":
                delete_supabase_verification_row(
                    row["paper_id"],
                    row["instrument_id"],
                    url,
                    key,
                    database_id,
                    scoped=scoped,
                )
            else:
                upsert_supabase_verification_row(
                    row,
                    url,
                    key,
                    database_id,
                    scoped=scoped,
                )
        clear_database_caches()
        return

    verification = tables["verification"].copy()
    for update in normalized_updates:
        paper_id = update["paper_id"]
        instrument_id = update["instrument_id"]
        status = update["status"]
        keep_mask = ~(
            (verification["paper_id"].fillna("").astype(str) == paper_id)
            & (verification["instrument_id"].fillna("").astype(str) == instrument_id)
        )
        verification = verification[keep_mask].reset_index(drop=True)
        if status != "unchecked":
            verification = append_row(
                verification,
                update,
                REQUIRED_COLUMNS["verification"],
            )
    tables["verification"] = verification
    write_csv_table("verification", verification, database_id)
    clear_database_caches()


def render_paper_verification_controls(
    tables: dict[str, pd.DataFrame],
    selected_paper_id: str,
    *,
    key_prefix: str,
    allow_instrument_editing: bool = True,
    selected_paper: pd.Series | None = None,
) -> None:
    """Render per-instrument verification controls for one selected paper."""
    assignments = paper_instrument_assignments(tables, selected_paper_id)

    st.markdown("#### Instrument Verification")
    if allow_instrument_editing:
        metadata_options = admin_metadata_options(tables)
        with st.form(f"{key_prefix}_add_instrument_form"):
            add_cols = st.columns([2, 1, 1])
            with add_cols[0]:
                new_instrument = metadata_selectbox(
                    "Add instrument",
                    metadata_options["instruments"],
                    key=f"{key_prefix}_new_instrument",
                    help="Search existing instruments or type a new instrument name.",
                )
            with add_cols[1]:
                new_instrument_status = st.text_input(
                    "Instrument status",
                    value="uses",
                    key=f"{key_prefix}_new_instrument_status",
                )
            with add_cols[2]:
                add_submitted = st.form_submit_button("Add instrument")

        if add_submitted:
            try:
                ok, message = add_instrument_assignment_to_paper(
                    tables,
                    selected_paper_id,
                    new_instrument,
                    new_instrument_status,
                )
                if ok:
                    st.success(f"Added instrument: {message}")
                    st.rerun()
                else:
                    st.error(message)
            except requests.HTTPError as exc:
                response = exc.response
                detail = response.text if response is not None else str(exc)
                st.error(f"Supabase rejected the instrument assignment: {detail}")
            except Exception as exc:
                st.error(f"Could not add instrument: {exc}")
    else:
        st.caption("Use Paper Metadata to add or change instrument assignments.")

    if assignments.empty:
        st.info("This paper has no instrument assignments yet.")
        if selected_paper is None:
            return

        current_status = normalize_status(selected_paper.get("verification_status"))
        if current_status == "unchecked":
            current_status = paper_level_verification_from_go_canada_status(
                selected_paper.get("go_canada_status")
            )
        status_options = ["unchecked", "verified_true", "verified_false", "unsure"]
        default_index = status_options.index(current_status) if current_status in status_options else 0
        with st.form(f"{key_prefix}_paper_level_verification_form"):
            verification_status = st.selectbox(
                "Paper-level verification status",
                status_options,
                index=default_index,
                format_func={
                    "unchecked": "Unchecked",
                    "verified_true": "Verified true",
                    "verified_false": "Verified false",
                    "unsure": "Unsure",
                }.get,
                key=f"{key_prefix}_paper_verification_status",
            )
            submitted = st.form_submit_button("Save paper verification", type="primary")

        if submitted:
            try:
                save_paper_level_verification_status(
                    tables,
                    selected_paper_id,
                    verification_status,
                )
                st.success("Paper-level verification status saved.")
            except requests.HTTPError as exc:
                response = exc.response
                detail = response.text if response is not None else str(exc)
                st.error(f"Supabase rejected the paper verification update: {detail}")
            except Exception as exc:
                st.error(f"Could not save paper verification: {exc}")
        return

    existing = tables["verification"].copy()
    status_options = ["unchecked", "verified_true", "verified_false", "unsure"]
    with st.form(f"{key_prefix}_verification_form"):
        update_payloads: list[dict[str, Any]] = []
        for _, assignment in assignments.iterrows():
            instrument_id = clean_text(assignment.get("instrument_id"))
            instrument_name = clean_text(assignment.get("instrument_name")) or instrument_id
            existing_rows = existing[
                (existing["paper_id"].fillna("").astype(str) == selected_paper_id)
                & (existing["instrument_id"].fillna("").astype(str) == instrument_id)
            ]
            existing_row = existing_rows.iloc[0] if not existing_rows.empty else pd.Series(dtype="object")
            current_status = normalize_status(existing_row.get("status", "unchecked"))
            default_status_index = status_options.index(current_status) if current_status in status_options else 0

            st.markdown(f"**{instrument_name}**")
            c1, c2 = st.columns([1, 2])
            with c1:
                status = st.selectbox(
                    "Verification status",
                    status_options,
                    index=default_status_index,
                    key=f"{key_prefix}_{instrument_id}_status",
                )
                checked_date = st.text_input(
                    "Checked date/time",
                    value=clean_text(existing_row.get("checked_date")),
                    key=f"{key_prefix}_{instrument_id}_checked_date",
                )
            with c2:
                evidence_quote = st.text_area(
                    "Evidence quote",
                    value=clean_text(existing_row.get("evidence_quote")),
                    key=f"{key_prefix}_{instrument_id}_evidence",
                )
                notes = st.text_area(
                    "Notes",
                    value=clean_text(existing_row.get("notes")),
                    key=f"{key_prefix}_{instrument_id}_notes",
                )
            update_payloads.append(
                {
                    "paper_id": selected_paper_id,
                    "instrument_id": instrument_id,
                    "status": status,
                    "evidence_quote": evidence_quote,
                    "checked_date": checked_date,
                    "notes": notes,
                }
            )

        submitted = st.form_submit_button("Save all verification statuses", type="primary")

    if submitted:
        try:
            save_paper_verification_updates(tables, update_payloads)
            st.success("Verification statuses saved.")
        except requests.HTTPError as exc:
            response = exc.response
            detail = response.text if response is not None else str(exc)
            st.error(f"Supabase rejected the verification update: {detail}")
        except Exception as exc:
            st.error(f"Could not save verification statuses: {exc}")


def render_paper_metadata_editor(tables: dict[str, pd.DataFrame], paper_view: pd.DataFrame) -> None:
    """Render a full paper metadata editor."""
    st.subheader("Edit Paper Metadata")
    if paper_view.empty:
        st.info("No papers are loaded.")
        return

    selected_paper_id = selected_paper_from_search(
        paper_view,
        search_key="admin_metadata_search",
        select_key="admin_metadata_paper",
    )
    if not selected_paper_id:
        return

    selected_paper = paper_view[paper_view["paper_id"] == selected_paper_id].iloc[0]
    source_names, source_types, source_notes = source_details_for_paper(tables, selected_paper_id)
    metadata_options = admin_metadata_options(tables)
    render_open_paper_button(selected_paper)

    with st.form("admin_metadata_form"):
        c1, c2 = st.columns(2)
        with c1:
            title = st.text_input("Title", value=clean_text(selected_paper.get("title")))
            doi = st.text_input("DOI", value=clean_text(selected_paper.get("DOI")))
            year = st.text_input("Year", value=clean_text(selected_paper.get("year")))
            journal = metadata_selectbox(
                "Journal",
                metadata_options["journals"],
                value=clean_text(selected_paper.get("journal")),
                key=f"metadata_journal_{selected_paper_id}",
            )
            publisher = metadata_selectbox(
                "Publisher",
                metadata_options["publishers"],
                value=clean_text(selected_paper.get("publisher")),
                key=f"metadata_publisher_{selected_paper_id}",
            )
        with c2:
            paper_type = metadata_selectbox(
                "Paper type",
                metadata_options["paper_types"],
                value=clean_text(selected_paper.get("paper_type")),
                key=f"metadata_paper_type_{selected_paper_id}",
            )
            go_canada_status = metadata_selectbox(
                "GO-Canada status",
                metadata_options["go_canada_statuses"],
                value=clean_text(selected_paper.get("go_canada_status")),
                key=f"metadata_go_canada_status_{selected_paper_id}",
            )
            is_known_false_positive = st.checkbox(
                "Known false positive",
                value=parse_bool(selected_paper.get("is_known_false_positive")),
            )
            source_name = metadata_multiselect(
                "Source name(s)",
                metadata_options["source_names"],
                values=source_names,
                key=f"metadata_source_name_{selected_paper_id}",
                help="Search existing source names or type a new one.",
            )
            source_type = metadata_multiselect(
                "Source type(s)",
                metadata_options["source_types"],
                values=source_types,
                key=f"metadata_source_type_{selected_paper_id}",
                help="Search existing source types or type a new one.",
            )

        authors = metadata_multiselect(
            "Authors",
            metadata_options["authors"],
            values=clean_text(selected_paper.get("display_authors")),
            key=f"metadata_authors_{selected_paper_id}",
            help="Search existing authors or type a new author name.",
        )
        instruments = metadata_multiselect(
            "Instruments",
            metadata_options["instruments"],
            values=clean_text(selected_paper.get("display_instruments")),
            key=f"metadata_instruments_{selected_paper_id}",
            help="Search existing instruments or type a new instrument name.",
        )
        instrument_status = st.text_input(
            "Instrument status",
            value=join_list(selected_paper.get("instrument_statuses", [])),
            help="Use one value or semicolon-separated values matching the instruments.",
        )
        source_notes_input = st.text_area("Source notes", value=source_notes)

        save_submitted = st.form_submit_button("Save metadata", type="primary")

    if save_submitted:
        working_tables = {name: table.copy() for name, table in tables.items()}
        ok, message = update_paper_metadata(
            working_tables,
            selected_paper_id,
            {
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
                "source_name": source_name,
                "source_type": source_type,
                "source_notes": source_notes_input,
            },
        )
        if ok:
            try:
                save_database_tables(working_tables)
                st.success("Paper metadata saved.")
                st.rerun()
            except requests.HTTPError as exc:
                response = exc.response
                detail = response.text if response is not None else str(exc)
                st.error(f"Supabase rejected the metadata update: {detail}")
            except Exception as exc:
                st.error(f"Could not save paper metadata: {exc}")
        else:
            st.error(f"Paper metadata was not saved: {message}")

    st.divider()
    render_paper_verification_controls(
        tables,
        selected_paper_id,
        key_prefix=f"metadata_verify_{selected_paper_id}",
        selected_paper=selected_paper,
    )

    with st.expander("Delete this paper", expanded=False):
        confirm_delete = st.checkbox(
            "I understand this removes the paper and its relationships from the live database.",
            key="admin_delete_confirm",
        )
        if st.button("Delete selected paper", disabled=not confirm_delete):
            working_tables = {name: table.copy() for name, table in tables.items()}
            delete_paper_record(working_tables, selected_paper_id)
            try:
                save_database_tables(working_tables)
                st.success("Paper deleted.")
                st.rerun()
            except requests.HTTPError as exc:
                response = exc.response
                detail = response.text if response is not None else str(exc)
                st.error(f"Supabase rejected the delete: {detail}")
            except Exception as exc:
                st.error(f"Could not delete paper: {exc}")


def render_verification_editor(
    paper_view: pd.DataFrame,
    database_id: str,
    tables: dict[str, pd.DataFrame] | None = None,
) -> None:
    """Render an editor for paper-instrument verification rows."""
    st.subheader("Change Verification Status")
    if paper_view.empty:
        st.info("No papers are loaded.")
        return

    search_key = "admin_verify_search"
    select_key = "admin_verify_paper"
    render_random_paper_controls(
        paper_view,
        search_key=search_key,
        select_key=select_key,
    )

    selected_paper_id = selected_paper_from_search(
        paper_view,
        search_key=search_key,
        select_key=select_key,
    )
    if not selected_paper_id:
        return

    selected_paper = paper_view[paper_view["paper_id"] == selected_paper_id].iloc[0]
    st.write(f"**Title:** {clean_text(selected_paper['title'])}")
    st.write(f"**DOI:** {clean_text(selected_paper['DOI']) or 'Missing'}")
    st.write(f"**Current paper status:** {clean_text(selected_paper['verification_status'])}")
    st.write(f"**GO Canada status:** {clean_text(selected_paper.get('go_canada_status')) or 'unknown'}")
    render_open_paper_button(selected_paper)
    render_cross_database_verification_context(selected_paper, database_id)
    verification_tables = tables or load_verification_context(
        database_id,
        selected_paper_id,
        str(DATA_DIR),
    )
    render_paper_verification_controls(
        verification_tables,
        selected_paper_id,
        key_prefix=f"verify_{selected_paper_id}",
        allow_instrument_editing=tables is not None,
        selected_paper=selected_paper,
    )


def render_database_sync_page(tables: dict[str, pd.DataFrame]) -> None:
    """Render backend setup and sync controls."""
    database_id = active_database_id()
    st.subheader("Online Database")
    st.write(f"Current backend: **{database_backend_label()}**")
    st.write(f"Active database: **{database_label(database_id)}**")

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
        "The sync button replaces only the active Supabase database with the matching "
        "repository CSV database."
    )
    if st.button("Seed / replace active Supabase database from repository CSVs", type="primary"):
        try:
            csv_tables = load_csv_database(str(database_data_dir(database_id)))
            replace_supabase_database(csv_tables, database_id)
            st.success(
                f"{database_label(database_id)} was replaced with its repository CSV database."
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Could not seed {database_label(database_id)}: {exc}")

    st.download_button(
        label="Download current papers table",
        data=tables["papers"].to_csv(index=False).encode("utf-8"),
        file_name="papers.csv",
        mime="text/csv",
    )


def render_admin_presets_page() -> None:
    """Render admin controls for shared dashboard presets."""
    st.subheader("Shared Presets")
    st.write(
        "Shared presets are visible to everyone in the sidebar. "
        "Set filters and graph options on the dashboard first, then save them here."
    )

    if supabase_config():
        st.caption("Preset backend: Supabase")
    else:
        st.caption("Preset backend: local JSON files")
        if READ_ONLY_MODE:
            st.info("Local preset editing is disabled in read-only mode unless Supabase is configured.")

    presets = load_shared_presets()
    preset_names = sorted(presets, key=str.lower)
    current_snapshot = current_view_snapshot()

    with st.expander("Current dashboard/view state", expanded=False):
        st.json(current_snapshot)

    st.subheader("Create or overwrite from current view")
    selected_existing = st.selectbox(
        "Existing preset",
        [""] + preset_names,
        key="admin_existing_preset",
    )
    preset_name = st.text_input(
        "Preset name",
        value=selected_existing,
        key="admin_preset_name",
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save current view as shared preset", type="primary"):
            try:
                save_shared_preset(preset_name, current_snapshot)
                st.success(f"Saved preset: {clean_preset_name(preset_name)}")
                st.rerun()
            except requests.HTTPError as exc:
                response = exc.response
                detail = response.text if response is not None else str(exc)
                st.error(f"Supabase rejected the preset save: {detail}")
            except Exception as exc:
                st.error(f"Could not save preset: {exc}")
    with c2:
        if st.button("Delete selected preset", disabled=not selected_existing):
            try:
                delete_shared_preset(selected_existing)
                st.success(f"Deleted preset: {selected_existing}")
                st.rerun()
            except requests.HTTPError as exc:
                response = exc.response
                detail = response.text if response is not None else str(exc)
                st.error(f"Supabase rejected the preset delete: {detail}")
            except Exception as exc:
                st.error(f"Could not delete preset: {exc}")

    st.subheader("Advanced JSON editor")
    json_preset_name = st.selectbox(
        "Preset to edit as JSON",
        [""] + preset_names,
        key="admin_json_preset",
    )
    json_default = json.dumps(presets.get(json_preset_name, current_snapshot), indent=2)
    edited_json = st.text_area(
        "Preset JSON",
        value=json_default,
        height=260,
        key="admin_preset_json",
    )
    if st.button("Save JSON preset", disabled=not json_preset_name):
        try:
            parsed = json.loads(edited_json)
            if not isinstance(parsed, dict):
                raise ValueError("Preset JSON must be an object.")
            save_shared_preset(json_preset_name, parsed)
            st.success(f"Saved preset: {json_preset_name}")
            st.rerun()
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")
        except requests.HTTPError as exc:
            response = exc.response
            detail = response.text if response is not None else str(exc)
            st.error(f"Supabase rejected the preset save: {detail}")
        except Exception as exc:
            st.error(f"Could not save preset: {exc}")


def render_admin_editor_page(active_db: str) -> None:
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
    admin_tool = st.radio(
        "Admin tool",
        [
            "Verification Status",
            "Paper Metadata",
            "Add / Import Papers",
            "Shared Presets",
            "Online Database",
        ],
        horizontal=True,
        key="admin_tool",
    )

    if admin_tool == "Shared Presets":
        render_admin_presets_page()
        return

    if admin_tool == "Add / Import Papers":
        tables = load_database(active_db, str(DATA_DIR))
        render_add_import_papers_page(tables, admin_mode=True)
        return

    if admin_tool == "Online Database":
        tables = load_database(active_db, str(DATA_DIR))
        render_database_sync_page(tables)
        return

    if admin_tool == "Paper Metadata":
        tables = load_database(active_db, str(DATA_DIR))
        paper_view = load_paper_view(active_db, str(DATA_DIR))
        render_paper_metadata_editor(tables, paper_view)
    elif admin_tool == "Verification Status":
        paper_view = load_paper_view(active_db, str(DATA_DIR))
        tables = None if supabase_config() else load_database(active_db, str(DATA_DIR))
        render_verification_editor(paper_view, active_db, tables)


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

    active_db = render_database_selector()
    page_options = [
        "Dashboard",
        "Compare Databases",
        "Filter + Paper List",
        "Graphs",
        "Data Quality",
        "Export",
    ]
    if not READ_ONLY_MODE:
        page_options.insert(4, "Add / Import Papers")
    if admin_password_configured():
        page_options.append("Admin Editor")
    page = st.sidebar.radio("Page", page_options)

    if page == "Admin Editor":
        st.sidebar.divider()
        st.sidebar.caption(f"Database backend: {database_backend_label()}")
        st.sidebar.caption(f"Active database: {database_label(active_db)}")
        render_admin_editor_page(active_db)
        return

    if page == "Add / Import Papers":
        tables = load_database(active_db, str(DATA_DIR))
        st.sidebar.divider()
        st.sidebar.caption(f"Database backend: {database_backend_label()}")
        st.sidebar.caption(f"Active database: {database_label(active_db)}")
        render_add_import_papers_page(tables)
        return

    if page == "Compare Databases":
        st.sidebar.divider()
        st.sidebar.caption(f"Database backend: {database_backend_label()}")
        st.sidebar.caption(f"Active database: {database_label(active_db)}")
        render_compare_databases_page(active_db)
        return

    paper_view = load_paper_view(active_db, str(DATA_DIR))
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
    st.sidebar.caption(f"Active database: {database_label(active_db)}")
    st.sidebar.caption(f"Loaded papers: {len(paper_view):,}")
    st.sidebar.caption(f"Current filtered papers: {len(filtered_df):,}")

    if paper_view.empty:
        st.info(
            f"{database_label(active_db)} is empty. "
            "Use Add / Import Papers or the Admin Editor to add papers to this database."
        )

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
