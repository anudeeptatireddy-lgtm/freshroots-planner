import datetime as dt

import pandas as pd
import pytest

from planner.exceptions import classify, distributor_anomalies
from planner.pipeline import run_pipeline
from tests.conftest import RUN_DATE


@pytest.fixture()
def result(data_dir, cfg):
    return run_pipeline(data_dir, RUN_DATE, cfg)


def codes(t, sku):
    v = t.set_index("sku_id").loc[sku, "exceptions"]
    return set(v.split("; ")) if v else set()


def test_expected_exceptions_exact(result):
    t = result.table
    exc = {r.sku_id: set(r.exceptions.split("; ")) for r in t.itertuples() if r.exceptions}
    assert exc == {"SKU001": {"BORDERLINE"}, "SKU003": {"BELOW_MIN_AFTER_ORDER"},
                   "SKU013": {"BELOW_MIN_AFTER_ORDER"}, "SKU007": {"BORDERLINE"}}


def test_status_and_auto_approved(result):
    t = result.table.set_index("sku_id")
    assert sorted(t[t.status == "AUTO_APPROVED"].index) == ["SKU004", "SKU011"]
    assert set(t[t.status == "NEEDS_REVIEW"].index) == {"SKU001", "SKU003", "SKU007", "SKU013"}
    assert (t[t.status == "NO_ORDER"].order_qty == 0).all()


def test_below_min_suggestion_reaches_min(result):
    t = result.table.set_index("sku_id")
    for sku in ("SKU003", "SKU013"):
        r = t.loc[sku]
        assert r.suggested_qty > r.order_qty
        assert (r.inventory_position + r.suggested_qty) / r.adjusted_weekly_demand >= r.min_weeks
        assert (r.inventory_position + r.suggested_qty - 1) / r.adjusted_weekly_demand < r.min_weeks
        assert "top-up" in r.exception_reasons


def test_every_exception_has_plain_reason(result):
    t = result.table
    assert (t[t.exceptions != ""].exception_reasons.str.len() > 20).all()


def _mod(result, cfg, sku, **changes):
    t = result.table.copy()
    i = t.index[t.sku_id == sku][0]
    for k, v in changes.items():
        t.loc[i, k] = v
    return t


def _reclassify(result, cfg, t):
    base = t[[c for c in t.columns if c not in ("exceptions", "exception_reasons", "suggested_qty", "suggested_note", "status", "data_issues")]]
    return classify(base, [], cfg, RUN_DATE).set_index("sku_id")


def test_sharp_drop(result, cfg):
    t = _mod(result, cfg, "SKU008", change_4w_vs_12w=-0.35)
    assert "SHARP_DROP" in set(_reclassify(result, cfg, t).loc["SKU008", "exceptions"].split("; "))


def test_above_max_after_order_perishable(result, cfg):
    t = _mod(result, cfg, "SKU004", weeks_of_cover_after_order=5.0)
    r = _reclassify(result, cfg, t).loc["SKU004"]
    assert "ABOVE_MAX_AFTER_ORDER" in r.exceptions and "write-off" in r.exception_reasons


def test_overstock_zero_order_is_not_above_max(result):
    assert "ABOVE_MAX_AFTER_ORDER" not in codes(result.table, "SKU006")


def test_new_launch(data_dir, cfg, tmp_path):
    import shutil
    for f in data_dir.glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    lines = [ln for ln in (tmp_path / "weekly_sales.csv").read_text().splitlines()
             if not (ln.startswith("SKU010,") and ln.split(",")[1] < "2026-W38")]
    (tmp_path / "weekly_sales.csv").write_text("\n".join(lines) + "\n")
    res = run_pipeline(tmp_path, RUN_DATE, cfg)
    r = res.table.set_index("sku_id").loc["SKU010"]
    assert r.is_new_launch and r.history_weeks == 5
    assert "NEW_LAUNCH" in r.exceptions and r.status == "NEEDS_REVIEW"
    assert "DATA_ISSUE" not in r.exceptions          # weeks before launch are not "missing"


def test_data_issue_routes_to_review(dirty_dir, cfg):
    res = run_pipeline(dirty_dir, RUN_DATE, cfg)
    t = res.table.set_index("sku_id")
    assert "DATA_ISSUE" in t.loc["SKU005", "exceptions"]       # missing week
    assert t.loc["SKU005", "status"] == "NEEDS_REVIEW"
    assert "DATA_ISSUE" in t.loc["SKU099", "exceptions"]       # unknown SKU still in table
    assert t.loc["SKU099", "flag"] == "NOT_PLANNED"
    assert t.loc["SKU015", "flag"] == "NOT_PLANNED"            # no inventory


def test_borderline_thresholds_are_config_driven(data_dir, cfg):
    cfg["exceptions"]["borderline_change_pp"] = 0.0
    cfg["exceptions"]["borderline_weeks"] = 0.0
    res = run_pipeline(data_dir, RUN_DATE, cfg)
    assert "SKU001" not in set(res.table[res.table.exceptions.str.contains("BORDERLINE")].sku_id)


def test_hooks_inactive_without_data(result, cfg):
    assert distributor_anomalies(None, cfg, RUN_DATE) == {}
    assert not result.table.exceptions.str.contains("DISTRIBUTOR_ANOMALY|HIGH_VALUE").any()


def test_distributor_anomaly_hook_active(cfg):
    win = [dt.date(2026, 7, 27) + dt.timedelta(days=7 * i) for i in range(12)]
    rows = [{"distributor_id": "D1", "sku_id": "SKU001", "week_start": w, "units": 10 if i < 8 else 30} for i, w in enumerate(win)]
    out = distributor_anomalies(pd.DataFrame(rows), cfg, RUN_DATE)
    assert "SKU001" in out and "D1" in out["SKU001"]


def test_high_value_hook(data_dir, cfg, tmp_path):
    import shutil
    for f in data_dir.glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "sku_prices.csv").write_text("SKU_ID,Unit_Price\nSKU004,100\nSKU011,100\n")
    cfg["exceptions"]["high_value_threshold"] = 20000
    res = run_pipeline(tmp_path, RUN_DATE, cfg)
    t = res.table.set_index("sku_id")
    assert "HIGH_VALUE" in t.loc["SKU011", "exceptions"] and t.loc["SKU011", "status"] == "NEEDS_REVIEW"   # 500 x 100 = 50,000
    assert "HIGH_VALUE" not in t.loc["SKU004", "exceptions"]                                                 # 15,000
