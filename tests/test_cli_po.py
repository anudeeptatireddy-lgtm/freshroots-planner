import json

import pandas as pd
import pypdf
import pytest

from planner import outputs, review
from planner.cli import main
from planner.common import PlannerError, load_config
from tests.conftest import ROOT


def run_cli(tmp_path, *extra, data=None):
    code = main(["run", "--data", str(data or ROOT / "data/raw"), "--run-date", "2026-10-19",
                 "--config", str(ROOT / "config.yaml"), "--outputs", str(tmp_path), *extra])
    assert code == 0
    return sorted(p for p in tmp_path.iterdir())[-1]


def test_run_writes_stage_1_to_6_outputs(tmp_path):
    d = run_cli(tmp_path)
    assert d.name == "2026-10-19"
    for f in ("planning_table.csv", "data_quality_report.csv", "exceptions.csv", "run_log.json"):
        assert (d / f).exists()
    assert not (d / "purchase_orders_zoho_import.csv").exists()      # nothing before review
    log = json.loads((d / "run_log.json").read_text())
    assert log["skus_processed"] == 15
    assert log["exception_counts"] == {"BELOW_MIN_AFTER_ORDER": 2, "BORDERLINE": 2}
    assert log["flag_counts"]["STOCKOUT_RISK"] == 5 and log["flag_counts"]["HIGH_DEMAND"] == 1
    assert set(log["file_hashes_sha256"]) == {"weekly_sales.csv", "sku_master.csv", "distributor_master.csv",
                                              "current_inventory.csv", "calendar.csv"}
    assert len(pd.read_csv(d / "exceptions.csv")) == 4


