"""Stage 2: validate and clean. Every issue gets a row: file, row, issue, action taken."""
from __future__ import annotations

import datetime as dt
import math

import pandas as pd

from planner.common import (
    PlannerError,
    forecast_week_starts,
    iso_week_label,
    make_issue,
    parse_date,
    parse_iso_week,
    window_weeks,
)

NAN = float("nan")


def _norm_ids(df: pd.DataFrame, col: str, file: str, issues: list, sku_col: bool = True) -> pd.Series:
    """Trim + uppercase an ID column, logging each value that had to change."""
    out = []
    for raw, row in zip(df[col].astype(str), df["_row"]):
        new = raw.strip().upper()
        if new != raw and new:
            issues.append(make_issue(file, f"row {row}", f"{col} '{raw}' had whitespace/lowercase",
                                     f"Normalised to '{new}'", sku_id=new if sku_col else "",
                                     severity="info"))
        out.append(new)
    return pd.Series(out, index=df.index)


def _to_float(text) -> float:
    s = str(text).strip().replace(",", "")
    if s == "":
        return NAN
    try:
        return float(s)
    except ValueError:
        return NAN


# --------------------------------------------------------------------------- calendar
def _clean_calendar(df: pd.DataFrame) -> dict[str, bool]:
    cal: dict[str, bool] = {}
    for r in df.to_dict("records"):
        ym = str(r["Year_Month"]).strip()
        flag = str(r["Is_Festival_Month"]).strip().upper()
        if flag not in ("TRUE", "FALSE"):
            raise PlannerError(f"calendar.csv row {r['_row']}: Is_Festival_Month must be TRUE/FALSE, got '{r['Is_Festival_Month']}'")
        cal[ym] = flag == "TRUE"
    return cal


def _check_calendar(cal: dict, run_date: dt.date, cfg: dict) -> None:
    months = {run_date.strftime("%Y-%m")}
    months |= {d.strftime("%Y-%m") for d in forecast_week_starts(run_date, cfg["history"]["forecast_weeks"])}
    missing = sorted(m for m in months if m not in cal)
    if missing:
        raise PlannerError(f"calendar.csv has no row for month(s) {missing} needed by this run; add them and re-run")


# --------------------------------------------------------------------------- master data
def _clean_distributors(df, cfg, issues):
    f = "distributor_master.csv"
    df = df.copy()
    df["Distributor_ID"] = _norm_ids(df, "Distributor_ID", f, issues, sku_col=False)
    df = df[df["Distributor_ID"] != ""]
    dup = df.duplicated("Distributor_ID", keep="first")
    for r in df[dup].to_dict("records"):
        issues.append(make_issue(f, f"row {r['_row']}", f"Duplicate Distributor_ID {r['Distributor_ID']}", "Kept first row", severity="info"))
    df = df[~dup]
    home = {h.strip().lower() for h in cfg["cleaning"].get("home_regions", [])}
    out = {}
    for r in df.to_dict("records"):
        status = str(r["Status"]).strip()
        out[r["Distributor_ID"]] = {"name": str(r["Distributor_Name"]).strip(),
                                    "region": str(r["Region"]).strip(), "status": status}
        if home and out[r["Distributor_ID"]]["region"].lower() not in home:
            issues.append(make_issue(f, f"row {r['_row']}", f"{r['Distributor_ID']} region '{out[r['Distributor_ID']]['region']}' is outside {cfg['cleaning']['home_regions']}",
                                     "Noted only; no action", severity="info"))
    return out


