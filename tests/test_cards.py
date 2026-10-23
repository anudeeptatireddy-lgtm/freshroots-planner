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


def test_sku013_option_rows(rows):
    opts = cards.options_for(rows["SKU013"])
    assert [(o[0], o[1], o[2]) for o in opts] == [("Use suggested · 161", "edit", 161), ("Approve · 120", "approve", 120), ("Reject · 0", "reject", 0)]
    r = rows["SKU013"]
    assert [fr.wk(o[3], r.min_weeks, r.max_weeks) for o in opts] == ["6.01", "5.3", "3.2"]   # handoff says 6.0; its wk() shows 6.01 (6.0066 is just above the band edge)
    assert "in band" in fr.outcome(opts[0][3], r.min_weeks, r.max_weeks) and "below band" in fr.outcome(opts[1][3], r.min_weeks, r.max_weeks)


def test_sku003_shows_two_decimals_not_six(rows):
    r = rows["SKU003"]
    assert fr.wk(cards.cover_after(r, 300), r.min_weeks, r.max_weeks) == "5.95"


def test_paused_label_and_no_suggestion_options(rows):
    opts = cards.options_for(rows["SKU007"])
    assert [o[0] for o in opts] == ["Approve · 0 (paused)", "Reject · 0"]
    assert [o[0] for o in cards.options_for(rows["SKU001"])] == ["Approve · 750", "Reject · 0"]


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
