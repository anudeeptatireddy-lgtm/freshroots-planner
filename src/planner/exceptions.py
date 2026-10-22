"""Stage 6: decide which lines go to a human (NEEDS_REVIEW) and which are AUTO_APPROVED."""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from planner.common import window_weeks

CODES = ["NEW_LAUNCH", "DATA_ISSUE", "BELOW_MIN_AFTER_ORDER", "ABOVE_MAX_AFTER_ORDER", "BORDERLINE",
         "SHARP_DROP", "DISTRIBUTOR_ANOMALY", "HIGH_VALUE"]
NAN = float("nan")


def distributor_anomalies(dsales: pd.DataFrame | None, cfg: dict, run_date: dt.date) -> dict[str, str]:
    """HOOK. Inactive (returns {}) unless distributor-level sales were supplied.
    Flags a SKU when any distributor's 4w average moved more than the configured amount vs its 12w average.
    The threshold is a placeholder in config; confirm with Raghav before relying on it."""
    if dsales is None or dsales.empty:
        return {}
    n, r = cfg["history"]["window_weeks"], cfg["history"]["recent_weeks"]
    win = window_weeks(run_date, n)
    recent = set(win[-r:])
    limit = cfg["exceptions"]["distributor_anomaly_change"]
    out: dict[str, str] = {}
    for (sku, dist), g in dsales.groupby(["sku_id", "distributor_id"]):
        a12, a4 = g.units.mean(), g[g.week_start.isin(recent)].units.mean()
        if a12 and not math.isnan(a4) and abs(a4 / a12 - 1) > limit:
            msg = f"Distributor {dist} moved {a4 / a12 - 1:+.0%} (4-week vs 12-week average), beyond the +/-{limit:.0%} limit."
            out[sku] = (out[sku] + " " + msg) if sku in out else msg
    return out


def classify(table: pd.DataFrame, issues: list[dict], cfg: dict, run_date: dt.date,
             dsales: pd.DataFrame | None = None) -> pd.DataFrame:
    ec = cfg["exceptions"]
    review_issues: dict[str, list[str]] = {}
    for i in issues:
        if i["severity"] == "review" and i["sku_id"]:
            review_issues.setdefault(i["sku_id"], []).append(f"{i['file']} {i['row_ref']}: {i['issue']}")
    anomalies = distributor_anomalies(dsales, cfg, run_date)
    thr = cfg["rules"]["high_demand_threshold"]
    rounding = cfg["rules"]["order_qty_rounding"]

    res = []
    for r in table.to_dict("records"):
        codes: dict[str, str] = {}
        sug_qty, sug_note = NAN, ""
        planned = r["flag"] != "NOT_PLANNED"
        qty = r["order_qty"]

        if r["is_new_launch"]:
            codes["NEW_LAUNCH"] = (f"Only {r['history_weeks']} week(s) of sales history (need {cfg['history']['window_weeks']}); "
                                   "the rules are not applied automatically to new launches.")
        data_msgs = review_issues.get(r["sku_id"], [])
        if not planned and not data_msgs:
            data_msgs = [r["plan_blockers"]]
        if data_msgs:
            codes["DATA_ISSUE"] = f"{len(data_msgs)} data issue(s): " + "; ".join(data_msgs[:3]) + (" ..." if len(data_msgs) > 3 else "")

        if planned:
            cover, after = r["weeks_of_cover"], r["weeks_of_cover_after_order"]
            mn, mx, adj, pos = r["min_weeks"], r["max_weeks"], r["adjusted_weekly_demand"], r["inventory_position"]
            if "STOCKOUT_RISK" in r["flag"] and after < mn:
                total = math.ceil(mn * adj - pos - 1e-9)
                sug_qty, top_up = float(total), total - qty
                codes["BELOW_MIN_AFTER_ORDER"] = (f"After the recommended order of {qty:g} units stock would cover {after:.2f} weeks; "
                                                  f"the minimum is {mn:g}. Suggested top-up: +{top_up:g} units (order {total:g} in total) to reach {mn:g} weeks.")
                sug_note = f"Top up by {top_up:g} units to reach the {mn:g}-week minimum."
            if qty > 0 and after > mx:
                total = max(0, math.floor(mx * adj - pos + 1e-9))
                sug_qty = float(total)
                extra = " Perishable: over-ordering risks write-off." if r["perishability"] == "High" else ""
                codes["ABOVE_MAX_AFTER_ORDER"] = (f"After the recommended order of {qty:g} units stock would cover {after:.2f} weeks, above the {mx:g}-week maximum.{extra} "
                                                  f"Suggested quantity: {total:g} units.")
                sug_note = f"Reduce to {total:g} units to stay within the {mx:g}-week maximum."
            near = []
            if r["flag"] == "OVERSTOCK":
                if abs(cover - mx) <= ec["borderline_weeks"]:
                    near.append(f"cover {cover:.2f} weeks is within {ec['borderline_weeks']:g} weeks of the {mx:g}-week maximum")
            else:
                if abs(r["change_4w_vs_12w"] - thr) <= ec["borderline_change_pp"]:
                    near.append(f"4-week change {r['change_4w_vs_12w']:+.1%} is within {ec['borderline_change_pp'] * 100:g} points of the {thr:.0%} high-demand threshold")
                if abs(cover - mn) <= ec["borderline_weeks"]:
                    near.append(f"cover {cover:.2f} weeks is within {ec['borderline_weeks']:g} weeks of the {mn:g}-week minimum")
                if abs(cover - mx) <= ec["borderline_weeks"]:
                    near.append(f"cover {cover:.2f} weeks is within {ec['borderline_weeks']:g} weeks of the {mx:g}-week maximum")
            if near:
                codes["BORDERLINE"] = "Close to a rule threshold, so a small data change would flip the decision: " + "; ".join(near) + "."
            if r["change_4w_vs_12w"] < ec["sharp_drop_threshold"]:
                codes["SHARP_DROP"] = (f"Demand fell {r['change_4w_vs_12w']:+.1%} (4-week vs 12-week average), beyond {ec['sharp_drop_threshold']:.0%}; "
                                       "the rules do not cover falling demand.")
        if r["sku_id"] in anomalies:
            codes["DISTRIBUTOR_ANOMALY"] = anomalies[r["sku_id"]]
        hv = ec.get("high_value_threshold")
        if hv is not None and planned and qty > 0 and not math.isnan(r["unit_price"]) and qty * r["unit_price"] > hv:
            codes["HIGH_VALUE"] = f"Order value INR {qty * r['unit_price']:,.0f} exceeds the INR {hv:,.0f} review threshold."

        ordered = [c for c in CODES if c in codes]
        if ordered:
            status = "NEEDS_REVIEW"
        elif qty > 0:
            status = "AUTO_APPROVED"
        else:
            status = "NO_ORDER"
        res.append({"exceptions": "; ".join(ordered), "exception_reasons": " | ".join(f"{c}: {codes[c]}" for c in ordered),
                    "suggested_qty": sug_qty, "suggested_note": sug_note, "status": status,
                    "data_issues": " | ".join(data_msgs)})
    return pd.concat([table, pd.DataFrame(res, index=table.index)], axis=1)
