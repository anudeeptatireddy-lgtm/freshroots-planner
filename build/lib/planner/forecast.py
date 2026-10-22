"""Stage 5: rules-based 4-week forecast = avg_weekly_12w x the uplift of each week's month."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from planner.common import forecast_week_starts


def apply_forecast(table: pd.DataFrame, cleaned: dict, cfg: dict, run_date: dt.date) -> pd.DataFrame:
    n = cfg["history"]["forecast_weeks"]
    starts = forecast_week_starts(run_date, n)
    ups = [cfg["festival"]["uplift"] if cleaned["calendar"][d.strftime("%Y-%m")] else cfg["festival"]["non_festival_uplift"]
           for d in starts]
    out = pd.DataFrame(index=table.index)
    for i, u in enumerate(ups, start=1):
        out[f"forecast_w{i}"] = table["avg_weekly_12w"] * u
    out["forecast_total_4w"] = out[[f"forecast_w{i}" for i in range(1, n + 1)]].sum(axis=1, min_count=n)
    out["forecast_week_starts"] = ", ".join(d.isoformat() for d in starts)
    return pd.concat([table, out], axis=1)
