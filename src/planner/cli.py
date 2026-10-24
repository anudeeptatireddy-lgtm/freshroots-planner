"""Command line: `python -m planner run ...` and `python -m planner generate-pos ...`."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from planner import outputs, review
from planner.common import PlannerError, load_config
from planner.pipeline import run_pipeline
from planner.store import Store, dsn_from_env


def _save_to_database(run_dir, cfg) -> None:
    """If DATABASE_URL is set (e.g. in the twice-weekly scheduled run), mirror the run into Postgres."""
    dsn = dsn_from_env()
    if not dsn:
        return
    store = Store(dsn)
    store.ensure_schema()
    store.save_run(run_dir, cfg)
    print(f"  saved to database as run {run_dir.name}")


def _cmd_run(args) -> int:
    cfg = load_config(args.config)
    run_date = dt.date.fromisoformat(args.run_date) if args.run_date else None
    result = run_pipeline(args.data, run_date, cfg)
    run_dir = outputs.write_run(result, cfg, args.outputs)
    t = result.table
    print(f"Run date {result.run_date}: {len(t)} SKUs -> {run_dir}")
    for n in result.notes:
        print(f"  note: {n}")
    print(f"  data issues: {len(result.issues)} ({int((result.issues.severity == 'review').sum())} need review)")
    print("  status: " + ", ".join(f"{k}={v}" for k, v in t.status.value_counts().sort_index().items()))
    if args.auto_approve_rules_only:
        log_path = run_dir / "review_log.csv"
        review.append_log(log_path, review.auto_decisions(outputs.load_planning_table(run_dir)))
        rl = json.loads((run_dir / "run_log.json").read_text())
        rl["auto_mode"] = True            # exceptions are deliberately left out of the PO
        (run_dir / "run_log.json").write_text(json.dumps(rl, indent=2))
        res = outputs.finalize_run(run_dir, cfg)
        print(f"  auto-approved lines only: {res['lines'].po_number.nunique() if not res['lines'].empty else 0} PO(s); "
              f"{len(res['held'])} line(s) held for review")
    else:
        print("  next: streamlit run app/review_app.py   (review exceptions, then generate POs)")
    _save_to_database(run_dir, cfg)
    return 0


def _cmd_generate(args) -> int:
    cfg = load_config(args.config)
    res = outputs.finalize_run(args.run_dir, cfg)
    print(f"{res['lines'].po_number.nunique() if not res['lines'].empty else 0} PO(s) written to {args.run_dir}")
    _save_to_database(Path(args.run_dir), cfg)
    return 0


def _cmd_db_seed(args) -> int:
    dsn = dsn_from_env()
    if not dsn:
        raise PlannerError("DATABASE_URL is not set")
    cfg = load_config(args.config)
    store = Store(dsn)
    store.ensure_schema()
    for table, n in store.seed_reference_data(args.data, cfg).items():
        print(f"  {table}: {n} rows")
    return 0


def _cmd_zoho_files(args) -> int:
    from planner import zoho_files
    for p in zoho_files.write(args.data, load_config(args.config), args.out):
        print(f"  wrote {p}")
    return 0


def _cmd_zoho_token(args) -> int:
    import tomllib

    from planner import zoho
    secrets = Path(args.secrets)
    values = tomllib.loads(secrets.read_text()) if secrets.exists() else {}
    token = zoho.exchange_code(values, args.code)
    zoho.save_secret(secrets, "ZOHO_REFRESH_TOKEN", token)
    print(f"  refresh token saved to {secrets} (not shown). Add the same ZOHO_REFRESH_TOKEN line to the Streamlit Secrets panel.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="planner", description="Freshroots demand planning and PO automation")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Run stages 1-6 and write outputs")
    r.add_argument("--data", default="data/raw")
    r.add_argument("--run-date", default=None, help="YYYY-MM-DD; defaults to the inventory As_Of_Date")
    r.add_argument("--config", default="config.yaml")
    r.add_argument("--outputs", default="outputs")
    r.add_argument("--auto-approve-rules-only", action="store_true",
                   help="Approve only AUTO_APPROVED lines; exceptions are left out of the PO")
    r.set_defaults(fn=_cmd_run)
    g = sub.add_parser("generate-pos", help="Generate POs from a run folder's review_log.csv")
    g.add_argument("--run-dir", required=True)
    g.add_argument("--config", default="config.yaml")
    g.set_defaults(fn=_cmd_generate)
    d = sub.add_parser("db-seed", help="Load the input CSVs (master data, sales, stock, calendar) into the database")
    d.add_argument("--data", default="data/raw")
    d.add_argument("--config", default="config.yaml")
    d.set_defaults(fn=_cmd_db_seed)
    z = sub.add_parser("zoho-files", help="Write Zoho Inventory import files (vendors.csv, items.csv) from the seed data")
    z.add_argument("--data", default="data/raw")
    z.add_argument("--config", default="config.yaml")
    z.add_argument("--out", default="data/zoho_seed")
    z.set_defaults(fn=_cmd_zoho_files)
    k = sub.add_parser("zoho-token", help="Exchange a Zoho Self Client one-time code for a refresh token and save it to the secrets file")
    k.add_argument("--code", required=True)
    k.add_argument("--secrets", default=".streamlit/secrets.toml")
    k.set_defaults(fn=_cmd_zoho_token)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except PlannerError as e:
        print(f"ERROR: {e}")
        return 2