def _clean_master(df, dist, issues):
    f = "sku_master.csv"
    df = df.copy()
    df["SKU_ID"] = _norm_ids(df, "SKU_ID", f, issues)
    for r in df[df["SKU_ID"] == ""].to_dict("records"):
        issues.append(make_issue(f, f"row {r['_row']}", "Blank SKU_ID", "Row excluded"))
    df = df[df["SKU_ID"] != ""]
    dup = df.duplicated("SKU_ID", keep="first")
    for r in df[dup].to_dict("records"):
        issues.append(make_issue(f, f"row {r['_row']}", f"Duplicate SKU_ID {r['SKU_ID']} in master", "Kept first row; SKU routed to review", sku_id=r["SKU_ID"]))
    df = df[~dup]
    rows = []
    for r in df.to_dict("records"):
        sku, row = r["SKU_ID"], f"row {r['_row']}"
        perish_raw = str(r["Perishability"]).strip()
        perish = perish_raw.title()
        if perish not in ("High", "Low"):
            issues.append(make_issue(f, row, f"Perishability '{perish_raw}' is not High/Low", "Rules not applied; SKU routed to review", sku_id=sku))
            perish = None
        elif perish != perish_raw:
            issues.append(make_issue(f, row, f"Perishability '{perish_raw}' inconsistent case", f"Normalised to '{perish}'", sku_id=sku, severity="info"))
        qty = _to_float(r["Standard_Reorder_Qty"])
        if math.isnan(qty) or qty <= 0:
            issues.append(make_issue(f, row, f"Standard_Reorder_Qty '{r['Standard_Reorder_Qty']}' is not a positive number", "Rules not applied; SKU routed to review", sku_id=sku))
            qty = NAN
        did = str(r["Distributor_ID"]).strip().upper()
        if did != str(r["Distributor_ID"]):
            issues.append(make_issue(f, row, f"Distributor_ID '{r['Distributor_ID']}' had whitespace/lowercase", f"Normalised to '{did}'", sku_id=sku, severity="info"))
        if did not in dist:
            issues.append(make_issue(f, row, f"Distributor_ID '{did}' not in distributor master", "PO counterparty unknown; SKU routed to review", sku_id=sku))
        elif dist[did]["status"].lower() != "active":
            issues.append(make_issue(f, row, f"Distributor {did} status is '{dist[did]['status']}', not Active", "SKU routed to review", sku_id=sku))
        rows.append({"sku_id": sku, "sku_name": str(r["SKU_Name"]).strip(), "category": str(r["Category"]).strip(),
                     "perishability": perish, "std_qty": qty, "uom": str(r["Unit_of_Measure"]).strip() or "Units",
                     "distributor_id": did})
    return pd.DataFrame(rows, columns=["sku_id", "sku_name", "category", "perishability", "std_qty", "uom", "distributor_id"])


# --------------------------------------------------------------------------- inventory
def _clean_inventory(df, run_date, issues):
    f = "current_inventory.csv"
    df = df.copy()
    df["SKU_ID"] = _norm_ids(df, "SKU_ID", f, issues)
    rows = []
    for r in df.to_dict("records"):
        sku, row = r["SKU_ID"], f"row {r['_row']}"
        if not sku:
            issues.append(make_issue(f, row, "Blank SKU_ID", "Row excluded"))
            continue
        units = _to_float(r["Units_On_Hand"])
        if math.isnan(units) or units < 0:
            issues.append(make_issue(f, row, f"Units_On_Hand '{r['Units_On_Hand']}' is blank/negative/non-numeric", "Treated as unknown; SKU routed to review", sku_id=sku))
            units = NAN
        asof = parse_date(r["As_Of_Date"])
        if asof is None:
            issues.append(make_issue(f, row, f"As_Of_Date '{r['As_Of_Date']}' unreadable", "Stock date unverified; SKU routed to review", sku_id=sku))
        elif asof != run_date:
            issues.append(make_issue(f, row, f"As_Of_Date {asof} differs from run date {run_date}", "Used as is; SKU routed to review", sku_id=sku))
        rows.append({"sku_id": sku, "units": units, "location": str(r["Location"]).strip()})
    d = pd.DataFrame(rows, columns=["sku_id", "units", "location"])
    out = []
    for sku, g in d.groupby("sku_id", sort=True):
        if len(g) > 1:
            issues.append(make_issue(f, f"{len(g)} rows", f"{sku} appears at {len(g)} locations", "Summed across locations", sku_id=sku, severity="info"))
        out.append({"sku_id": sku, "units_on_hand": NAN if g.units.isna().any() else float(g.units.sum())})
    return pd.DataFrame(out, columns=["sku_id", "units_on_hand"])


