"""The web API over the planner engine, on local files (no database)."""
import base64
import json
import os
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
    for bad in ("..", ".", "2026-10-19/..", "2026-10-19_r2/../x", ""):
        assert api("GET", "run", {"id": bad})[0] == 400
        assert api("POST", "decide", body={"run": bad, "reviewer": "T", "changes": [], "bundle": {"planning_table.csv": "AA=="}})[0] == 400
    assert api("GET", "nope")[0] == 404
    bad = base64.b64encode(b"x").decode()
    assert api("POST", "plan", body={"files": {"weekly_sales.csv": bad}})[0] == 400
    assert api("POST", "zoho", body={"run": run["id"], "mode": "send", "confirm": True})[0] == 400


def test_upload_replaces_a_bundled_file(api):
    cal = base64.b64encode((Path(__file__).resolve().parent.parent / "data" / "raw" / "calendar.csv").read_bytes()).decode()
    status, run = api("POST", "plan", body={"files": {"calendar.csv": cal}})
    assert status == 200 and run["counts"] == {"skus": 15, "review": 4, "auto": 2}
    assert api("POST", "plan", body={"files": {"calendar.csv": cal}})[1]["id"].endswith("_r2")     # a re-run never reuses an id


def test_no_database_run_survives_a_fresh_server_instance(api, tmp_path, monkeypatch):
    """Serverless without a database: any call may land on an instance that never saw the run. The browser's bundle rebuilds it."""
    import shutil
    _, run = api("POST", "plan")
    bundle = run["bundle"]
    assert bundle and "planning_table.csv" in bundle and "review_log.csv" not in bundle

    def fresh_instance():
        shutil.rmtree(tmp_path / run["id"], ignore_errors=True)

    changes = [{"sku": s, "action": "approve"} for s in run["pending"]]
    fresh_instance()
    assert api("POST", "decide", body={"run": run["id"], "reviewer": "T", "changes": changes})[0] == 400      # no bundle: honest error
    status, decided = api("POST", "decide", body={"run": run["id"], "reviewer": "T", "changes": changes, "bundle": bundle})
    assert status == 200 and decided["pending"] == [] and "review_log.csv" in decided["bundle"]
    fresh_instance()
    status, done = api("POST", "generate", body={"run": run["id"], "reviewer": "T", "bundle": decided["bundle"]})
    assert status == 200 and done["po_ready"] and any(n.startswith("PO_") for n in done["bundle"])
    # a client-built run can never reach Zoho for real, even with credentials and live sending switched on
    for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_DC", "ZOHO_ORG_ID"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setitem(_core.CFG["zoho"], "dry_run_only", False)
    assert api("POST", "zoho", body={"run": run["id"], "mode": "send", "confirm": True, "bundle": done["bundle"]})[0] == 400
    assert api("POST", "zoho", body={"run": run["id"], "mode": "preview", "bundle": done["bundle"]})[1]["zoho"]["live"] is False
    fresh_instance()
    status, prev = api("POST", "zoho", body={"run": run["id"], "mode": "preview", "bundle": done["bundle"]})
    assert status == 200 and prev["zoho"]["preview"]
    assert api("POST", "decide", body={"run": run["id"], "reviewer": "T", "changes": [], "bundle": {"../x.csv": "AA=="}})[0] == 400  # unsafe names ignored


def test_serverless_without_database_lists_no_runs(api, monkeypatch):
    monkeypatch.setattr(_core, "OUT_LOCAL", _core.TMP_BASE)
    assert api("GET", "runs")[1]["runs"] == []


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL (Neon tests branch)")
def test_database_mode_survives_cold_starts(monkeypatch, tmp_path):
    """Serverless instances start with an empty disk: everything must come back from Postgres."""
    import shutil
    import uuid

    import psycopg
    schema = "t_" + uuid.uuid4().hex[:8]
    monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    monkeypatch.setenv("FRESHROOTS_DB_SCHEMA", schema)
    monkeypatch.delenv("FRESHROOTS_DISABLE_DB", raising=False)
    monkeypatch.setattr(_core, "_store", None)
    monkeypatch.setattr(_core, "TMP_BASE", tmp_path / "fr")
    call = lambda m, op, q=None, b=None: (lambda r: (r[0], json.loads(r[2]) if r[1] == "application/json" else r[2]))(_core.dispatch(m, op, q or {}, b or {}))  # noqa: E731
    try:
        _, run = call("POST", "plan")
        shutil.rmtree(_core.TMP_BASE, ignore_errors=True)
        assert call("GET", "runs")[1] == {"runs": [run["id"]], "db": True}
        shutil.rmtree(_core.TMP_BASE, ignore_errors=True)
        call("POST", "decide", b={"run": run["id"], "reviewer": "T", "changes": [{"sku": s, "action": "approve"} for s in run["pending"]]})
        shutil.rmtree(_core.TMP_BASE, ignore_errors=True)
        _, done = call("POST", "generate", b={"run": run["id"], "reviewer": "T"})
        shutil.rmtree(_core.TMP_BASE, ignore_errors=True)
        status, pdf = call("GET", "file", {"run": run["id"], "name": done["orders"][0]["pdf"]})
        assert done["po_ready"] and status == 200 and pdf[:4] == b"%PDF"
    finally:
        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as c:
            c.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
