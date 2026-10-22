"""Stage 8b: sourcing handoff note and run summary. Template-based; the optional AI layer may reword it."""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd

from planner.common import STATUS_AUTO, STATUS_REVIEW


def template_run_summary(run_date, table: pd.DataFrame, lines: pd.DataFrame, held: pd.DataFrame, stats: dict) -> str:
    counts = table["flag"].value_counts().to_dict()
    flag_txt = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    no_human = stats["override_rate"] is None or not stats.get("human_decisions")
    rate = "n/a (no human decisions yet)" if no_human else f"{stats['override_rate']:.0%}"
    return "\n".join([
        f"- Run date {run_date}: {len(table)} SKUs processed ({flag_txt}).",
        f"- {int((table.status == STATUS_REVIEW).sum())} lines were sent to review; {int((table.status == STATUS_AUTO).sum())} were auto-approved by the rules.",
        f"- {lines.po_number.nunique() if not lines.empty else 0} purchase order(s) with {len(lines)} line(s) were generated from approved lines.",
        f"- {len(held)} line(s) with a recommended order are held back pending review.",
        f"- Override rate so far: {rate}.",
    ])


def held_lines(table: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """Lines excluded from POs: NEEDS_REVIEW with no decision, or rejected."""
    decided = {} if decisions is None or decisions.empty else decisions.set_index("sku_id").decision.to_dict()
    mask = (table.status == STATUS_REVIEW) & (~table.sku_id.isin(decided)) | table.sku_id.map(decided).eq("reject")
    h = table[mask].copy()
    h["held_reason"] = ["Rejected by reviewer" if decided.get(s) == "reject" else "Pending review" for s in h.sku_id]
    return h


def build_handoff_md(run_date: dt.date, lines: pd.DataFrame, held: pd.DataFrame, summary: str, cfg: dict) -> str:
    out = [f"# Sourcing handoff - {run_date}", "", "## Run summary", summary, ""]
    if lines.empty:
        out += ["## Purchase orders", "No purchase orders were generated for this run.", ""]
    else:
        out += ["## Purchase orders", f"Counterparty: {cfg['po']['counterparty_label']} - confirm the actual supplier before release.", ""]
        urgent_first = sorted(lines.po_number.unique(), key=lambda p: (not lines[lines.po_number == p].is_urgent.any(), p))
        for po in urgent_first:
            g = lines[lines.po_number == po]
            f = g.iloc[0]
            out += [f"### {po} - {f.vendor_name} ({f.vendor_id})" + ("  **URGENT**" if g.is_urgent.any() else ""), "",
                    "| SKU | Item | Qty | Unit | Notes |", "|---|---|---:|---|---|"]
            for r in g.sort_values("is_urgent", ascending=False).itertuples():
                out.append(f"| {r.sku_id} | {r.item_name} | {r.quantity:,} | {r.unit} | {r.notes} |")
            priced = g.unit_price.notna().all()
            out += ["", f"Order value: {(g.unit_price * g.quantity).sum():,.2f}" if priced else "Order value: not calculated (no unit prices provided).", ""]
    out += ["## Excluded pending review"]
    if held.empty:
        out += ["Nothing is held back.", ""]
    else:
        out += ["These SKUs are NOT on any PO yet.", "", "| SKU | Item | System qty | Why held |", "|---|---|---:|---|"]
        for r in held.itertuples():
            out.append(f"| {r.sku_id} | {r.sku_name} | {r.order_qty:g} | {r.held_reason}: {r.exceptions or r.flag} |")
        out.append("")
    out += ["---", "Unit prices and lead times are not in the source data; PO prices are blank unless sku_prices.csv was supplied."]
    return "\n".join(out)


def ai_summary(cfg: dict, planning_csv: str, review_csv: str) -> str | None:
    """OPTIONAL. Off by default. Summarises only; returns None to fall back to the template."""
    ac = cfg.get("ai_summary", {})
    if not ac.get("enabled") or not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        msg = anthropic.Anthropic().messages.create(
            model=ac["model"], max_tokens=ac.get("max_tokens", 900),
            messages=[{"role": "user", "content": f"{ac['prompt']}\n\nplanning_table.csv:\n{planning_csv}\n\nreview_log.csv:\n{review_csv}"}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip() or None
    except Exception:
        return None
