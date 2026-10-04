"""Shared safety gates for everything that touches the gold set."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TEST_WARNING = ("WARNING: you are using the TEST split. Tuning prompts, models, or retrieval settings on test data invalidates the results; "
                "any change made after seeing these numbers needs a fresh test set.")


def gate_split(split: str, confirm_test: bool) -> None:
    if split == "test" and not confirm_test:
        sys.exit("REFUSING to use the TEST split without --confirm-test.\nThe test split must stay untouched until the system is frozen; use --split dev while iterating.")
    if split == "test": print(TEST_WARNING, file=sys.stderr)


def require_valid_gold(gold_dir: Path, allow_errors: bool = False) -> None:
    f = gold_dir / "validation_summary.json"
    if not f.exists(): sys.exit("No validation_summary.json: run scripts/gold_convert.py first.")
    if json.loads(f.read_text())["errors"] and not allow_errors:
        sys.exit("Gold validation has errors (see validation_report.md). Fix the CSVs and re-run gold_convert.py, or pass --allow-gold-errors.")
