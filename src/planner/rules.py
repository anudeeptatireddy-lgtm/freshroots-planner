"""Stage 4: Raghav's rules, implemented literally. Thresholds come from config only."""
from __future__ import annotations

import math

import pandas as pd

NAN = float("nan")


def round_qty(x: float, mode: str) -> float:
    if mode == "ceil":
        return float(math.ceil(x - 1e-9))
    if mode == "round":
        return float(math.floor(x + 0.5))
    return float(x)


def _rule_row(r, rc: dict) -> dict:
    blockers = r["plan_blockers"]
    if blockers:
        return {"flag": "NOT_PLANNED", "flag_reasons": f"Rules could not be applied: {blockers}.",
                "action": "Needs a person", "order_qty": 0.0, "is_urgent": False,
                "weeks_of_cover_after_order": NAN}
    cover, mx, mn = r["weeks_of_cover"], r["max_weeks"], r["min_weeks"]
    demand_txt = "festival-adjusted demand" if r["is_festival"] else "average weekly demand"

    # 1. Overstock: stop here for this SKU.
    if cover > mx:
        return {"flag": "OVERSTOCK",
                "flag_reasons": f"Stock covers {cover:.2f} weeks of {demand_txt}; maximum is {mx:g} weeks.",
                "action": "Pause next order", "order_qty": 0.0, "is_urgent": False,
                "weeks_of_cover_after_order": cover}
    flags, reasons = [], []
    high = r["change_4w_vs_12w"] > rc["high_demand_threshold"]
    if high:
        flags.append("HIGH_DEMAND")
        reasons.append(f"Last 4 weeks averaged {r['avg_weekly_4w']:.1f}/week, {r['change_4w_vs_12w']:+.1%} vs the "
                       f"12-week average of {r['avg_weekly_12w']:.1f}; high-demand threshold is +{rc['high_demand_threshold']:.0%}.")
    stockout = cover < mn
    if stockout:
        flags.append("STOCKOUT_RISK")
        reasons.append(f"Stock covers {cover:.2f} weeks of {demand_txt}; minimum is {mn:g} weeks.")
    std = r["standard_reorder_qty"]
    if high:
        qty, action = std * rc["high_demand_multiplier"], f"Reorder {rc['high_demand_multiplier']:g}x standard quantity" + (" (urgent)" if stockout else "")
    elif stockout:
        qty, action = std * rc["stockout_multiplier"], "Immediate reorder (urgent)"
    else:
        qty, action = 0.0, "No order this run"
        flags.append("HEALTHY")
        reasons.append(f"Stock covers {cover:.2f} weeks of {demand_txt}, inside the {mn:g}-{mx:g} week range, and demand is not above threshold.")
    qty = round_qty(qty, rc["order_qty_rounding"]) if qty else 0.0
    after = (r["inventory_position"] + qty) / r["adjusted_weekly_demand"]
    return {"flag": " + ".join(flags), "flag_reasons": " ".join(reasons), "action": action,
            "order_qty": qty, "is_urgent": stockout, "weeks_of_cover_after_order": after}


def apply_rules(table: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    rc = cfg["rules"]
    out = pd.DataFrame([_rule_row(r, rc) for r in table.to_dict("records")], index=table.index)
    return pd.concat([table, out], axis=1)
