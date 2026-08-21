"""
Pull every Supabase database down to CSV.

Supabase is the source of truth; this brings it into the repo. The export always
lands in a staging directory first and is checked before anything in data/ is
touched, so a failed or partial fetch can never overwrite good CSVs.

Credentials come from the environment, never the command line, so the key does
not land in shell history:

    export SUPABASE_URL="https://your-project.supabase.co"
    export SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"
    python3 scripts/export_supabase_to_csv.py            # stage + report only
    python3 scripts/export_supabase_to_csv.py --apply    # stage, check, then promote

Exits non-zero when a promotion is refused, so a scheduled job fails loudly
instead of committing a bad snapshot.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

import app  # noqa: E402

# A live table this much smaller than the repo copy means a broken fetch far more
# often than it means a real deletion. --force is the deliberate override.
SHRINK_LIMIT = 0.5


def export_database(
    database_id: str, url: str, key: str, out_dir: Path
) -> dict[str, int]:
    """Write one Supabase database into a staging directory. Returns row counts."""
    scoped = app.supabase_supports_database_scoping(url, key)
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name, columns in app.REQUIRED_COLUMNS.items():
        df = app.fetch_supabase_table(
            name, columns, url, key, database_id, scoped=scoped
        )
        app.dataframe_for_storage(df, columns).to_csv(
            out_dir / f"{name}.csv", index=False
        )
        counts[name] = len(df)
    return counts


def local_row_count(database_id: str, table: str) -> int | None:
    """Row count of the CSV currently in the repo, or None when there isn't one."""
    path = app.database_data_dir(database_id) / f"{table}.csv"
    if not path.exists():
        return None
    return len(pd.read_csv(path, low_memory=False))


def safety_problems(database_id: str, counts: dict[str, int]) -> list[str]:
    """Reasons promoting this export would destroy data. Empty means safe."""
    problems = []
    for table, live in counts.items():
        local = local_row_count(database_id, table)
        if not local:
            continue
        if live == 0:
            problems.append(
                f"{database_id}/{table}: live is EMPTY but the repo has {local:,} rows"
            )
        elif live < local * SHRINK_LIMIT:
            problems.append(
                f"{database_id}/{table}: live {live:,} rows is under half the repo's {local:,}"
            )
    return problems


def promote(database_id: str, staged: Path) -> int:
    """Copy a checked staging directory over the repo CSVs. Returns files written."""
    target = app.database_data_dir(database_id)
    target.mkdir(parents=True, exist_ok=True)
    written = 0
    for name in app.REQUIRED_COLUMNS:
        shutil.copyfile(staged / f"{name}.csv", target / f"{name}.csv")
        written += 1
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="data/_supabase_export",
        help="Staging directory (default: data/_supabase_export).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="After the safety check passes, copy the export over the repo CSVs.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Promote even when the safety check objects. Only for real bulk deletions.",
    )
    parser.add_argument(
        "--database",
        action="append",
        help="Only export this database id. Repeatable. Default: all of them.",
    )
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get(
        "SUPABASE_ANON_KEY", ""
    )
    if not url or not key:
        sys.exit(
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment first."
        )

    database_ids = args.database or [db["id"] for db in app.DATABASES]
    unknown = sorted(set(database_ids) - app.VALID_DATABASE_IDS)
    if unknown:
        sys.exit(f"Unknown database id(s): {', '.join(unknown)}")

    rows = []
    staged_counts: dict[str, dict[str, int]] = {}
    for database_id in database_ids:
        staged = Path(args.out) / database_id
        print(f"Exporting {database_id} -> {staged}")
        counts = export_database(database_id, url, key, staged)
        staged_counts[database_id] = counts
        for table, live in counts.items():
            local = local_row_count(database_id, table)
            rows.append(
                {
                    "database": database_id,
                    "table": table,
                    "live": live,
                    "repo_csv": "-" if local is None else local,
                    "delta": "-" if local is None else live - local,
                }
            )

    report = pd.DataFrame(rows)
    print("\nLive Supabase vs CSV currently in the repo:")
    print(report.to_string(index=False))

    problems = [
        p for db in database_ids for p in safety_problems(db, staged_counts[db])
    ]
    if problems:
        print("\nSAFETY CHECK FAILED:")
        for problem in problems:
            print(f"  - {problem}")

    if not args.apply:
        print(f"\nStaged only. Review {args.out}, then re-run with --apply to promote.")
        sys.exit(1 if problems else 0)

    if problems and not args.force:
        sys.exit(
            "\nRefusing to overwrite data/ - the export looks broken, not smaller.\n"
            "Check the credentials and that the Supabase project is awake, then retry.\n"
            "Pass --force only if these deletions are real."
        )

    if problems:
        print("\n--force given: promoting despite the safety check.")
    total = sum(promote(db, Path(args.out) / db) for db in database_ids)
    print(
        f"\nPromoted {total} file(s) into data/. Review 'git diff' before committing."
    )


if __name__ == "__main__":
    main()
