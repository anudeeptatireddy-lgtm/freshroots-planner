"""Postgres (Neon) persistence for runs, decisions and PO files.

The pipeline still works on a run folder of files. The store mirrors a finished or changed run folder into
Postgres (`save_run`) and rebuilds run folders from Postgres (`materialize`), so nothing is lost when a hosted
disk is wiped. Decisions live in the `decisions` table (append-only history; the last row per SKU stands).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd
import psycopg

from planner import review
from planner.common import PlannerError

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS {s};
CREATE TABLE IF NOT EXISTS {s}.runs (
    run_id text PRIMARY KEY,
    run_date date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    run_log jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS {s}.run_files (
    run_id text NOT NULL REFERENCES {s}.runs(run_id) ON DELETE CASCADE,
    name text NOT NULL,
    content bytea NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, name)
);
CREATE TABLE IF NOT EXISTS {s}.planning_lines (
    run_id text NOT NULL REFERENCES {s}.runs(run_id) ON DELETE CASCADE,
    sku_id text NOT NULL,
    status text NOT NULL,
    flag text,
    order_qty numeric,
    exceptions text,
    data jsonb NOT NULL,
    PRIMARY KEY (run_id, sku_id)
);
CREATE TABLE IF NOT EXISTS {s}.data_issues (
    id bigserial PRIMARY KEY,
    run_id text NOT NULL REFERENCES {s}.runs(run_id) ON DELETE CASCADE,
    file text, row_ref text, sku_id text, issue text, action text, severity text
);
CREATE TABLE IF NOT EXISTS {s}.decisions (
    id bigserial PRIMARY KEY,
    run_id text NOT NULL REFERENCES {s}.runs(run_id) ON DELETE CASCADE,
    sku_id text NOT NULL,
    system_qty numeric NOT NULL,
    final_qty numeric NOT NULL,
    decision text NOT NULL CHECK (decision IN ('approve', 'edit', 'reject')),
    reviewer text NOT NULL,
    note text NOT NULL DEFAULT '',
    decided_at text NOT NULL
);
CREATE INDEX IF NOT EXISTS decisions_run_sku ON {s}.decisions (run_id, sku_id);
CREATE TABLE IF NOT EXISTS {s}.purchase_order_lines (
    id bigserial PRIMARY KEY,
    run_id text NOT NULL REFERENCES {s}.runs(run_id) ON DELETE CASCADE,
    po_number text NOT NULL,
    vendor_id text, vendor_name text, sku_id text, item_name text,
    quantity integer, unit text, unit_price numeric, notes text
);
"""


def dsn_from_env() -> str | None:
    return os.environ.get("DATABASE_URL") or None


