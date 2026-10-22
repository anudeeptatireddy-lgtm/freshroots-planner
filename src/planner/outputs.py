"""Writes the per-run output folder and finalises it (POs, handoff, run log) after review."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from planner import handoff, po, review
from planner.common import PlannerError
from planner.pipeline import PipelineResult

TEXT_FILL_SKIP = {"is_festival", "is_urgent", "is_new_launch"}


def new_run_dir(base: str | Path, run_date: dt.date) -> Path:
    """outputs/<run_date>/ - never overwritten: a re-run gets _r2, _r3, ..."""
    base = Path(base)
    d = base / run_date.isoformat()
    n = 2
    while d.exists():
        d = base / f"{run_date.isoformat()}_r{n}"
        n += 1
    d.mkdir(parents=True)
    return d


def load_planning_table(run_dir: str | Path) -> pd.DataFrame:
    path = Path(run_dir) / "planning_table.csv"
    if not path.exists():
        raise PlannerError(f"{path} not found; run `python -m planner run` first")
    df = pd.read_csv(path)
    for c in df.columns:
        if c not in TEXT_FILL_SKIP and (df[c].dtype == object or pd.api.types.is_string_dtype(df[c])):
            df[c] = df[c].fillna("")
    return df


def _counts(series: pd.Series, split: str | None = None) -> dict:
    items = []
    for v in series:
        if v:
            items += str(v).split(split) if split else [v]
    return dict(sorted(pd.Series(items, dtype=object).value_counts().to_dict().items())) if items else {}


def write_run(result: PipelineResult, cfg: dict, out_base: str | Path) -> Path:
    run_dir = new_run_dir(out_base, result.run_date)
    t = result.table
    t.to_csv(run_dir / "planning_table.csv", index=False, float_format="%.6g")
    result.issues.to_csv(run_dir / "data_quality_report.csv", index=False)
    exc_cols = ["sku_id", "sku_name", "distributor_id", "flag", "order_qty", "weeks_of_cover", "weeks_of_cover_after_order",
                "exceptions", "exception_reasons", "suggested_qty", "suggested_note"]
    t[t.status == "NEEDS_REVIEW"][exc_cols].to_csv(run_dir / "exceptions.csv", index=False, float_format="%.6g")
    log = {
        "run_date": result.run_date.isoformat(),
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "file_hashes_sha256": result.hashes,
        "row_counts": result.row_counts,
        "skus_processed": int(len(t)),
        "data_issues": {"total": int(len(result.issues)), "needing_review": int((result.issues.severity == "review").sum()),
                        "info_only": int((result.issues.severity == "info").sum())},
        "run_notes": result.notes,
        "flag_counts": _counts(t.flag, " + "),
        "exception_counts": _counts(t.exceptions, "; "),
        "status_counts": _counts(t.status),
        "override_count": None, "override_rate": None, "lines_decided": 0,
        "po_generated": False,
        "config_snapshot": {k: cfg[k] for k in ("festival", "rules", "exceptions", "history")},
    }
    (run_dir / "run_log.json").write_text(json.dumps(log, indent=2, default=str))
    return run_dir


def finalize_run(run_dir: str | Path, cfg: dict, summary_override: str | None = None) -> dict:
    """Generate POs, Zoho CSV, PO PDFs and the sourcing handoff from the review log. Refuses while any line is undecided."""
    run_dir = Path(run_dir)
    table = load_planning_table(run_dir)
    run_log = json.loads((run_dir / "run_log.json").read_text())
    run_date = dt.date.fromisoformat(run_log["run_date"])
    decisions = review.latest_decisions(review.read_log(run_dir / "review_log.csv"))
    pending = review.pending_review(table, decisions)
    held_ok = run_log.get("auto_mode", False)
    if pending and not held_ok:
        raise PlannerError(f"Cannot generate POs: {len(pending)} line(s) still need a decision: {', '.join(pending)}")
    lines = po.build_po_lines(table, decisions, cfg, run_date)
    paths = po.write_pos(lines, cfg, run_dir)
    held = handoff.held_lines(table, decisions)
    stats = review.override_stats(decisions)
    summary = summary_override or handoff.template_run_summary(run_date, table, lines, held, stats)
    if summary_override is None:    # optional AI layer: may reword the summary text only; tables below stay template-built
        log_csv = (run_dir / "review_log.csv").read_text() if (run_dir / "review_log.csv").exists() else ""
        summary = handoff.ai_summary(cfg, (run_dir / "planning_table.csv").read_text(), log_csv) or summary
    (run_dir / "sourcing_handoff.md").write_text(handoff.build_handoff_md(run_date, lines, held, summary, cfg))
    run_log.update({"override_count": stats["overrides"], "override_rate": stats["override_rate"],
                    "lines_decided": stats["decided_lines"], "human_decisions": stats["human_decisions"],
                    "po_generated": True, "po_count": int(lines.po_number.nunique()) if not lines.empty else 0,
                    "po_line_count": int(len(lines)), "lines_held_back": int(len(held)),
                    "finalised_at": dt.datetime.now().isoformat(timespec="seconds")})
    (run_dir / "run_log.json").write_text(json.dumps(run_log, indent=2, default=str))
    return {"lines": lines, "pdfs": paths, "held": held, "stats": stats, "summary": summary}
