"""The web API: plain functions over the planner engine. `dispatch` is shared by the Vercel handler and the local dev server."""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from planner import outputs, review, zoho  # noqa: E402
from planner.common import STATUS_AUTO, STATUS_REVIEW, PlannerError, load_config  # noqa: E402
from planner.store import Store  # noqa: E402

CFG = load_config(ROOT / "config.yaml")
DATA_DIR = ROOT / "data" / "raw"
TMP_BASE = Path(tempfile.gettempdir()) / "fr_runs"
OUT_LOCAL = Path(os.environ.get("FRESHROOTS_OUTPUTS") or (ROOT / "outputs" if os.access(ROOT, os.W_OK) else TMP_BASE))   # serverless disks are read-only
RUN_ID = re.compile(r"^[\w.-]+$")
FILE_TYPES = {".pdf": "application/pdf", ".csv": "text/csv", ".md": "text/markdown", ".json": "application/json"}
COLS = ["sku_id", "sku_name", "category", "perishability", "distributor_id", "distributor_name", "standard_reorder_qty", "unit", "unit_price",
        "units_on_hand", "avg_weekly_12w", "avg_weekly_4w", "change_4w_vs_12w", "is_festival", "uplift", "adjusted_weekly_demand", "weeks_of_cover",
        "min_weeks", "max_weeks", "flag", "flag_reasons", "action", "order_qty", "is_urgent", "weeks_of_cover_after_order", "forecast_total_4w",
        "exceptions", "exception_reasons", "suggested_qty", "suggested_note", "status"]
_store: Store | None = None


def get_store() -> Store | None:
    """Neon when DATABASE_URL is set, else None (local files in outputs/)."""
    global _store
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn or os.environ.get("FRESHROOTS_DISABLE_DB"):
        return None
    if _store is None:
        _store = Store(dsn, os.environ.get("FRESHROOTS_DB_SCHEMA", "public"))
        _store.ensure_schema()
    return _store


def base_dir() -> Path:
    return TMP_BASE if get_store() else OUT_LOCAL


def run_ids() -> list[str]:
    store = get_store()
    if store:
        return store.list_runs()
    return sorted((p.name for p in OUT_LOCAL.glob("*") if (p / "planning_table.csv").exists()), reverse=True)


def open_run(run_id: str) -> Path:
    if not RUN_ID.match(run_id or ""):
        raise PlannerError("Unknown run")
    store, base = get_store(), base_dir()
    if store:
        store.materialize([run_id], base)
    run_dir = base / run_id
    if not (run_dir / "planning_table.csv").exists():
        raise PlannerError("Unknown run")
    return run_dir


def save(run_dir: Path, decisions_only: bool = False) -> None:
    store = get_store()
    if store:
        store.save_decisions(run_dir) if decisions_only else store.save_run(run_dir, CFG)


