"""Vercel entry point: mobile review page + JSON API around the planner.

Stateless on purpose (Vercel has no writable disk): each request re-runs the pipeline on the bundled
data/raw files. Review decisions live in the phone's browser until "Generate" is pressed; the server then
builds the POs from them and returns the files, including review_log.csv, to download.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from flask import Flask, Response, jsonify, request  # noqa: E402

from planner import outputs, review  # noqa: E402
from planner.common import PlannerError, load_config  # noqa: E402
from planner.pipeline import run_pipeline  # noqa: E402

app = Flask(__name__)
CFG = load_config(ROOT / "config.yaml")
DATA = ROOT / "data" / "raw"
MIME = {".csv": "text/csv", ".md": "text/markdown", ".pdf": "application/pdf", ".json": "application/json"}


def _plan(tmp: Path):
    result = run_pipeline(DATA, None, CFG)
    run_dir = outputs.write_run(result, CFG, tmp)
    return result, run_dir, outputs.load_planning_table(run_dir)


@app.get("/")
def index():
    return Response((ROOT / "web" / "index.html").read_text(encoding="utf-8"), mimetype="text/html")


@app.get("/api/plan")
def plan():
    with tempfile.TemporaryDirectory() as tmp:
        result, run_dir, table = _plan(Path(tmp))
        log = json.loads((run_dir / "run_log.json").read_text())
    rows = json.loads(table.to_json(orient="records"))
    return jsonify({"run_date": str(result.run_date), "rows": rows, "flag_counts": log["flag_counts"],
                    "exception_counts": log["exception_counts"], "data_issues": log["data_issues"],
                    "notes": result.notes, "counterparty_label": CFG["po"]["counterparty_label"]})


@app.post("/api/generate")
def generate():
    body = request.get_json(force=True, silent=True) or {}
    reviewer = str(body.get("reviewer", "")).strip()
    posted = body.get("decisions", {})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result, run_dir, table = _plan(Path(tmp))
            rows, by_sku = [], table.set_index("sku_id")
            for sku, d in posted.items():
                if sku not in by_sku.index:
                    raise PlannerError(f"Unknown SKU in decisions: {sku}")
                rows.append(review.make_decision(sku, float(by_sku.loc[sku, "order_qty"]), d.get("decision", ""), reviewer,
                                                 final_qty=d.get("qty"), note=str(d.get("note", "")), timestamp=d.get("ts")))
            decided = {r["sku_id"] for r in rows}
            for r in table[(table.status == "AUTO_APPROVED") & (~table.sku_id.isin(decided))].itertuples():
                rows.append(review.make_decision(r.sku_id, r.order_qty, "approve", review.AUTO_REVIEWER))
            review.append_log(run_dir / "review_log.csv", rows)
            res = outputs.finalize_run(run_dir, CFG)
            files = {}
            for p in sorted(run_dir.iterdir()):
                if p.suffix in MIME:
                    files[p.name] = {"mime": MIME[p.suffix], "b64": base64.b64encode(p.read_bytes()).decode()}
            lines = json.loads(res["lines"].drop(columns="is_urgent").to_json(orient="records"))
            return jsonify({"po_count": int(res["lines"].po_number.nunique()) if not res["lines"].empty else 0, "lines": lines,
                            "held": res["held"][["sku_id", "sku_name", "order_qty", "held_reason"]].to_dict("records"),
                            "stats": res["stats"], "summary": res["summary"], "files": files})
    except PlannerError as e:
        return jsonify({"error": str(e)}), 400