# --------------------------------------------------------------------------- sales
def _parse_sales_rows(df, cfg, win, issues) -> pd.DataFrame:
    """Row-level checks: blank IDs, bad weeks, incomplete weeks, blank/negative/zero units."""
    f = "weekly_sales.csv"
    win_set, last = set(win), win[-1]
    zero_action = cfg["cleaning"]["zero_units_action"]
    df = df.copy()
    df["SKU_ID"] = _norm_ids(df, "SKU_ID", f, issues)
    rows = []
    for r in df.to_dict("records"):
        row, sku = f"row {r['_row']}", r["SKU_ID"]
        if not sku:
            issues.append(make_issue(f, row, "Blank SKU_ID", "Row excluded"))
            continue
        wk = parse_iso_week(r["Week"])
        if wk is None:
            issues.append(make_issue(f, row, f"Week '{r['Week']}' is not an ISO week", "Row excluded; SKU routed to review", sku_id=sku))
            continue
        if wk > last:
            issues.append(make_issue(f, row, f"Week {iso_week_label(wk)} is not complete as of the run date", "Excluded from calculations", sku_id=sku, severity="info"))
            continue
        sev = "review" if wk in win_set else "info"      # old weeks only matter for history, not the window
        units = _to_float(r["Units_Sold"])
        if math.isnan(units):
            issues.append(make_issue(f, row, f"Units_Sold '{r['Units_Sold']}' is blank/non-numeric ({iso_week_label(wk)})", "Excluded from averages; treated as missing, not zero", sku_id=sku, severity=sev))
        elif units < 0:
            issues.append(make_issue(f, row, f"Negative Units_Sold {units:g} ({iso_week_label(wk)})", "Excluded from averages; treated as missing", sku_id=sku, severity=sev))
            units = NAN
        elif units == 0 and zero_action == "exclude":
            issues.append(make_issue(f, row, f"Zero Units_Sold ({iso_week_label(wk)})", "Excluded from averages; treated as missing", sku_id=sku, severity=sev))
            units = NAN
        elif units == 0 and zero_action == "flag":
            issues.append(make_issue(f, row, f"Zero Units_Sold ({iso_week_label(wk)}); could be a real zero or a stock-out week", "Kept in averages; SKU routed to review", sku_id=sku, severity=sev))
        rows.append({"sku_id": sku, "week_start": wk, "units": units, "row": r["_row"]})
    return pd.DataFrame(rows, columns=["sku_id", "week_start", "units", "row"])


def _drop_duplicate_weeks(d: pd.DataFrame, cfg: dict, win_set: set, issues) -> pd.DataFrame:
    """One row per SKU + week. Prefers a valid value; logs every dropped copy."""
    f, keep = "weekly_sales.csv", cfg["cleaning"]["duplicate_keep"]
    drop_rows = set()
    for (sku, wk), g in d[d.duplicated(["sku_id", "week_start"], keep=False)].groupby(["sku_id", "week_start"]):
        g = g.sort_values("row")
        pool = g[g.units.notna()] if g.units.notna().any() else g
        chosen = pool.iloc[-1] if keep == "last" else pool.iloc[0]
        differs = g.units.nunique(dropna=False) > 1
        for r in g.to_dict("records"):
            if r["row"] == chosen["row"]:
                continue
            drop_rows.add(r["row"])
            issues.append(make_issue(f, f"row {r['row']}", f"Duplicate {sku} {iso_week_label(wk)} (value {r['units']:g}" + (", differs from other copy)" if differs else ", identical copy)"),
                                     f"Dropped; kept row {chosen['row']} (value {chosen['units']:g})", sku_id=sku,
                                     severity="review" if differs and wk in win_set else "info"))
    return d[~d["row"].isin(drop_rows)].drop(columns="row").reset_index(drop=True)


def _flag_missing_weeks(d: pd.DataFrame, win: list, issues) -> None:
    """Weeks absent after a SKU's first sale are missing (not zero); earlier weeks are just pre-launch."""
    for sku, g in d.groupby("sku_id"):
        valid = set(g[g.units.notna()].week_start)
        if not valid:
            continue
        missing = [w for w in win if w >= min(valid) and w not in valid]
        if missing:
            issues.append(make_issue("weekly_sales.csv", "n/a", f"Missing week(s) inside the window: {', '.join(iso_week_label(w) for w in missing)}",
                                     "Treated as missing, not zero; SKU routed to review", sku_id=sku))


