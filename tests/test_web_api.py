import base64
import importlib.util

import pandas as pd
import pytest

from tests.conftest import ROOT


@pytest.fixture()
def client():
    spec = importlib.util.spec_from_file_location("web_index", ROOT / "api" / "index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app.test_client()


def test_page_and_plan(client):
    assert b"Freshroots review" in client.get("/").data
    j = client.get("/api/plan").get_json()
    assert j["run_date"] == "2026-10-19" and len(j["rows"]) == 15
    assert sorted(r["sku_id"] for r in j["rows"] if r["status"] == "AUTO_APPROVED") == ["SKU004", "SKU011"]


def test_generate_blocked_then_allowed(client):
    r = client.post("/api/generate", json={"reviewer": "Raghav", "decisions": {}})
    assert r.status_code == 400 and "still need a decision" in r.get_json()["error"]
    r = client.post("/api/generate", json={"reviewer": "", "decisions": {}})
    assert r.status_code == 400

    dec = {"SKU001": {"decision": "approve"}, "SKU007": {"decision": "approve"}, "SKU013": {"decision": "reject", "note": "short supply"},
           "SKU003": {"decision": "edit", "qty": 309, "note": "top up"}}
    r = client.post("/api/generate", json={"reviewer": "Raghav", "decisions": dec})
    assert r.status_code == 200
    j = r.get_json()
    got = {(l["vendor_id"], l["sku_id"]): l["quantity"] for l in j["lines"]}
    assert got == {("DIST001", "SKU001"): 750, ("DIST002", "SKU003"): 309, ("DIST002", "SKU004"): 150, ("DIST004", "SKU011"): 500}
    assert {"purchase_orders_zoho_import.csv", "sourcing_handoff.md", "review_log.csv", "run_log.json"} <= set(j["files"])
    assert any(n.endswith(".pdf") for n in j["files"])
    log = base64.b64decode(j["files"]["review_log.csv"]["b64"]).decode()
    assert "Raghav" in log and "short supply" in log
    assert j["stats"]["overrides"] == 2
