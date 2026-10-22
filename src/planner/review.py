"""Stage 7 logic (UI-free): decisions, the review log and the override rate."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from planner.common import PlannerError

LOG_COLUMNS = ["sku_id", "system_qty", "final_qty", "decision", "reviewer", "note", "timestamp"]
DECISIONS = ("approve", "edit", "reject")
SYSTEM_PREFIX = "system:"
AUTO_REVIEWER = "system:auto-approve-rules-only"


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def make_decision(sku_id: str, system_qty: float, decision: str, reviewer: str,
                  final_qty: float | None = None, note: str = "", timestamp: str | None = None) -> dict:
    if decision not in DECISIONS:
        raise PlannerError(f"decision must be one of {DECISIONS}, got '{decision}'")
    if not str(reviewer).strip():
        raise PlannerError("Reviewer name is required")
    if decision == "approve":
        final_qty = system_qty
    elif decision == "reject":
        final_qty = 0.0
    else:
        if final_qty is None or final_qty < 0 or float(final_qty) != int(final_qty):
            raise PlannerError("Edited quantity must be a whole number >= 0")
    return {"sku_id": sku_id, "system_qty": float(system_qty), "final_qty": float(final_qty), "decision": decision,
            "reviewer": reviewer.strip(), "note": note.strip(), "timestamp": timestamp or _now()}


def auto_decisions(table: pd.DataFrame) -> list[dict]:
    """Approve only AUTO_APPROVED lines at the system quantity."""
    return [make_decision(r.sku_id, r.order_qty, "approve", AUTO_REVIEWER)
            for r in table[table.status == "AUTO_APPROVED"].itertuples()]


def append_log(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path = Path(path)
    new = pd.DataFrame(rows, columns=LOG_COLUMNS)
    new.to_csv(path, mode="a", header=not path.exists(), index=False)


def read_log(path: Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=LOG_COLUMNS)
    return pd.read_csv(path, keep_default_na=False)


def latest_decisions(log: pd.DataFrame) -> pd.DataFrame:
    """The log is append-only; the last row per SKU is the standing decision."""
    if log.empty:
        return log
    return log.drop_duplicates("sku_id", keep="last").reset_index(drop=True)


def pending_review(table: pd.DataFrame, decisions: pd.DataFrame) -> list[str]:
    decided = set(decisions.sku_id) if not decisions.empty else set()
    return [s for s in table[table.status == "NEEDS_REVIEW"].sku_id if s not in decided]


def can_generate_pos(table: pd.DataFrame, decisions: pd.DataFrame) -> bool:
    return not pending_review(table, decisions)


def override_stats(decisions: pd.DataFrame) -> dict:
    """Override = final qty differs from system qty (a reject of a positive qty counts).
    Denominator = decided lines where either quantity is above zero. Rate is None until there is one."""
    if decisions is None or decisions.empty:
        return {"decided_lines": 0, "overrides": 0, "override_rate": None, "human_decisions": 0}
    d = decisions[(decisions.system_qty > 0) | (decisions.final_qty > 0)]
    over = int((d.final_qty != d.system_qty).sum())
    human = int((~decisions.reviewer.astype(str).str.startswith(SYSTEM_PREFIX)).sum())
    return {"decided_lines": int(len(d)), "overrides": over,
            "override_rate": round(over / len(d), 4) if len(d) else None, "human_decisions": human}
