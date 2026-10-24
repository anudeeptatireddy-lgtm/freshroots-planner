"""Where the app keeps its runs: Postgres (Neon) when a database URL exists, else local files. Also run listing, saving and starting runs."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import streamlit as st
from secrets_util import secret

from planner import outputs
from planner.common import PlannerError
from planner.store import Store

RECENT_RUNS = 8     # newest runs rebuilt from the database on each page load; older ids are only reserved


def get_dsn() -> str | None:
    """Database URL (env, then Streamlit secrets). FRESHROOTS_DISABLE_DB forces files-only."""
    return secret("DATABASE_URL") or None


@st.cache_resource
def get_store(dsn: str, schema: str) -> Store:
    store = Store(dsn, schema)
    store.ensure_schema()
    return store


@dataclass
class Workspace:
    cfg: dict
    data_dir: Path
    out_base: Path
    store: Store | None
    db_note: str

    def list_runs(self) -> list[Path]:
        if not self.out_base.exists():
            return []
        return sorted((p for p in self.out_base.glob("*") if (p / "planning_table.csv").exists()), reverse=True)

    def sync_up(self, run_dir: Path, decisions_only: bool = False) -> None:
        """Mirror a changed run folder to Postgres (no-op without a database)."""
        if not self.store:
            return
        try:
            self.store.save_decisions(run_dir) if decisions_only else self.store.save_run(run_dir, self.cfg)
        except Exception as exc:
            st.error(f"Could not save to the database ({type(exc).__name__}). Your change is only on this server.")

    def start_run(self, ups) -> None:
        """Plan again (on the bundled files, with any uploaded CSVs replacing them), save it, and rerun the page."""
        try:
            new_dir = outputs.plan_with_overrides(self.data_dir, {u.name: u.getvalue() for u in ups or []}, self.cfg, self.out_base)
            self.sync_up(new_dir)
        except PlannerError as e:
            st.error(str(e))
            return
        st.rerun()


def open_workspace(cfg: dict, data_dir: Path, default_out: Path) -> Workspace:
    out_base, store, note = default_out, None, "Local files only. Nothing is saved to a database."
    dsn = get_dsn()
    if dsn:
        try:
            store = get_store(dsn, os.environ.get("FRESHROOTS_DB_SCHEMA", "public"))
            st.session_state.setdefault("workdir", tempfile.mkdtemp(prefix="freshroots_"))
            out_base = Path(st.session_state.workdir)       # scratch copy; Postgres is the source of truth
            run_ids = store.list_runs()
            store.reserve(run_ids[RECENT_RUNS:], out_base)
            store.materialize(run_ids[:RECENT_RUNS], out_base)
            note = "Saved to the Neon database."
        except Exception as exc:                              # an unreachable DB must not take the app down
            store = None
            st.warning(f"Database unavailable ({type(exc).__name__}). Working with local files only; nothing will be saved to Neon.")
    return Workspace(cfg, data_dir, out_base, store, note)
