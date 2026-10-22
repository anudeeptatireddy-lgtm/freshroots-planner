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


def test_generation_blocked_until_every_exception_decided(run_dir):
    at = fresh()
    gen = [b for b in at.button if b.key == "generate"][0]
    assert gen.disabled
    assert any("Cannot generate POs: 4 exception(s)" in e.value for e in at.error)
    assert [m.value for m in at.metric][:3] == ["15", "4", "2"]

    t = outputs.load_planning_table(run_dir)
    ex = t[t.status == "NEEDS_REVIEW"]
    review.append_log(run_dir / "review_log.csv", [review.make_decision(r.sku_id, r.order_qty, "approve", "Raghav") for r in ex.iloc[:3].itertuples()])
    at = fresh()
    assert [b for b in at.button if b.key == "generate"][0].disabled           # one still waiting

    last = ex.iloc[3]
    review.append_log(run_dir / "review_log.csv", [review.make_decision(last.sku_id, last.order_qty, "reject", "Raghav", note="hold")])
    at = fresh()
    gen = [b for b in at.button if b.key == "generate"][0]
    assert not gen.disabled
    at.text_input(key="reviewer").set_value("Raghav").run()
    [b for b in at.button if b.key == "generate"][0].click().run()
    assert not at.exception
    assert (run_dir / "purchase_orders_zoho_import.csv").exists()
    keys = {b.key for b in at.get("download_button")}
    assert {"dl_zoho", "dl_handoff", "dl_log2"} <= keys and any(k.startswith("dl_PO_") for k in keys)   # persist after rerun
    z = pd.read_csv(run_dir / "purchase_orders_zoho_import.csv")
    assert last.sku_id not in set(z["SKU"]) or last.order_qty == 0


def _submit(at, sku_index):
    forms = [b for b in at.button if b.label == "Save decision"]
    forms[sku_index].click().run()          # exception forms render in order SKU001, SKU003, SKU013, SKU007


def test_save_decision_through_form_requires_name(run_dir):
    at = fresh()
    at.radio(key="exc_SKU003_choice").set_value("Edit quantity")
    at.number_input(key="exc_SKU003_qty").set_value(309)
    at.text_input(key="exc_SKU003_note").set_value("top up to 6 weeks")
    _submit(at, 1)
    assert review.read_log(run_dir / "review_log.csv").empty
    assert any("Reviewer name is required" in e.value for e in at.error)

    at.text_input(key="reviewer").set_value("Raghav").run()
    at.radio(key="exc_SKU003_choice").set_value("Edit quantity")
    at.number_input(key="exc_SKU003_qty").set_value(309)
    at.text_input(key="exc_SKU003_note").set_value("top up to 6 weeks")
    _submit(at, 1)
    log = review.read_log(run_dir / "review_log.csv")
    assert list(log.sku_id) == ["SKU003"]
    r = log.iloc[0]
    assert (r.system_qty, r.final_qty, r.decision, r.reviewer, r.note) == (300, 309, "edit", "Raghav", "top up to 6 weeks")
    assert r.timestamp


def test_app_runs_planner_itself_when_no_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("FRESHROOTS_OUTPUTS", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception and [b for b in at.button if b.key == "run_now"]      # empty state offers a run
    [b for b in at.button if b.key == "run_now"][0].click().run()
    assert not at.exception
    assert (tmp_path / "2026-10-19" / "planning_table.csv").exists()
    assert [m.value for m in at.metric][:3] == ["15", "4", "2"]
