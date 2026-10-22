"""Stage 6: decide which lines go to a human (NEEDS_REVIEW) and which are AUTO_APPROVED."""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from planner.common import STATUS_AUTO, STATUS_NO_ORDER, STATUS_REVIEW, window_weeks

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
    recent = set(window_weeks(run_date, n)[-r:])
    limit = cfg["exceptions"]["distributor_anomaly_change"]
    out: dict[str, str] = {}
    for (sku, dist), g in dsales.groupby(["sku_id", "distributor_id"]):
        a12, a4 = g.units.mean(), g[g.week_start.isin(recent)].units.mean()
        if a12 and not math.isnan(a4) and abs(a4 / a12 - 1) > limit:
            msg = f"Distributor {dist} moved {a4 / a12 - 1:+.0%} (4-week vs 12-week average), beyond the +/-{limit:.0%} limit."
            out[sku] = f"{out[sku]} {msg}" if sku in out else msg
    return out


def _review_issues_by_sku(issues: list[dict]) -> dict[str, list[str]]:
    by_sku: dict[str, list[str]] = {}
    for i in issues:
        if i["severity"] == "review" and i["sku_id"]:
            by_sku.setdefault(i["sku_id"], []).append(f"{i['file']} {i['row_ref']}: {i['issue']}")
    return by_sku


# Each check returns a reason string (or None). The two order-quantity checks also return a suggestion.
def _new_launch(r: dict, cfg: dict) -> str | None:
    if not r["is_new_launch"]:
        return None
    return (f"Only {r['history_weeks']} week(s) of sales history (need {cfg['history']['window_weeks']}); "
            "the rules are not applied automatically to new launches.")


def _data_issue(r: dict, messages: list[str]) -> str | None:
    if not messages:
        return None
    return f"{len(messages)} data issue(s): " + "; ".join(messages[:3]) + (" ..." if len(messages) > 3 else "")


def _below_min(r: dict) -> tuple[str, float, str] | None:
    after, mn, qty = r["weeks_of_cover_after_order"], r["min_weeks"], r["order_qty"]
    if "STOCKOUT_RISK" not in r["flag"] or after >= mn:
        return None
    total = math.ceil(mn * r["adjusted_weekly_demand"] - r["inventory_position"] - 1e-9)
    top_up = total - qty
    reason = (f"After the recommended order of {qty:g} units stock would cover {after:.2f} weeks; "
              f"the minimum is {mn:g}. Suggested top-up: +{top_up:g} units (order {total:g} in total) to reach {mn:g} weeks.")
    return reason, float(total), f"Top up by {top_up:g} units to reach the {mn:g}-week minimum."


def _above_max(r: dict) -> tuple[str, float, str] | None:
    after, mx, qty = r["weeks_of_cover_after_order"], r["max_weeks"], r["order_qty"]
    if qty <= 0 or after <= mx:     # OVERSTOCK lines have qty 0 and would otherwise always trigger
        return None
    total = max(0, math.floor(mx * r["adjusted_weekly_demand"] - r["inventory_position"] + 1e-9))
    extra = " Perishable: over-ordering risks write-off." if r["perishability"] == "High" else ""
    reason = (f"After the recommended order of {qty:g} units stock would cover {after:.2f} weeks, above the {mx:g}-week maximum.{extra} "
              f"Suggested quantity: {total:g} units.")
    return reason, float(total), f"Reduce to {total:g} units to stay within the {mx:g}-week maximum."


def _borderline(r: dict, ec: dict, high_demand_threshold: float) -> str | None:
    cover, mn, mx, margin = r["weeks_of_cover"], r["min_weeks"], r["max_weeks"], ec["borderline_weeks"]
    near = []
    if r["flag"] != "OVERSTOCK":    # demand and minimum thresholds only matter on the order branch
        if abs(r["change_4w_vs_12w"] - high_demand_threshold) <= ec["borderline_change_pp"]:
            near.append(f"4-week change {r['change_4w_vs_12w']:+.1%} is within {ec['borderline_change_pp'] * 100:g} points "
                        f"of the {high_demand_threshold:.0%} high-demand threshold")
        if abs(cover - mn) <= margin:
            near.append(f"cover {cover:.2f} weeks is within {margin:g} weeks of the {mn:g}-week minimum")
    if abs(cover - mx) <= margin:
        near.append(f"cover {cover:.2f} weeks is within {margin:g} weeks of the {mx:g}-week maximum")
    if not near:
        return None
    return "Close to a rule threshold, so a small data change would flip the decision: " + "; ".join(near) + "."


def _sharp_drop(r: dict, ec: dict) -> str | None:
    if r["change_4w_vs_12w"] >= ec["sharp_drop_threshold"]:
        return None
    return (f"Demand fell {r['change_4w_vs_12w']:+.1%} (4-week vs 12-week average), beyond {ec['sharp_drop_threshold']:.0%}; "
            "the rules do not cover falling demand.")


def _high_value(r: dict, ec: dict) -> str | None:
    limit, qty, price = ec.get("high_value_threshold"), r["order_qty"], r["unit_price"]
    if limit is None or qty <= 0 or math.isnan(price) or qty * price <= limit:
        return None
    return f"Order value INR {qty * price:,.0f} exceeds the INR {limit:,.0f} review threshold."


def _classify_row(r: dict, cfg: dict, data_msgs: list[str], anomaly: str | None) -> dict:
    ec, planned = cfg["exceptions"], r["flag"] != "NOT_PLANNED"
    thr = cfg["rules"]["high_demand_threshold"]
    codes: dict[str, str] = {}
    sug_qty, sug_note = NAN, ""

    codes["NEW_LAUNCH"] = _new_launch(r, cfg)
    codes["DATA_ISSUE"] = _data_issue(r, data_msgs or ([r["plan_blockers"]] if not planned else []))
    if planned:
        for code, check in (("BELOW_MIN_AFTER_ORDER", _below_min(r)), ("ABOVE_MAX_AFTER_ORDER", _above_max(r))):
            if check:
                codes[code], sug_qty, sug_note = check
        codes["BORDERLINE"] = _borderline(r, ec, thr)
        codes["SHARP_DROP"] = _sharp_drop(r, ec)
        codes["HIGH_VALUE"] = _high_value(r, ec)
    codes["DISTRIBUTOR_ANOMALY"] = anomaly

    found = [c for c in CODES if codes.get(c)]
    if found:
        status = STATUS_REVIEW
    elif r["order_qty"] > 0:
        status = STATUS_AUTO
    else:
        status = STATUS_NO_ORDER
    return {"exceptions": "; ".join(found), "exception_reasons": " | ".join(f"{c}: {codes[c]}" for c in found),
            "suggested_qty": sug_qty, "suggested_note": sug_note, "status": status,
            "data_issues": " | ".join(data_msgs or ([r["plan_blockers"]] if not planned else []))}


def classify(table: pd.DataFrame, issues: list[dict], cfg: dict, run_date: dt.date,
             dsales: pd.DataFrame | None = None) -> pd.DataFrame:
    by_sku = _review_issues_by_sku(issues)
    anomalies = distributor_anomalies(dsales, cfg, run_date)
    rows = [_classify_row(r, cfg, by_sku.get(r["sku_id"], []), anomalies.get(r["sku_id"])) for r in table.to_dict("records")]
    return pd.concat([table, pd.DataFrame(rows, index=table.index)], axis=1)
