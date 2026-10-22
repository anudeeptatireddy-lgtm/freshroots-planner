"""Shared helpers: errors, issue records, ISO-week and date utilities, config loading."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

ISSUE_COLUMNS = ["file", "row_ref", "sku_id", "issue", "action", "severity"]
# severity: "review" -> routes the SKU to a human (DATA_ISSUE); "info" -> logged only.


class PlannerError(Exception):
    """A problem that must stop the run, with a message for the user."""


def make_issue(file, row_ref, issue, action, sku_id="", severity="review"):
    return {"file": file, "row_ref": row_ref, "sku_id": sku_id, "issue": issue,
            "action": action, "severity": severity}


_WEEK = re.compile(r"^(\d{4})-?W(\d{1,2})$", re.IGNORECASE)


def parse_iso_week(text) -> dt.date | None:
    """'2026-W42' -> Monday of that ISO week; None if unparseable."""
    m = _WEEK.match(str(text).strip())
    if not m:
        return None
    try:
        return dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return None


def iso_week_label(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def parse_date(text) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(text).strip())
    except ValueError:
        return None


def monday_of(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def window_weeks(run_date: dt.date, n: int) -> list[dt.date]:
    """The n most recent COMPLETE weeks before run_date, oldest first (Mondays)."""
    last = monday_of(run_date) - dt.timedelta(days=7)
    return [last - dt.timedelta(days=7 * (n - 1 - i)) for i in range(n)]


def forecast_week_starts(run_date: dt.date, n: int) -> list[dt.date]:
    first = monday_of(run_date)
    return [first + dt.timedelta(days=7 * i) for i in range(n)]


def load_config(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)
