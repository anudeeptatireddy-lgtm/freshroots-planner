import datetime as dt

import pandas as pd
import pytest

from planner.clean import clean
from planner.common import PlannerError
from planner.load import load_all
from tests.conftest import RUN_DATE


def run_clean(data_dir, cfg, run_date=RUN_DATE):
    raw, hashes, _ = load_all(data_dir, cfg)
    return clean(raw, cfg, run_date)


def issue_df(issues):
    return pd.DataFrame(issues)


def test_clean_real_data_has_no_review_issues(data_dir, cfg):
    cleaned, issues = run_clean(data_dir, cfg)
    review = [i for i in issues if i["severity"] == "review"]
    assert review == []
    assert len(cleaned["sales"]) == 240
    # two distributors outside Maharashtra/Goa are noted as info only
    assert sum("outside" in i["issue"] for i in issues) == 2


def test_missing_column_names_file_and_column(data_dir, cfg, tmp_path):
    import shutil
    for f in data_dir.glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "sku_master.csv").write_text("SKU_ID,SKU_Name\nSKU001,x\n")
    with pytest.raises(PlannerError, match=r"sku_master.csv.*Perishability"):
        load_all(tmp_path, cfg)


def test_missing_required_file(data_dir, cfg, tmp_path):
    with pytest.raises(PlannerError, match="not found"):
        load_all(tmp_path, cfg)


def test_crlf_files_load(dirty_dir, cfg):
    raw, _, _ = load_all(dirty_dir, cfg)
    assert "SKU_ID" in raw["sales"].columns


def test_dirty_fixture_issues(dirty_dir, cfg):
    cleaned, issues = run_clean(dirty_dir, cfg)
    df = issue_df(issues)
    sales = cleaned["sales"]

    def has(sku, text, sev=None):
        sub = df[(df.sku_id == sku) & df.issue.str.contains(text, regex=False)]
        return len(sub) > 0 and (sev is None or (sub.severity == sev).any())

    assert has("SKU009", "whitespace/lowercase", "info")             # normalised id
    assert "SKU009" in set(sales.sku_id) and " SKU009 " not in set(sales.sku_id)
    assert has("SKU006", "Negative", "review")
    assert has("SKU007", "blank", "review")
    assert has("SKU005", "Missing week", "review")
    assert has("SKU010", "identical copy", "info")
    assert has("SKU011", "differs from other copy", "review")
    assert has("SKU099", "not in sku_master", "review")
    assert has("SKU015", "not in current_inventory", "review")
    assert has("SKU003", "not High/Low", "review")
    assert has("SKU002", "not in distributor master", "review")
    assert has("SKU002", "inconsistent case", "info")
    assert has("SKU012", "not complete", "info")
    assert has("SKU013", "Zero", "review")
    # nothing silently dropped: negative/blank units are NaN rows, not zeros
    neg = sales[(sales.sku_id == "SKU006") & (sales.week_start == dt.date(2026, 8, 31))]  # 2026-W36
    assert len(neg) == 1 and pd.isna(neg.units.iloc[0])
    # SKU005 missing week is absent, not zero
    assert not ((sales.sku_id == "SKU005") & (sales.week_start == dt.date(2026, 8, 24))).any()
    # duplicates: exactly one row kept per SKU/week
    assert not sales.duplicated(["sku_id", "week_start"]).any()
    # every issue row has all fields
    assert set(df.columns) == {"file", "row_ref", "sku_id", "issue", "action", "severity"}
    assert (df.action != "").all()


def test_run_month_not_in_calendar_stops(data_dir, cfg):
    with pytest.raises(PlannerError, match="calendar.csv has no row"):
        run_clean(data_dir, cfg, run_date=dt.date(2027, 3, 1))


def test_inventory_date_mismatch_flags(data_dir, cfg):
    cleaned, issues = run_clean(data_dir, cfg, run_date=dt.date(2026, 10, 20))
    assert sum("differs from run date" in i["issue"] for i in issues) == 15
