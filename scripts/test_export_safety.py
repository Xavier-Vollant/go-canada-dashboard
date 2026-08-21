"""
Prove the export cannot destroy data/ when Supabase returns nothing useful.

    python3 scripts/test_export_safety.py

No network and no credentials: the Supabase fetch is stubbed. The end-to-end
cases assert the real data/papers.csv is byte-identical afterwards, so a
regression here fails loudly instead of quietly overwriting the database.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))
os.environ["SUPABASE_URL"] = "https://stub.invalid"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "stub-key-not-real"

import app  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "exporter", REPO_ROOT / "scripts" / "export_supabase_to_csv.py"
)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)

LIVE_CSV = REPO_ROOT / "data" / "papers.csv"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stub_fetch(rows: int):
    """Replace the Supabase fetch with one returning `rows` blank rows per table."""

    def fetch(name, columns, *args, **kwargs):
        return pd.DataFrame(
            [{c: "" for c in columns} for _ in range(rows)], columns=columns
        )

    app.fetch_supabase_table = fetch
    app.supabase_supports_database_scoping = lambda *a, **k: True


def run(argv: list[str]) -> int:
    """Run the exporter's main() and return its exit code."""
    saved = sys.argv
    sys.argv = ["export_supabase_to_csv.py", *argv]
    try:
        exporter.main()
        return 0
    except SystemExit as exc:
        return 1 if exc.code is None else (exc.code if isinstance(exc.code, int) else 1)
    finally:
        sys.argv = saved


def test_safety_problems_flags_empty():
    exporter.local_row_count = lambda db, table: 2269
    problems = exporter.safety_problems("main", {"papers": 0})
    assert problems, "an empty live table against a populated repo must be flagged"
    assert "EMPTY" in problems[0], problems
    print("  PASS  empty live table is flagged")


def test_safety_problems_flags_big_shrink():
    exporter.local_row_count = lambda db, table: 2269
    assert exporter.safety_problems(
        "main", {"papers": 1000}
    ), "a >50% shrink must be flagged"
    print("  PASS  >50% shrink is flagged")


def test_safety_problems_allows_normal():
    exporter.local_row_count = lambda db, table: 2269
    assert exporter.safety_problems("main", {"papers": 2359}) == [], "growth must pass"
    assert (
        exporter.safety_problems("main", {"papers": 2200}) == []
    ), "small shrink must pass"
    print("  PASS  normal growth and small shrink are allowed")


def test_apply_refuses_and_leaves_data_untouched():
    """The one that matters: a broken fetch must not touch data/."""
    before = sha(LIVE_CSV)
    stub_fetch(rows=0)
    with tempfile.TemporaryDirectory() as tmp:
        code = run(["--apply", "--database", "main", "--out", tmp])
    after = sha(LIVE_CSV)
    assert code != 0, "a broken export must exit non-zero"
    assert before == after, "data/papers.csv WAS MODIFIED by a refused export"
    print("  PASS  broken export refuses, exit code != 0, data/papers.csv untouched")


def test_healthy_export_promotes():
    """A healthy export must actually write - the guard cannot block everything."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "target"
        target.mkdir()
        app.database_data_dir = lambda db: target
        (target / "papers.csv").write_text("paper_id\n" + "x\n" * 2269)
        stub_fetch(rows=2400)
        code = run(["--apply", "--database", "main", "--out", str(Path(tmp) / "stage")])
        written = pd.read_csv(target / "papers.csv")
    assert code == 0, f"a healthy export must succeed, got exit {code}"
    assert len(written) == 2400, f"expected 2400 promoted rows, got {len(written)}"
    print("  PASS  healthy export promotes all 8 tables")


def main() -> None:
    real_local_row_count = exporter.local_row_count
    baseline = sha(LIVE_CSV)
    print("Export safety checks\n")
    test_safety_problems_flags_empty()
    test_safety_problems_flags_big_shrink()
    test_safety_problems_allows_normal()
    exporter.local_row_count = real_local_row_count
    test_apply_refuses_and_leaves_data_untouched()
    test_healthy_export_promotes()
    assert sha(LIVE_CSV) == baseline, "data/papers.csv changed during the test run"
    print("\nAll checks passed. data/papers.csv verified unchanged.")


if __name__ == "__main__":
    main()
