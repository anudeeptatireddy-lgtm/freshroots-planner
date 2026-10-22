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


def test_summary_and_generation_blocked_until_every_exception_decided(run_dir):
    at = fresh()
    assert btn(at, "generate").disabled
    assert any("Cannot generate POs yet: 4 exception(s)" in e.value for e in at.error)
    assert [m.value for m in at.metric] == ["15", "4", "2", "9"]
    assert at.get("progress")[0].proto.text == "0 of 4 exceptions decided"

    t = outputs.load_planning_table(run_dir)
    ex = t[t.status == "NEEDS_REVIEW"]
    review.append_log(run_dir / "review_log.csv", [review.make_decision(r.sku_id, r.order_qty, "approve", "Raghav") for r in ex.iloc[:3].itertuples()])
    assert btn(fresh(), "generate").disabled                                   # one still waiting

    last = ex.iloc[3]
    review.append_log(run_dir / "review_log.csv", [review.make_decision(last.sku_id, last.order_qty, "reject", "Raghav", note="hold")])
    at = fresh()
    assert not btn(at, "generate").disabled
    at.text_input(key="reviewer").set_value("Raghav").run()
    btn(at, "generate").click().run()
    assert not at.exception
    keys = {b.key for b in at.get("download_button")}
    assert {"dl_zoho", "dl_handoff", "dl_log2"} <= keys and any(k.startswith("dl_PO_") for k in keys)   # persist after rerun
    z = pd.read_csv(run_dir / "purchase_orders_zoho_import.csv")
    assert last.sku_id not in set(z["SKU"]) or last.order_qty == 0


def test_one_tap_decisions_require_a_name_and_are_logged(run_dir):
    at = fresh()
    btn(at, "exc_suggest_SKU003").click().run()                  # "Use 309" with no name
    assert review.read_log(run_dir / "review_log.csv").empty
    assert any("Reviewer name is required" in e.value for e in at.error)

    at.text_input(key="reviewer").set_value("Raghav").run()
    at.text_input(key="exc_note_SKU003").set_value("top up to 6 weeks").run()
    btn(at, "exc_suggest_SKU003").click().run()
    log = review.read_log(run_dir / "review_log.csv")
    assert list(log.sku_id) == ["SKU003"]
    r = log.iloc[0]
    assert (r.system_qty, r.final_qty, r.decision, r.reviewer, r.note) == (300, 309, "edit", "Raghav", "top up to 6 weeks")
    assert r.timestamp
    assert fresh().get("progress")[0].proto.text == "1 of 4 exceptions decided"     # progress moves


def test_approve_reject_and_edit_buttons(run_dir):
    at = fresh()
    at.text_input(key="reviewer").set_value("Raghav").run()
    btn(at, "exc_approve_SKU001").click().run()
    btn(at, "exc_reject_SKU013").click().run()
    at.number_input(key="exc_qty_SKU007").set_value(25).run()
    btn(at, "exc_saveedit_SKU007").click().run()
    log = review.latest_decisions(review.read_log(run_dir / "review_log.csv")).set_index("sku_id")
    assert (log.loc["SKU001", "decision"], log.loc["SKU001", "final_qty"]) == ("approve", 750)
    assert (log.loc["SKU013", "decision"], log.loc["SKU013", "final_qty"]) == ("reject", 0)
    assert (log.loc["SKU007", "decision"], log.loc["SKU007", "final_qty"]) == ("edit", 25)


def test_app_runs_planner_itself_when_no_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("FRESHROOTS_OUTPUTS", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception and [b for b in at.button if b.key == "run_now"]      # empty state offers a run
    btn(at, "run_now").click().run()
    assert not at.exception
    assert (tmp_path / "2026-10-19" / "planning_table.csv").exists()
    assert [m.value for m in at.metric] == ["15", "4", "2", "9"]