class Store:
    def __init__(self, dsn: str, schema: str = "public"):
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
            raise ValueError(f"Invalid schema name: {schema!r}")
        self.dsn, self.s = dsn, schema

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn, connect_timeout=15)

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(SCHEMA_SQL.format(s=self.s))

    def list_runs(self, limit: int | None = None) -> list[str]:
        """Run ids, newest first."""
        sql = f"SELECT run_id FROM {self.s}.runs ORDER BY run_date DESC, created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql + (" LIMIT %s" if limit else ""), (limit,) if limit else ()).fetchall()
        return [r[0] for r in rows]

    # ---- write ---------------------------------------------------------------------------
    def save_run(self, run_dir: str | Path, cfg: dict) -> None:
        """Mirror a run folder into Postgres (replaces what was stored for this run)."""
        run_dir = Path(run_dir)
        run_log_path = run_dir / "run_log.json"
        if not run_log_path.exists():
            raise PlannerError(f"{run_log_path} not found")
        run_log = json.loads(run_log_path.read_text())
        run_id, s = run_dir.name, self.s
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {s}.runs (run_id, run_date, run_log) VALUES (%s, %s, %s) "
                f"ON CONFLICT (run_id) DO UPDATE SET run_log = EXCLUDED.run_log, updated_at = now()",
                (run_id, run_log["run_date"], json.dumps(run_log)))
            cur.executemany(
                f"INSERT INTO {s}.run_files (run_id, name, content) VALUES (%s, %s, %s) "
                f"ON CONFLICT (run_id, name) DO UPDATE SET content = EXCLUDED.content, updated_at = now()",
                [(run_id, p.name, p.read_bytes()) for p in sorted(run_dir.iterdir()) if p.is_file() and not p.name.startswith(".")])
            self._replace_planning_lines(cur, run_id, run_dir)
            self._replace_issues(cur, run_id, run_dir)
            self._replace_decisions(cur, run_id, run_dir)
            self._replace_po_lines(cur, run_id, run_dir, cfg)

    def save_decisions(self, run_dir: str | Path) -> None:
        """Mirror only review_log.csv into the decisions table (what every Approve / Reject tap needs)."""
        run_dir = Path(run_dir)
        with self._connect() as conn, conn.cursor() as cur:
            self._replace_decisions(cur, run_dir.name, run_dir)

    def _replace_planning_lines(self, cur, run_id: str, run_dir: Path) -> None:
        path = run_dir / "planning_table.csv"
        cur.execute(f"DELETE FROM {self.s}.planning_lines WHERE run_id = %s", (run_id,))
        if not path.exists():
            return
        df = pd.read_csv(path)
        records = json.loads(df.to_json(orient="records"))      # NaN -> null
        cur.executemany(
            f"INSERT INTO {self.s}.planning_lines (run_id, sku_id, status, flag, order_qty, exceptions, data) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            [(run_id, r["sku_id"], r["status"], r.get("flag"), r.get("order_qty"), r.get("exceptions") or "", json.dumps(r)) for r in records])

    def _replace_issues(self, cur, run_id: str, run_dir: Path) -> None:
        path = run_dir / "data_quality_report.csv"
        cur.execute(f"DELETE FROM {self.s}.data_issues WHERE run_id = %s", (run_id,))
        if not path.exists():
            return
        df = pd.read_csv(path, keep_default_na=False, dtype=str)
        cur.executemany(
            f"INSERT INTO {self.s}.data_issues (run_id, file, row_ref, sku_id, issue, action, severity) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            [(run_id, r.file, r.row_ref, r.sku_id, r.issue, r.action, r.severity) for r in df.itertuples()])

    def _replace_decisions(self, cur, run_id: str, run_dir: Path) -> None:
        log = review.read_log(run_dir / "review_log.csv")
        cur.execute(f"DELETE FROM {self.s}.decisions WHERE run_id = %s", (run_id,))
        cur.executemany(
            f"INSERT INTO {self.s}.decisions (run_id, sku_id, system_qty, final_qty, decision, reviewer, note, decided_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            [(run_id, r.sku_id, r.system_qty, r.final_qty, r.decision, r.reviewer, r.note, str(r.timestamp)) for r in log.itertuples()])

    def _replace_po_lines(self, cur, run_id: str, run_dir: Path, cfg: dict) -> None:
        cur.execute(f"DELETE FROM {self.s}.purchase_order_lines WHERE run_id = %s", (run_id,))
        path = run_dir / "purchase_orders_zoho_import.csv"
        if not path.exists():
            return
        zc = cfg["po"]["zoho_columns"]
        df = pd.read_csv(path, keep_default_na=False, dtype=str)
        cur.executemany(
            f"INSERT INTO {self.s}.purchase_order_lines (run_id, po_number, vendor_id, vendor_name, sku_id, item_name, quantity, unit, unit_price, notes) "
            f"VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(run_id, r[zc["po_number"]], r[zc["vendor_id"]], r[zc["vendor_name"]], r[zc["sku"]], r[zc["item_name"]],
              int(r[zc["quantity"]]), r[zc["unit"]], (r[zc["unit_price"]] or None), r[zc["notes"]]) for _, r in df.iterrows()])

    # ---- read ----------------------------------------------------------------------------
    def materialize(self, run_ids: list[str], dest_base: str | Path) -> None:
        """Rebuild run folders (files + review_log.csv from the decisions table) under dest_base."""
        if not run_ids:
            return
        dest_base, s = Path(dest_base), self.s
        with self._connect() as conn:
            files = conn.execute(f"SELECT run_id, name, content FROM {s}.run_files WHERE run_id = ANY(%s)", (run_ids,)).fetchall()
            decisions = conn.execute(
                f"SELECT run_id, sku_id, system_qty, final_qty, decision, reviewer, note, decided_at FROM {s}.decisions "
                f"WHERE run_id = ANY(%s) ORDER BY id", (run_ids,)).fetchall()
        for run_id in run_ids:
            (dest_base / run_id).mkdir(parents=True, exist_ok=True)
        for run_id, name, content in files:
            (dest_base / run_id / name).write_bytes(bytes(content))
        for run_id in run_ids:
            rows = [(sku, float(sq), float(fq), dec, who, note, at) for rid, sku, sq, fq, dec, who, note, at in decisions if rid == run_id]
            log = dest_base / run_id / "review_log.csv"
            if rows:
                pd.DataFrame(rows, columns=review.LOG_COLUMNS).to_csv(log, index=False)
            elif log.exists():
                log.unlink()

    def reserve(self, run_ids: list[str], dest_base: str | Path) -> None:
        """Create empty folders for older runs so a new run never reuses an existing run id."""
        for run_id in run_ids:
            (Path(dest_base) / run_id).mkdir(parents=True, exist_ok=True)