def test_outputs_never_overwritten(tmp_path):
    run_cli(tmp_path)
    run_cli(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-10-19", "2026-10-19_r2"]


def test_reproducible(tmp_path):
    run_cli(tmp_path / "a")
    run_cli(tmp_path / "b")
    for f in ("planning_table.csv", "data_quality_report.csv", "exceptions.csv"):
        assert (tmp_path / "a/2026-10-19" / f).read_bytes() == (tmp_path / "b/2026-10-19" / f).read_bytes()


def test_auto_approve_rules_only_gives_two_pos(tmp_path):
    d = run_cli(tmp_path, "--auto-approve-rules-only")
    z = pd.read_csv(d / "purchase_orders_zoho_import.csv")
    assert sorted(zip(z["Vendor ID"], z["SKU"], z["Quantity"])) == [("DIST002", "SKU004", 150), ("DIST004", "SKU011", 500)]
    assert sorted(z["PO Number"]) == ["FR-PO-20261019-01", "FR-PO-20261019-02"]
    assert z["Unit Price"].isna().all()
    assert (d / "PO_FR-PO-20261019-01.pdf").exists() and (d / "PO_FR-PO-20261019-02.pdf").exists()
    md = (d / "sourcing_handoff.md").read_text()
    for sku in ("SKU001", "SKU003", "SKU007", "SKU013"):
        assert sku in md.split("## Excluded pending review")[1]
    rl = pd.read_csv(d / "review_log.csv")
    assert sorted(rl.sku_id) == ["SKU004", "SKU011"] and (rl.reviewer == review.AUTO_REVIEWER).all()
    log = json.loads((d / "run_log.json").read_text())
    assert log["po_count"] == 2 and log["lines_held_back"] == 4 and log["override_count"] == 0


def test_all_exceptions_approved_gives_three_pos(tmp_path):
    cfg = load_config(ROOT / "config.yaml")
    d = run_cli(tmp_path)
    t = outputs.load_planning_table(d)
    rows = [review.make_decision(r.sku_id, r.order_qty, "approve", "Raghav") for r in t[t.status != "NO_ORDER"].itertuples()]
    review.append_log(d / "review_log.csv", rows)
    outputs.finalize_run(d, cfg)
    z = pd.read_csv(d / "purchase_orders_zoho_import.csv")
    got = {(v, s): q for v, s, q in zip(z["Vendor ID"], z["SKU"], z["Quantity"])}
    assert got == {("DIST001", "SKU001"): 750, ("DIST001", "SKU013"): 120, ("DIST002", "SKU003"): 300,
                   ("DIST002", "SKU004"): 150, ("DIST004", "SKU011"): 500}
    assert z["PO Number"].nunique() == 3
    assert json.loads((d / "run_log.json").read_text())["override_rate"] == 0.0
    text = pypdf.PdfReader(d / "PO_FR-PO-20261019-01.pdf").pages[0].extract_text()
    assert "FR-PO-20261019-01" in text and "NutriFlow" in text and "Unit prices were not provided" in text


def test_po_blocked_while_exception_undecided(tmp_path):
    cfg = load_config(ROOT / "config.yaml")
    d = run_cli(tmp_path)
    t = outputs.load_planning_table(d)
    review.append_log(d / "review_log.csv", review.auto_decisions(t))
    with pytest.raises(PlannerError, match="still need a decision"):
        outputs.finalize_run(d, cfg)
    assert not (d / "purchase_orders_zoho_import.csv").exists()
    assert not review.can_generate_pos(t, review.latest_decisions(review.read_log(d / "review_log.csv")))


def test_edit_and_reject_are_overrides(tmp_path):
    cfg = load_config(ROOT / "config.yaml")
    d = run_cli(tmp_path)
    t = outputs.load_planning_table(d)
    rows = []
    for r in t[t.status != "NO_ORDER"].itertuples():
        if r.sku_id == "SKU003":
            rows.append(review.make_decision("SKU003", r.order_qty, "edit", "Raghav", final_qty=309, note="top up"))
        elif r.sku_id == "SKU013":
            rows.append(review.make_decision("SKU013", r.order_qty, "reject", "Raghav", note="supplier shortage"))
        else:
            rows.append(review.make_decision(r.sku_id, r.order_qty, "approve", "Raghav"))
    review.append_log(d / "review_log.csv", rows)
    res = outputs.finalize_run(d, cfg)
    z = res["lines"]
    assert 309 in set(z.quantity) and "SKU013" not in set(z.sku_id)
    assert "edited by reviewer" in " ".join(z.notes)
    s = res["stats"]
    assert s["overrides"] == 2 and s["decided_lines"] == 5 and s["override_rate"] == 0.4   # SKU007 qty 0->0 not counted
    assert json.loads((d / "run_log.json").read_text())["override_rate"] == 0.4


def test_latest_decision_wins_and_log_is_append_only(tmp_path):
    p = tmp_path / "review_log.csv"
    review.append_log(p, [review.make_decision("SKU001", 750, "approve", "A")])
    review.append_log(p, [review.make_decision("SKU001", 750, "edit", "A", final_qty=700)])
    assert len(review.read_log(p)) == 2
    assert review.latest_decisions(review.read_log(p)).final_qty.iloc[0] == 700


def test_decision_validation():
    with pytest.raises(PlannerError):
        review.make_decision("SKU001", 750, "approve", "  ")
    with pytest.raises(PlannerError):
        review.make_decision("SKU001", 750, "edit", "A", final_qty=-1)
    with pytest.raises(PlannerError):
        review.make_decision("SKU001", 750, "maybe", "A")


def test_cli_error_exit_code(tmp_path, capsys):
    code = main(["run", "--data", str(tmp_path), "--config", str(ROOT / "config.yaml"), "--outputs", str(tmp_path / "o")])
    assert code == 2 and "ERROR" in capsys.readouterr().out


def test_prices_flow_into_po(tmp_path, data_dir):
    import shutil
    src = tmp_path / "src"
    src.mkdir()
    for f in data_dir.glob("*.csv"):
        shutil.copy(f, src / f.name)
    (src / "sku_prices.csv").write_text("SKU_ID,Unit_Price\nSKU004,12.5\nSKU011,30\n")
    d = run_cli(tmp_path / "out", "--auto-approve-rules-only", data=src)
    z = pd.read_csv(d / "purchase_orders_zoho_import.csv")
    assert sorted(z["Unit Price"]) == [12.5, 30.0]


def test_ai_layer_off_or_unavailable_falls_back_to_template(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = load_config(ROOT / "config.yaml")
    cfg["ai_summary"]["enabled"] = True            # enabled but no key -> template, same numbers
    d = run_cli(tmp_path, "--auto-approve-rules-only")
    before = (d / "purchase_orders_zoho_import.csv").read_text()
    res = outputs.finalize_run(d, cfg)
    assert "SKUs processed" in res["summary"]
    assert (d / "purchase_orders_zoho_import.csv").read_text() == before


def test_zoho_seed_files_match_the_seed_data(data_dir, cfg):
    from planner import zoho_files
    f = zoho_files.build(data_dir, cfg)
    v, i = f["vendors.csv"], f["items.csv"]
    assert list(v["Display Name"]) == ["NutriFlow Distributors", "GrainPath Logistics", "PeakSource Supply", "Meridian Trade Co."]
    assert len(i) == 15 and i["SKU"].is_unique and set(i["Item Type"]) == {"Inventory"}
    assert i.set_index("SKU").loc["SKU001", "Opening Stock"] == 900 and i.set_index("SKU").loc["SKU001", "Preferred Vendor"] == "NutriFlow Distributors"
    assert (i["Purchase Rate"] == "").all() and (i["Opening Stock Value"] == "").all()      # no prices in the data, so none invented
    assert set(i["Preferred Vendor"]) <= set(v["Display Name"])
