"""Acceptance table from the build brief (section 4). Do not edit expected values to match code."""
import pytest

from planner.clean import clean
from planner.forecast import apply_forecast
from planner.load import load_all
from planner.organise import organise
from planner.rules import apply_rules
from tests.conftest import RUN_DATE

# sku: (perish, std, on_hand, avg12, avg4, change, adj, cover, flag, qty, cover_after)
EXPECTED = {
    "SKU001": ("Low", 500, 900, 214.92, 261.00, 0.214, 268.65, 3.35, "HIGH_DEMAND + STOCKOUT_RISK", 750, 6.14),
    "SKU002": ("Low", 200, 1200, 83.75, 83.75, 0.0, 104.69, 11.46, "HEALTHY", 0, 11.46),
    "SKU003": ("Low", 300, 820, 150.50, 150.75, 0.002, 188.12, 4.36, "STOCKOUT_RISK", 300, 5.95),
    "SKU004": ("High", 150, 180, 79.83, 81.00, 0.015, 99.79, 1.80, "STOCKOUT_RISK", 150, 3.31),
    "SKU005": ("Low", 150, 600, 59.50, 58.25, -0.021, 74.38, 8.07, "HEALTHY", 0, 8.07),
    "SKU006": ("Low", 100, 1100, 39.58, 40.25, 0.017, 49.48, 22.23, "OVERSTOCK", 0, 22.23),
    "SKU007": ("High", 400, 620, 121.50, 133.50, 0.099, 151.88, 4.08, "OVERSTOCK", 0, 4.08),
    "SKU008": ("Low", 300, 950, 108.75, 103.00, -0.053, 135.94, 6.99, "HEALTHY", 0, 6.99),
    "SKU009": ("Low", 80, 400, 34.08, 34.75, 0.020, 42.60, 9.39, "HEALTHY", 0, 9.39),
    "SKU010": ("Low", 60, 260, 24.42, 24.75, 0.014, 30.52, 8.52, "HEALTHY", 0, 8.52),
    "SKU011": ("High", 500, 460, 204.33, 209.25, 0.024, 255.42, 1.80, "STOCKOUT_RISK", 500, 3.76),
    "SKU012": ("Low", 150, 480, 56.75, 60.00, 0.057, 70.94, 6.77, "HEALTHY", 0, 6.77),
    "SKU013": ("Low", 120, 180, 45.42, 44.75, -0.015, 56.77, 3.17, "STOCKOUT_RISK", 120, 5.28),
    "SKU014": ("Low", 200, 620, 72.42, 77.50, 0.070, 90.52, 6.85, "HEALTHY", 0, 6.85),
    "SKU015": ("Low", 80, 360, 29.83, 28.75, -0.036, 37.29, 9.65, "HEALTHY", 0, 9.65),
}


def build(data_dir, cfg):
    raw, _, _ = load_all(data_dir, cfg)
    cleaned, _ = clean(raw, cfg, RUN_DATE)
    t = organise(cleaned, cfg, RUN_DATE)
    t = apply_rules(t, cfg)
    t = apply_forecast(t, cleaned, cfg, RUN_DATE)
    return t.set_index("sku_id")


@pytest.fixture()
def table(data_dir, cfg):
    return build(data_dir, cfg)


@pytest.mark.parametrize("sku", sorted(EXPECTED))
def test_acceptance_row(table, sku):
    perish, std, oh, a12, a4, chg, adj, cover, flag, qty, after = EXPECTED[sku]
    r = table.loc[sku]
    assert r.perishability == perish
    assert r.standard_reorder_qty == std
    assert r.units_on_hand == oh
    assert round(r.avg_weekly_12w, 2) == a12
    assert round(r.avg_weekly_4w, 2) == a4
    assert round(r.change_4w_vs_12w, 3) == chg
    assert round(r.adjusted_weekly_demand, 2) == adj
    assert round(r.weeks_of_cover, 2) == cover
    assert r["flag"] == flag
    assert r.order_qty == qty
    assert round(r.weeks_of_cover_after_order, 2) == after


def test_festival_and_window(table):
    assert table.is_festival.all() and (table.uplift == 1.25).all()
    assert (table.history_weeks == 16).all() and not table.is_new_launch.any()


def test_uplift_applied_before_thresholds(table, data_dir, cfg):
    """SKU002: 14.33 weeks without uplift (overstock), 11.46 with it (healthy)."""
    r = table.loc["SKU002"]
    assert round(r.inventory_position / r.avg_weekly_12w, 2) == 14.33
    assert r["flag"] == "HEALTHY"


def test_uplift_one_makes_sku002_overstock(data_dir, cfg):
    cfg["festival"]["uplift"] = 1.00
    assert build(data_dir, cfg).loc["SKU002", "flag"] == "OVERSTOCK"


def test_forecast(table):
    r = table.loc["SKU001"]
    assert round(r.forecast_w1, 2) == round(214.9166667 * 1.25, 2)
    assert round(r.forecast_total_4w, 2) == round(214.9166667 * 1.25 * 4, 2)
    assert r.forecast_week_starts == "2026-10-19, 2026-10-26, 2026-11-02, 2026-11-09"


def test_forecast_uses_calendar_month_per_week(data_dir, cfg):
    """A run in late Nov: weeks starting Nov 23/30 hit Nov (festival) then Dec (not)."""
    import datetime as dt
    raw, _, _ = load_all(data_dir, cfg)
    run = dt.date(2026, 11, 23)
    cleaned, _ = clean(raw, cfg, run)
    t = apply_forecast(organise(cleaned, cfg, run), cleaned, cfg, run)
    r = t.iloc[0]
    assert round(r.forecast_w1 / r.avg_weekly_12w, 2) == 1.25   # Nov 23
    assert round(r.forecast_w2 / r.avg_weekly_12w, 2) == 1.25   # Nov 30 (a Monday in Nov)
    assert round(r.forecast_w3 / r.avg_weekly_12w, 2) == 1.00   # Dec 7


def test_every_flag_has_reason(table):
    assert (table.flag_reasons.str.len() > 0).all()
