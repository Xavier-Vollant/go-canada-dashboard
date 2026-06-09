from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import pandas as pd


PAPER_COLUMNS = [
    "paper_id",
    "DOI",
    "title",
    "year",
    "journal",
    "publisher",
    "paper_type",
    "go_canada_status",
    "is_known_false_positive",
]

AUTHOR_COLUMNS = ["author_id", "author_name"]
PAPER_AUTHOR_COLUMNS = ["paper_id", "author_id", "author_order"]
INSTRUMENT_COLUMNS = ["instrument_id", "instrument_name"]
PAPER_INSTRUMENT_COLUMNS = ["paper_id", "instrument_id", "instrument_status"]
VERIFICATION_COLUMNS = [
    "paper_id",
    "instrument_id",
    "status",
    "evidence_quote",
    "checked_date",
    "notes",
]
SOURCE_COLUMNS = ["source_id", "source_name", "source_type", "notes"]
PAPER_SOURCE_COLUMNS = ["paper_id", "source_id"]


def clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def split_list(value: Any) -> list[str]:
    text = clean(value)
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def normalized_key(value: Any) -> str:
    return " ".join(clean(value).lower().split())


def next_id(prefix: str, index: int) -> str:
    return f"{prefix}{index:05d}"


def review_decision_to_status(decision: Any) -> str:
    decision_key = normalized_key(decision)
    if decision_key == "correct instrument/component":
        return "verified_true"
    if decision_key == "incorrect instrument/component":
        return "verified_false"
    if decision_key == "unsure":
        return "unsure"
    return "unchecked"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def build_tables(import_df: pd.DataFrame, review_df: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    papers: list[dict[str, Any]] = []
    authors: list[dict[str, Any]] = []
    paper_authors: list[dict[str, Any]] = []
    instruments: list[dict[str, Any]] = []
    paper_instruments: list[dict[str, Any]] = []
    verification: list[dict[str, Any]] = []
    paper_sources: list[dict[str, Any]] = []

    source_rows = [
        {
            "source_id": "S00001",
            "source_name": "GO-Canada Database Excel import",
            "source_type": "excel_import",
            "notes": "Metadata filled from DOI post-processing; instruments came from the Excel file.",
        }
    ]

    author_ids: dict[str, str] = {}
    instrument_ids: dict[str, str] = {}
    paper_id_by_doi: dict[str, str] = {}
    paper_instrument_id_by_key: dict[tuple[str, str], str] = {}

    for paper_index, (_, row) in enumerate(import_df.iterrows(), start=1):
        paper_id = next_id("P", paper_index)
        doi = clean(row.get("DOI"))
        paper_id_by_doi[normalized_key(doi)] = paper_id

        year = clean(row.get("year"))
        if year.endswith(".0"):
            year = year[:-2]

        papers.append(
            {
                "paper_id": paper_id,
                "DOI": doi,
                "title": clean(row.get("title")),
                "year": year,
                "journal": clean(row.get("journal")),
                "publisher": clean(row.get("publisher")),
                "paper_type": clean(row.get("paper_type")),
                "go_canada_status": clean(row.get("go_canada_status")) or "candidate",
                "is_known_false_positive": clean(row.get("is_known_false_positive")).lower()
                in {"true", "1", "yes"},
            }
        )

        for author_order, author_name in enumerate(split_list(row.get("authors")), start=1):
            author_key = normalized_key(author_name)
            if author_key not in author_ids:
                author_id = next_id("A", len(author_ids) + 1)
                author_ids[author_key] = author_id
                authors.append({"author_id": author_id, "author_name": author_name})
            paper_authors.append(
                {
                    "paper_id": paper_id,
                    "author_id": author_ids[author_key],
                    "author_order": author_order,
                }
            )

        instrument_names = split_list(row.get("instruments"))
        instrument_statuses = split_list(row.get("instrument_status"))
        for index, instrument_name in enumerate(instrument_names):
            instrument_key = normalized_key(instrument_name)
            if instrument_key not in instrument_ids:
                instrument_id = next_id("I", len(instrument_ids) + 1)
                instrument_ids[instrument_key] = instrument_id
                instruments.append(
                    {"instrument_id": instrument_id, "instrument_name": instrument_name}
                )
            instrument_status = (
                instrument_statuses[index]
                if index < len(instrument_statuses)
                else clean(row.get("instrument_status")) or "uses"
            )
            instrument_id = instrument_ids[instrument_key]
            paper_instruments.append(
                {
                    "paper_id": paper_id,
                    "instrument_id": instrument_id,
                    "instrument_status": instrument_status,
                }
            )
            paper_instrument_id_by_key[(normalized_key(doi), instrument_key)] = instrument_id

        paper_sources.append({"paper_id": paper_id, "source_id": "S00001"})

    if not review_df.empty:
        verified_reviews = review_df[review_df["review_status"].fillna("").astype(str) == "verified"]
        for _, review in verified_reviews.iterrows():
            doi_key = normalized_key(review.get("DOI"))
            instrument_key = normalized_key(review.get("instrument"))
            paper_id = paper_id_by_doi.get(doi_key)
            instrument_id = paper_instrument_id_by_key.get((doi_key, instrument_key))
            status = review_decision_to_status(review.get("review_decision"))
            if not paper_id or not instrument_id or status == "unchecked":
                continue

            notes_parts = [
                f"review_decision={clean(review.get('review_decision'))}",
                f"corrected_instrument={clean(review.get('corrected_instrument'))}",
                clean(review.get("review_notes")),
            ]
            verification.append(
                {
                    "paper_id": paper_id,
                    "instrument_id": instrument_id,
                    "status": status,
                    "evidence_quote": clean(review.get("evidence_quote")),
                    "checked_date": clean(review.get("reviewed_at")),
                    "notes": " | ".join(part for part in notes_parts if part),
                }
            )

    return {
        "papers": papers,
        "authors": authors,
        "paper_authors": paper_authors,
        "instruments": instruments,
        "paper_instruments": paper_instruments,
        "verification": verification,
        "sources": source_rows,
        "paper_sources": paper_sources,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--import-csv", required=True, type=Path)
    parser.add_argument("--review-csv", required=True, type=Path)
    parser.add_argument("--data-dir", default=Path("data"), type=Path)
    args = parser.parse_args()

    import_df = read_csv(args.import_csv)
    review_df = read_csv(args.review_csv)
    tables = build_tables(import_df, review_df)

    write_csv(args.data_dir / "papers.csv", tables["papers"], PAPER_COLUMNS)
    write_csv(args.data_dir / "authors.csv", tables["authors"], AUTHOR_COLUMNS)
    write_csv(args.data_dir / "paper_authors.csv", tables["paper_authors"], PAPER_AUTHOR_COLUMNS)
    write_csv(args.data_dir / "instruments.csv", tables["instruments"], INSTRUMENT_COLUMNS)
    write_csv(
        args.data_dir / "paper_instruments.csv",
        tables["paper_instruments"],
        PAPER_INSTRUMENT_COLUMNS,
    )
    write_csv(args.data_dir / "verification.csv", tables["verification"], VERIFICATION_COLUMNS)
    write_csv(args.data_dir / "sources.csv", tables["sources"], SOURCE_COLUMNS)
    write_csv(args.data_dir / "paper_sources.csv", tables["paper_sources"], PAPER_SOURCE_COLUMNS)

    print(f"Papers: {len(tables['papers']):,}")
    print(f"Authors: {len(tables['authors']):,}")
    print(f"Instruments: {len(tables['instruments']):,}")
    print(f"Paper-instrument rows: {len(tables['paper_instruments']):,}")
    print(f"Verification rows: {len(tables['verification']):,}")


if __name__ == "__main__":
    main()
