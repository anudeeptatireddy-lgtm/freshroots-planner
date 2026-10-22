"""Stage 3: one row per SKU with the averages, uplift, inventory position and cover."""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from planner.common import window_weeks

NAN = float("nan")


def _plan_blockers(m, win_cfg, on_hand: float, avg12: float, adj: float) -> str:
    """Why the rules cannot run for this SKU (empty string when they can)."""
    problems = []
    if m is None:
        problems.append("not in sku_master")
    else:
        if win_cfg is None:
            problems.append("invalid Perishability")
        if math.isnan(m["std_qty"]):
            problems.append("invalid Standard_Reorder_Qty")
    if math.isnan(on_hand):
        problems.append("no valid inventory")
    if math.isnan(avg12):
        problems.append("no valid sales in 12-week window")
    elif adj <= 0:
        problems.append("zero demand in window")
    return "; ".join(problems)


def _ratio(num: float, den: float) -> float:
    """num/den, or NaN when either is missing or the denominator is zero."""
    if math.isnan(num) or math.isnan(den) or not den:
        return NAN
    return num / den


def organise(cleaned: dict, cfg: dict, run_date: dt.date) -> pd.DataFrame:
    n, r = cfg["history"]["window_weeks"], cfg["history"]["recent_weeks"]
    win = window_weeks(run_date, n)
    recent_set = set(win[-r:])
    last_complete = win[-1]

    sales = cleaned["sales"]
    valid = sales[sales.units.notna()]
    in_win = valid[valid.week_start.isin(set(win))]
    a12 = in_win.groupby("sku_id").units.mean()
    a4 = in_win[in_win.week_start.isin(recent_set)].groupby("sku_id").units.mean()
    first_week = valid.groupby("sku_id").week_start.min()

    master = cleaned["master"].set_index("sku_id")
    inv = cleaned["inventory"].set_index("sku_id")
    open_pos = cleaned["open_pos"] or {}
    prices = cleaned["prices"] or {}

    is_fest = bool(cleaned["calendar"][run_date.strftime("%Y-%m")])
    uplift = cfg["festival"]["uplift"] if is_fest else cfg["festival"]["non_festival_uplift"]

    rows = []
    for sku in sorted(set(master.index) | set(sales.sku_id) | set(inv.index)):
        m = master.loc[sku] if sku in master.index else None
        perish = m["perishability"] if m is not None else None
        win_cfg = cfg["rules"]["windows"].get(perish) if isinstance(perish, str) else None
        dist = cleaned["distributors"].get(m["distributor_id"]) if m is not None else None
        on_hand = float(inv.loc[sku, "units_on_hand"]) if sku in inv.index else NAN
        position = on_hand + float(open_pos.get(sku, 0.0))
        avg12, avg4 = float(a12.get(sku, NAN)), float(a4.get(sku, NAN))
        adj = avg12 * uplift
        fw = first_week.get(sku)
        hist_weeks = (last_complete - fw).days // 7 + 1 if fw is not None and fw <= last_complete else 0
        rows.append({
            "sku_id": sku,
            "sku_name": m["sku_name"] if m is not None else "",
            "category": m["category"] if m is not None else "",
            "perishability": perish if isinstance(perish, str) else "",
            "distributor_id": m["distributor_id"] if m is not None else "",
            "distributor_name": dist["name"] if dist else "",
            "distributor_region": dist["region"] if dist else "",
            "standard_reorder_qty": m["std_qty"] if m is not None else NAN,
            "unit": m["uom"] if m is not None else "Units",
            "unit_price": float(prices[sku]) if sku in prices else NAN,
            "units_on_hand": on_hand,
            "open_po_qty": float(open_pos.get(sku, 0.0)),
            "inventory_position": position,
            "history_weeks": hist_weeks,
            "is_new_launch": hist_weeks < n,
            "avg_weekly_12w": avg12,
            "avg_weekly_4w": avg4,
            "change_4w_vs_12w": _ratio(avg4, avg12) - 1,
            "is_festival": is_fest,
            "uplift": uplift,
            "adjusted_weekly_demand": adj,
            "weeks_of_cover": _ratio(position, adj),
            "min_weeks": win_cfg["min_weeks"] if win_cfg else NAN,
            "max_weeks": win_cfg["max_weeks"] if win_cfg else NAN,
            "plan_blockers": _plan_blockers(m, win_cfg, on_hand, avg12, adj),
        })
    return pd.DataFrame(rows)