def zoho_state(run_dir: Path) -> dict:
    csv = run_dir / "purchase_orders_zoho_import.csv"
    if not csv.exists():
        return {}
    settings = zoho.settings_from({k: os.environ.get(k, "") for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_DC", "ZOHO_ORG_ID")})
    live = settings is not None and not CFG.get("zoho", {}).get("dry_run_only", True)
    read = lambda name: json.loads((run_dir / name).read_text()) if (run_dir / name).exists() else None  # noqa: E731
    sent = read(zoho.SENT_FILE) or {}
    drafts = zoho.build_drafts(csv, CFG)
    return {"live": live, "preview": read(zoho.PREVIEW_FILE), "sent": sent, "todo": [d["po_number"] for d in drafts if d["po_number"] not in sent]}


def orders(run_dir: Path, table, decisions) -> list[dict]:
    csv = run_dir / "purchase_orders_zoho_import.csv"
    if not csv.exists():
        return []
    import pandas as pd
    zc = CFG["po"]["zoho_columns"]
    z = pd.read_csv(csv)
    by_sku = table.set_index("sku_id")
    src = {r.sku_id: "Auto" if str(r.reviewer).startswith("system:") else ("Changed" if r.decision == "edit" else "Approved") for r in decisions.itertuples()}
    out = []
    for po, g in z.groupby(zc["po_number"], sort=True):
        out.append({"po": po, "vendor": g[zc["vendor_name"]].iloc[0], "units": int(g[zc["quantity"]].sum()), "pdf": f"PO_{po}.pdf",
                    "lines": [{"sku": r[zc["sku"]], "name": r[zc["item_name"]], "final": int(r[zc["quantity"]]), "system": int(by_sku.loc[r[zc["sku"]], "order_qty"]),
                               "source": src.get(r[zc["sku"]], "Auto")} for _, r in g.iterrows()]})
    return out


def run_payload(run_dir: Path) -> dict:
    table = outputs.load_planning_table(run_dir)
    dec = review.latest_decisions(review.read_log(run_dir / "review_log.csv"))
    pending = review.pending_review(table, dec)
    run_log = json.loads((run_dir / "run_log.json").read_text())
    return {
        "id": run_dir.name, "run_date": run_log.get("run_date"), "festival": bool(table.is_festival.iloc[0]), "uplift": float(table.uplift.iloc[0]),
        "rows": json.loads(table[COLS].to_json(orient="records")),
        "decisions": json.loads(dec.to_json(orient="records")) if not dec.empty else [],
        "pending": pending, "counts": {"skus": len(table), "review": int((table.status == STATUS_REVIEW).sum()), "auto": int((table.status == STATUS_AUTO).sum())},
        "po_ready": (run_dir / "sourcing_handoff.md").exists(), "run_log": run_log, "orders": orders(run_dir, table, dec), "zoho": zoho_state(run_dir),
        "files": sorted(p.name for p in run_dir.iterdir() if p.is_file()), "stats": review.override_stats(dec)}


def decide(body: dict) -> dict:
    run_dir = open_run(body.get("run", ""))
    if str(body.get("reviewer", "")).strip().lower().startswith(review.SYSTEM_PREFIX):
        raise PlannerError(f"A reviewer name cannot start with '{review.SYSTEM_PREFIX}': that prefix is reserved for automatic approvals.")
    table = outputs.load_planning_table(run_dir).set_index("sku_id")
    rows = []
    for c in body.get("changes", []):
        if c["sku"] not in table.index:
            raise PlannerError(f"Unknown SKU {c['sku']}")
        qty = c.get("qty")
        rows.append(review.make_decision(c["sku"], float(table.loc[c["sku"], "order_qty"]), c["action"], body.get("reviewer", ""),
                                         final_qty=None if qty is None else float(qty), note=c.get("note", "")))
    review.append_log(run_dir / "review_log.csv", rows)
    save(run_dir, decisions_only=True)
    return run_payload(run_dir)


def plan(body: dict) -> dict:
    store, base = get_store(), base_dir()
    base.mkdir(parents=True, exist_ok=True)
    if store:
        store.reserve(store.list_runs(), base)       # a new run never reuses an id
    files = {name: base64.b64decode(b64) for name, b64 in (body.get("files") or {}).items() if re.match(r"^[\w .()-]+\.csv$", name)}
    new_dir = outputs.plan_with_overrides(DATA_DIR, files, CFG, base)
    save(new_dir)
    return run_payload(new_dir)


def generate(body: dict) -> dict:
    run_dir = open_run(body.get("run", ""))
    if not str(body.get("reviewer", "")).strip() or str(body["reviewer"]).strip().lower().startswith(review.SYSTEM_PREFIX):
        raise PlannerError("Type your name first, so the log shows who approved.")
    outputs.generate_pos(run_dir, CFG)
    save(run_dir)
    return run_payload(run_dir)


def zoho_action(body: dict) -> dict:
    run_dir = open_run(body.get("run", ""))
    csv = run_dir / "purchase_orders_zoho_import.csv"
    if not csv.exists():
        raise PlannerError("Generate the purchase orders first.")
    drafts = zoho.build_drafts(csv, CFG)
    if body.get("mode") == "preview":
        zoho.write_preview(run_dir, zoho.send(drafts, dry_run=True), zoho.check_drafts(drafts))
    else:
        state = zoho_state(run_dir)
        if not state["live"] or not body.get("confirm"):
            raise PlannerError("Sending is locked: Zoho credentials missing, live sending off, or not confirmed.")
        todo = [d for d in drafts if d["po_number"] in state["todo"]]
        settings = zoho.settings_from({k: os.environ.get(k, "") for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_DC", "ZOHO_ORG_ID")})
        zoho.record_sent(run_dir / zoho.SENT_FILE, zoho.send(todo, dry_run=False, client=zoho.ZohoClient(settings)))
    save(run_dir)
    return run_payload(run_dir)


def dispatch(method: str, op: str, q: dict, body: dict) -> tuple[int, str, bytes]:
    """(status, content-type, bytes). Errors the user can act on come back as 400 {error}."""
    try:
        if method == "GET" and op == "runs":
            out = {"runs": run_ids(), "db": get_store() is not None}
        elif method == "GET" and op == "run":
            out = run_payload(open_run(q.get("id", "")))
        elif method == "GET" and op == "file":
            run_dir, name = open_run(q.get("run", "")), q.get("name", "")
            path = run_dir / name
            if not RUN_ID.match(name) or not path.is_file():
                raise PlannerError("No such file")
            return 200, FILE_TYPES.get(path.suffix, "application/octet-stream"), path.read_bytes()
        elif method == "POST" and op in ("decide", "plan", "generate", "zoho"):
            out = {"decide": decide, "plan": plan, "generate": generate, "zoho": zoho_action}[op](body)
        else:
            return 404, "application/json", b'{"error":"Not found"}'
        return 200, "application/json", json.dumps(out, default=str).encode()
    except PlannerError as e:
        return 400, "application/json", json.dumps({"error": str(e)}).encode()
    except Exception as e:      # never leak internals (connection strings etc.) to the browser
        print(f"api error {op}: {type(e).__name__}: {e}", file=sys.stderr)
        return 500, "application/json", json.dumps({"error": f"Server error ({type(e).__name__})"}).encode()
