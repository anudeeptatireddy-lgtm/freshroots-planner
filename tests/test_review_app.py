import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from planner import outputs, review
from planner.cli import main
from tests.conftest import ROOT

APP = str(ROOT / "app" / "review_app.py")


@pytest.fixture()
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FRESHROOTS_OUTPUTS", str(tmp_path))
    assert main(["run", "--data", str(ROOT / "data/raw"), "--run-date", "2026-10-19",
                 "--config", str(ROOT / "config.yaml"), "--outputs", str(tmp_path)]) == 0
    return tmp_path / "2026-10-19"


def fresh():
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    return at


def btn(at, key):
    return [b for b in at.button if b.key == key][0]


def with_name(at, name="Raghav"):
    at.text_input(key="reviewer").set_value(name).run()
    return at


def test_summary_and_generation_blocked_until_every_exception_decided(run_dir):
    at = fresh()
    assert btn(at, "generate").disabled
    assert any("4 exceptions still need a decision" in w.value for w in at.warning)
    assert [m.value for m in at.metric][:4] == ["15", "4", "2", "9"]
    assert [t.label for t in at.tabs] == ["Review · 4", "Auto · 2", "Orders", "All SKUs"]
    assert at.get("progress")[0].proto.text == "0 of 4 exceptions decided"

    t = outputs.load_planning_table(run_dir)
    ex = t[t.status == "NEEDS_REVIEW"]
    review.append_log(run_dir / "review_log.csv", [review.make_decision(r.sku_id, r.order_qty, "approve", "Raghav") for r in ex.iloc[:3].itertuples()])
    assert btn(fresh(), "generate").disabled                                   # one still waiting

    last = ex.iloc[3]
    review.append_log(run_dir / "review_log.csv", [review.make_decision(last.sku_id, last.order_qty, "reject", "Raghav", note="hold")])
    at = fresh()
    assert not btn(at, "generate").disabled
    assert at.get("progress")[0].proto.text == "All 4 exceptions decided"
    btn(with_name(at), "generate").click().run()
    assert not at.exception
    keys = {b.key for b in at.get("download_button")}
    assert {"dl_zoho", "dl_handoff", "dl_log2"} <= keys and any(k.startswith("dl_PO_") for k in keys)   # persist after rerun
    z = pd.read_csv(run_dir / "purchase_orders_zoho_import.csv")
    assert last.sku_id not in set(z["SKU"]) or last.order_qty == 0


def test_buttons_are_live_and_ask_for_a_name_when_tapped(run_dir):
    at = fresh()
    assert not any(btn(at, k).disabled for k in ("go-SKU001", "rej-SKU013", "sug-SKU003"))      # never greyed out
    btn(at, "go-SKU001").click().run()
    assert any("Enter your name at the top first" in e.value for e in at.error)
    assert review.read_log(run_dir / "review_log.csv").empty                                    # nothing saved without a name
    btn(with_name(at), "go-SKU001").click().run()
    assert list(review.read_log(run_dir / "review_log.csv").sku_id) == ["SKU001"]


def test_one_button_approves_or_saves_a_changed_quantity(run_dir):
    at = with_name(fresh())
    assert btn(at, "go-SKU001").label == "Approve · 750" and btn(at, "go-SKU007").label == "Approve · 0 (paused)"
    at.number_input(key="qty-SKU001").set_value(700).run()                                      # the box sits beside the button
    assert btn(at, "go-SKU001").label == "Save · 700 (changed)"
    btn(at, "go-SKU001").click().run()
    r = review.read_log(run_dir / "review_log.csv").iloc[0]
    assert (r.sku_id, r.system_qty, r.final_qty, r.decision) == ("SKU001", 750, 700, "edit")


def test_use_suggested_fills_the_box_then_one_tap_saves(run_dir):
    at = with_name(fresh())
    at.text_input(key="note-SKU003").set_value("top up to 6 weeks").run()
    btn(at, "sug-SKU003").click().run()
    assert at.number_input(key="qty-SKU003").value == 309 and btn(at, "go-SKU003").label == "Save · 309 (changed)"
    btn(at, "go-SKU003").click().run()
    log = review.read_log(run_dir / "review_log.csv")
    r = log.iloc[0]
    assert list(log.sku_id) == ["SKU003"]
    assert (r.system_qty, r.final_qty, r.decision, r.reviewer, r.note) == (300, 309, "edit", "Raghav", "top up to 6 weeks")
    assert r.timestamp
    at = fresh()
    assert at.get("progress")[0].proto.text == "1 of 4 exceptions decided"
    assert "Review · 3" in [t.label for t in at.tabs]


def test_approve_reject_and_change_decision(run_dir):
    at = with_name(fresh())
    btn(at, "go-SKU001").click().run()                           # Approve · 750
    btn(at, "rej-SKU013").click().run()                          # Reject
    log = review.latest_decisions(review.read_log(run_dir / "review_log.csv")).set_index("sku_id")
    assert (log.loc["SKU001", "decision"], log.loc["SKU001", "final_qty"]) == ("approve", 750)
    assert (log.loc["SKU013", "decision"], log.loc["SKU013", "final_qty"]) == ("reject", 0)

    at = fresh()
    assert any(b.key == "change-SKU001" for b in at.button)       # decided cards offer "Change decision"
    btn(at, "change-SKU001").click().run()
    btn(with_name(at), "go-SKU001").click().run()                 # re-open and re-decide: the last decision wins
    assert (review.read_log(run_dir / "review_log.csv").sku_id == "SKU001").sum() == 2


def test_cards_show_category_and_price_status(run_dir):
    html = " ".join(m.value for m in fresh().markdown)
    assert "Beverage · Price not in data" in html and "Condiment · Price not in data" in html


def test_app_runs_planner_itself_when_no_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("FRESHROOTS_OUTPUTS", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception and [b for b in at.button if b.key == "run_now"]      # empty state offers a run
    btn(at, "run_now").click().run()
    assert not at.exception
    assert (tmp_path / "2026-10-19" / "planning_table.csv").exists()
    assert [m.value for m in at.metric][:4] == ["15", "4", "2", "9"]


def test_zoho_preview_is_dry_run_and_send_is_locked(run_dir):
    t = outputs.load_planning_table(run_dir)
    review.append_log(run_dir / "review_log.csv", [review.make_decision(r.sku_id, r.order_qty, "approve", "Raghav") for r in t[t.status != "NO_ORDER"].itertuples()])
    at = with_name(fresh())
    btn(at, "generate").click().run()
    assert btn(at, "zoho_send").disabled                                   # locked: dry_run_only is true
    assert not (run_dir / "zoho_preview.json").exists()
    btn(at, "zoho_preview").click().run()
    assert not at.exception
    import json
    data = json.loads((run_dir / "zoho_preview.json").read_text())
    assert data["sent_to_zoho"] is False and len(data["purchase_orders"]) == 3
    assert any("nothing was sent to Zoho" in s.value for s in at.success)
    assert btn(at, "zoho_send").disabled
