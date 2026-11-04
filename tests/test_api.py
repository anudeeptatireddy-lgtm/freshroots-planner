"""The web API over the planner engine, on local files (no database)."""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import _core  # noqa: E402


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(_core, "OUT_LOCAL", tmp_path)
    monkeypatch.setattr(_core, "get_store", lambda: None)
    return lambda method, op, q=None, body=None: (lambda r: (r[0], json.loads(r[2]) if r[1] == "application/json" else r[2]))(_core.dispatch(method, op, q or {}, body or {}))


def test_plan_decide_generate_reproduces_acceptance(api):
    status, run = api("POST", "plan")
    assert status == 200 and run["pending"] == ["SKU001", "SKU003", "SKU007", "SKU013"]
    changes = [{"sku": s, "action": "approve"} for s in run["pending"]]
    assert api("POST", "decide", body={"run": run["id"], "reviewer": "", "changes": changes})[0] == 400
    assert api("POST", "decide", body={"run": run["id"], "reviewer": "system:auto", "changes": changes})[0] == 400
    assert api("POST", "decide", body={"run": run["id"], "reviewer": "Ravi", "changes": changes})[1]["pending"] == []
    status, done = api("POST", "generate", body={"run": run["id"], "reviewer": "Ravi"})
    final = {line["sku"]: line["final"] for o in done["orders"] for line in o["lines"]}
    assert status == 200 and final == {"SKU001": 750, "SKU003": 300, "SKU004": 150, "SKU011": 500, "SKU013": 120}


def test_files_and_errors_are_contained(api):
    _, run = api("POST", "plan")
    assert api("GET", "file", {"run": run["id"], "name": "../config.yaml"})[0] == 400
    assert api("GET", "run", {"id": "../../etc"})[0] == 400
    assert api("GET", "nope")[0] == 404
    bad = base64.b64encode(b"x").decode()
    assert api("POST", "plan", body={"files": {"weekly_sales.csv": bad}})[0] == 400
    assert api("POST", "zoho", body={"run": run["id"], "mode": "send", "confirm": True})[0] == 400
