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


def test_decision_buttons_disabled_without_a_name(run_dir):
    at = fresh()
    assert all(btn(at, k).disabled for k in ("btn-SKU001-0", "btn-SKU003-0", "btn-SKU013-2", "save-SKU007"))
    assert any("Add your name at the top" in c.value for c in at.caption)
    with_name(at)
    assert not btn(at, "btn-SKU001-0").disabled


def test_one_tap_use_suggested_is_logged(run_dir):
    at = with_name(fresh())
    at.text_input(key="note-SKU003").set_value("top up to 6 weeks").run()
    btn(at, "btn-SKU003-0").click().run()                        # primary on SKU003 = "Use suggested · 309"
    log = review.read_log(run_dir / "review_log.csv")
    assert list(log.sku_id) == ["SKU003"]
    r = log.iloc[0]
    assert (r.system_qty, r.final_qty, r.decision, r.reviewer, r.note) == (300, 309, "edit", "Raghav", "top up to 6 weeks")
    assert r.timestamp
    at = fresh()
    assert at.get("progress")[0].proto.text == "1 of 4 exceptions decided"
    assert "Review · 3" in [t.label for t in at.tabs]


def test_approve_reject_edit_and_change_decision(run_dir):
    at = with_name(fresh())
    btn(at, "btn-SKU001-0").click().run()                        # Approve · 750
    btn(at, "btn-SKU013-2").click().run()                        # Reject · 0
    at.number_input(key="qty-SKU007").set_value(25).run()
    btn(at, "save-SKU007").click().run()                         # edit
    log = review.latest_decisions(review.read_log(run_dir / "review_log.csv")).set_index("sku_id")
    assert (log.loc["SKU001", "decision"], log.loc["SKU001", "final_qty"]) == ("approve", 750)
    assert (log.loc["SKU013", "decision"], log.loc["SKU013", "final_qty"]) == ("reject", 0)
    assert (log.loc["SKU007", "decision"], log.loc["SKU007", "final_qty"]) == ("edit", 25)

    at = fresh()
    assert any(b.key == "change-SKU001" for b in at.button)       # decided cards offer "Change decision"
    btn(at, "change-SKU001").click().run()
    btn(with_name(at), "btn-SKU001-0").click().run()              # re-open and re-decide: the last decision wins
    log = review.read_log(run_dir / "review_log.csv")
    assert (log.sku_id == "SKU001").sum() == 2                    # append-only log keeps both


def test_app_runs_planner_itself_when_no_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("FRESHROOTS_OUTPUTS", str(tmp_path))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception and [b for b in at.button if b.key == "run_now"]      # empty state offers a run
    btn(at, "run_now").click().run()
    assert not at.exception
    assert (tmp_path / "2026-10-19" / "planning_table.csv").exists()
    assert [m.value for m in at.metric][:4] == ["15", "4", "2", "9"]