def _clean_sales(df, cfg, win, issues):
    d = _parse_sales_rows(df, cfg, win, issues)
    d = _drop_duplicate_weeks(d, cfg, set(win), issues)
    _flag_missing_weeks(d, win, issues)
    return d


# --------------------------------------------------------------------------- optional files
def _clean_optional(df, value_col, out_col, file, issues):
    if df is None:
        return None
    df = df.copy()
    df["SKU_ID"] = _norm_ids(df, "SKU_ID", file, issues)
    out = {}
    for r in df.to_dict("records"):
        v = _to_float(r[value_col])
        if not r["SKU_ID"] or math.isnan(v) or v < 0:
            issues.append(make_issue(file, f"row {r['_row']}", f"{value_col} '{r[value_col]}' invalid for '{r['SKU_ID']}'", "Row ignored", sku_id=r["SKU_ID"], severity="info"))
            continue
        out[r["SKU_ID"]] = v
    return out


def _clean_distributor_sales(df, win, issues):
    if df is None:
        return None
    f = "distributor_sales.csv"
    df = df.copy()
    df["SKU_ID"] = _norm_ids(df, "SKU_ID", f, issues)
    df["Distributor_ID"] = _norm_ids(df, "Distributor_ID", f, issues, sku_col=False)
    rows = []
    for r in df.to_dict("records"):
        wk, u = parse_iso_week(r["Week"]), _to_float(r["Units_Sold"])
        if wk is None or math.isnan(u) or u < 0 or wk not in set(win):
            continue
        rows.append({"distributor_id": r["Distributor_ID"], "sku_id": r["SKU_ID"], "week_start": wk, "units": u})
    return pd.DataFrame(rows, columns=["distributor_id", "sku_id", "week_start", "units"])


# --------------------------------------------------------------------------- entry point
def clean(raw: dict, cfg: dict, run_date: dt.date) -> tuple[dict, list[dict]]:
    issues: list[dict] = []
    win = window_weeks(run_date, cfg["history"]["window_weeks"])
    calendar = _clean_calendar(raw["calendar"])
    _check_calendar(calendar, run_date, cfg)
    dist = _clean_distributors(raw["distributors"], cfg, issues)
    master = _clean_master(raw["sku_master"], dist, issues)
    inventory = _clean_inventory(raw["inventory"], run_date, issues)
    sales = _clean_sales(raw["sales"], cfg, win, issues)

    m, s, i = set(master.sku_id), set(sales.sku_id), set(inventory.sku_id)
    for sku in sorted(s - m):
        issues.append(make_issue("weekly_sales.csv", f"{(sales.sku_id == sku).sum()} rows", f"{sku} has sales but is not in sku_master", "Not planned; routed to review", sku_id=sku))
    for sku in sorted(i - m):
        issues.append(make_issue("current_inventory.csv", "n/a", f"{sku} has inventory but is not in sku_master", "Not planned; routed to review", sku_id=sku))
    for sku in sorted(m - i):
        issues.append(make_issue("sku_master.csv", "n/a", f"{sku} is in sku_master but not in current_inventory", "Not planned (stock unknown); routed to review", sku_id=sku))
    for sku in sorted(m - s):
        issues.append(make_issue("sku_master.csv", "n/a", f"{sku} is in sku_master but has no sales history", "Not planned; routed to review", sku_id=sku))

    cleaned = {
        "calendar": calendar, "distributors": dist, "master": master, "inventory": inventory, "sales": sales,
        "open_pos": _clean_optional(raw.get("open_pos"), "Open_PO_Qty", "open_po_qty", "open_purchase_orders.csv", issues),
        "prices": _clean_optional(raw.get("prices"), "Unit_Price", "unit_price", "sku_prices.csv", issues),
        "distributor_sales": _clean_distributor_sales(raw.get("distributor_sales"), win, issues),
    }
    return cleaned, issues
