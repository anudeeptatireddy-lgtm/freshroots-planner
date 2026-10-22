"""Stage 3: one row per SKU with the averages, uplift, inventory position and cover."""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from planner.common import window_weeks

NAN = float("nan")


def organise(cleaned: dict, cfg: dict, run_date: dt.date) -> pd.DataFrame:
    n, r = cfg["history"]["window_weeks"], cfg["history"]["recent_weeks"]
    win = window_weeks(run_date, n)
    win_set, recent_set = set(win), set(win[-r:])
    sales = cleaned["sales"]
    valid = sales[sales.units.notna()]
    in_win = valid[valid.week_start.isin(win_set)]
    a12 = in_win.groupby("sku_id").units.mean()
    a4 = in_win[in_win.week_start.isin(recent_set)].groupby("sku_id").units.mean()
    first_week = valid.groupby("sku_id").week_start.min()

    master = cleaned["master"].set_index("sku_id")
    inv = cleaned["inventory"].set_index("sku_id")
    dist = cleaned["distributors"]
    open_pos = cleaned["open_pos"] or {}
    prices = cleaned["prices"] or {}

    ym = run_date.strftime("%Y-%m")
    is_fest = bool(cleaned["calendar"][ym])
    uplift = cfg["festival"]["uplift"] if is_fest else cfg["festival"]["non_festival_uplift"]
    last_complete = win[-1]

    skus = sorted(set(master.index) | set(sales.sku_id) | set(inv.index))
    rows = []
    for sku in skus:
        m = master.loc[sku] if sku in master.index else None
        perish = m["perishability"] if m is not None else None
        win_cfg = cfg["rules"]["windows"].get(perish) if isinstance(perish, str) else None
        on_hand = float(inv.loc[sku, "units_on_hand"]) if sku in inv.index else NAN
        open_po = float(open_pos.get(sku, 0.0))
        position = on_hand + open_po
        avg12 = float(a12.get(sku, NAN))
        avg4 = float(a4.get(sku, NAN))
        change = avg4 / avg12 - 1 if avg12 and not math.isnan(avg12) and not math.isnan(avg4) else NAN
        adj = avg12 * uplift if not math.isnan(avg12) else NAN
        cover = position / adj if adj and not math.isnan(adj) and not math.isnan(position) else NAN
        fw = first_week.get(sku)
        hist_weeks = ((last_complete - fw).days // 7 + 1) if fw is not None and fw <= last_complete else 0
        d = dist.get(m["distributor_id"]) if m is not None else None
        missing = []
        if m is None: missing.append("not in sku_master")
        else:
            if win_cfg is None: missing.append("invalid Perishability")
            if math.isnan(m["std_qty"]): missing.append("invalid Standard_Reorder_Qty")
        if math.isnan(on_hand): missing.append("no valid inventory")
        if math.isnan(avg12): missing.append("no valid sales in 12-week window")
        elif adj <= 0: missing.append("zero demand in window")
        rows.append({
            "sku_id": sku,
            "sku_name": m["sku_name"] if m is not None else "",
            "category": m["category"] if m is not None else "",
            "perishability": perish if isinstance(perish, str) else "",
            "distributor_id": m["distributor_id"] if m is not None else "",
            "distributor_name": d["name"] if d else "",
            "distributor_region": d["region"] if d else "",
            "standard_reorder_qty": m["std_qty"] if m is not None else NAN,
            "unit": m["uom"] if m is not None else "Units",
            "unit_price": float(prices[sku]) if sku in prices else NAN,
            "units_on_hand": on_hand,
            "open_po_qty": open_po,
            "inventory_position": position,
            "history_weeks": hist_weeks,
            "is_new_launch": hist_weeks < n,
            "avg_weekly_12w": avg12,
            "avg_weekly_4w": avg4,
            "change_4w_vs_12w": change,
            "is_festival": is_fest,
            "uplift": uplift,
            "adjusted_weekly_demand": adj,
            "weeks_of_cover": cover,
            "min_weeks": win_cfg["min_weeks"] if win_cfg else NAN,
            "max_weeks": win_cfg["max_weeks"] if win_cfg else NAN,
            "plan_blockers": "; ".join(missing),
        })
    return pd.DataFrame(rows)
