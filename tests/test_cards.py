"""Acceptance values from the design handoff (section 5): headline wording and cover-after per option."""
import re
import sys

import pytest

from planner.pipeline import run_pipeline
from tests.conftest import ROOT, RUN_DATE

sys.path.insert(0, str(ROOT / "app"))
import cards  # noqa: E402
import fr_html as fr  # noqa: E402


@pytest.fixture()
def rows(data_dir, cfg):
    t = run_pipeline(data_dir, RUN_DATE, cfg).table.set_index("sku_id", drop=False)
    return {s: next(t.loc[[s]].itertuples()) for s in t.index}


def test_sku001_headline(rows):
    r = rows["SKU001"]
    h = fr.headline(r.weeks_of_cover, cards.cover_after(r, r.order_qty), r.min_weeks, r.max_weeks, int(r.order_qty), False, True)
    text = re.sub(r"<[^>]+>", "", h)
    assert text == "Stock lasts 3.4 weeks; the minimum is 6. The rules order 750 (1.5× standard, for high demand), which brings it to 6.1 weeks."


def test_sku003_shows_two_decimals_not_six(rows):
    r = rows["SKU003"]
    assert fr.wk(cards.cover_after(r, 300), r.min_weeks, r.max_weeks) == "5.95"


def test_gauge_label_matches_headline_rounding(rows):
    r = rows["SKU003"]
    html = fr.gauge(r.weeks_of_cover, cards.cover_after(r, 300), r.min_weeks, r.max_weeks, False, verdict=False)
    assert "After order 5.95 wk" in html and "After order 6.0 wk" not in html


def _text(html):
    return re.sub(r"<[^>]+>", " ", html)


def test_compare_table_sku013_reads_down_each_choice(rows):
    r = rows["SKU013"]
    html = cards._table(r)
    assert "Now" in html and "Rules say" in html and "Suggested" in html
    flat = " ".join(_text(html).split())
    assert "Order (units) — 120 161" in flat
    assert "Stock (units) 180 300 341" in flat
    assert "Weeks of cover" in flat and "3.2 5.3 6.01" in flat
    assert "↓ Low ↓ Low ✓ OK" in flat


def test_compare_table_paused_and_no_suggestion(rows):
    flat = " ".join(_text(cards._table(rows["SKU007"])).split())
    assert "Suggested" not in flat and "0 paused" in flat           # SKU007: no order, no alternative
    assert "Order (units) — 750" in " ".join(_text(cards._table(rows["SKU001"])).split())


def test_header_shows_category_and_price(rows):
    head = " ".join(_text(cards._head(rows["SKU001"])).split())
    assert "Freshroots Mango Drink 200ml" in head and "Beverage · Price not in data" in head


def test_price_and_order_value_when_prices_exist(data_dir, cfg, tmp_path):
    import shutil
    for f in data_dir.glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    (tmp_path / "sku_prices.csv").write_text("SKU_ID,Unit_Price\nSKU001,12.5\n")
    t = run_pipeline(tmp_path, RUN_DATE, cfg).table.set_index("sku_id", drop=False)
    r = next(t.loc[["SKU001"]].itertuples())
    assert "₹12.50 per unit" in " ".join(_text(cards._head(r)).split())
    assert "Order value — ₹9,375" in " ".join(_text(cards._table(r)).split())      # 750 x 12.5


def test_rows_view_changes_only_decided_and_modified_rows():
    from rows import compute_changes
    base = [{"SKU": "A", "Rules": 100, "Final qty": 100, "Decision": "Pending", "Note": ""},
            {"SKU": "B", "Rules": 50, "Final qty": 50, "Decision": "Pending", "Note": ""},
            {"SKU": "C", "Rules": 80, "Final qty": 80, "Decision": "Approve", "Note": "ok"},
            {"SKU": "D", "Rules": 30, "Final qty": 30, "Decision": "Pending", "Note": ""}]
    new = [dict(base[0], Decision="Approve"),
           dict(base[1], Decision="Approve", **{"Final qty": 40}),
           dict(base[2]),                                            # already saved, untouched
           dict(base[3], Decision="Reject", **{"Final qty": 30})]
    assert compute_changes(base, new) == [("A", 100.0, "approve", 100.0, ""), ("B", 50.0, "edit", 40.0, ""),
                                          ("D", 30.0, "reject", 0.0, "")]
