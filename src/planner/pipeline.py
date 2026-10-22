"""Runs Stages 1-6 and returns everything the outputs need."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from planner.clean import clean
from planner.common import ISSUE_COLUMNS, PlannerError, parse_date
from planner.exceptions import classify
from planner.forecast import apply_forecast
from planner.load import load_all
from planner.organise import organise
from planner.rules import apply_rules


@dataclass
class PipelineResult:
    run_date: dt.date
    table: pd.DataFrame
    issues: pd.DataFrame
    row_counts: dict
    hashes: dict
    notes: list = field(default_factory=list)


def resolve_run_date(raw: dict, requested: dt.date | None, notes: list) -> dt.date:
    dates = {parse_date(x) for x in raw["inventory"]["As_Of_Date"]} - {None}
    if requested is None:
        if not dates:
            raise PlannerError("No readable As_Of_Date in current_inventory.csv and no --run-date given")
        requested = max(dates)
    if len(dates) > 1:
        notes.append(f"Inventory As_Of_Date differs across rows: {sorted(str(d) for d in dates)}")
    if dates and requested not in dates:
        notes.append(f"Run date {requested} differs from inventory As_Of_Date {sorted(str(d) for d in dates)}")
    return requested


def run_pipeline(data_dir: str | Path, run_date: dt.date | None, cfg: dict) -> PipelineResult:
    raw, hashes = load_all(data_dir, cfg)
    notes: list[str] = []
    run_date = resolve_run_date(raw, run_date, notes)
    cleaned, issues = clean(raw, cfg, run_date)
    table = organise(cleaned, cfg, run_date)
    table = apply_rules(table, cfg)
    table = apply_forecast(table, cleaned, cfg, run_date)
    table = classify(table, issues, cfg, run_date, cleaned["distributor_sales"])
    counts = {k: (0 if v is None else len(v)) for k, v in raw.items()}
    return PipelineResult(run_date, table, pd.DataFrame(issues, columns=ISSUE_COLUMNS), counts, hashes, notes)
