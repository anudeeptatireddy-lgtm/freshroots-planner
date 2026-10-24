"""Human review: decide every exception, then generate POs.  Run: streamlit run app/review_app.py"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))   # always run the repo code, never a stale installed copy

import fr_html as fr
import pandas as pd
import streamlit as st
from cards import auto_card, done_card, open_card
from orders_ui import render_orders
from rows import rows_view
from skus_ui import render_all_skus

from planner import outputs, review
from planner.common import STATUS_AUTO, STATUS_REVIEW, PlannerError, load_config
from planner.store import Store

OUT_BASE = Path(os.environ.get("FRESHROOTS_OUTPUTS", ROOT / "outputs"))
CONFIG = Path(os.environ.get("FRESHROOTS_CONFIG", ROOT / "config.yaml"))
DATA_DIR = ROOT / "data" / "raw"
REQUIRED = ["weekly_sales.csv", "sku_master.csv", "distributor_master.csv", "current_inventory.csv", "calendar.csv"]
OPTIONAL = ["open_purchase_orders.csv", "sku_prices.csv", "distributor_sales.csv"]
PAST = {"approve": "approved", "edit": "changed", "reject": "rejected"}

st.set_page_config(page_title="Freshroots demand planning", layout="centered")
st.markdown(f"<style>{(HERE / 'style.css').read_text()}</style>", unsafe_allow_html=True)
st.markdown(fr.theme_marker(), unsafe_allow_html=True)
st.session_state.setdefault("reopen", {})
if st.session_state.get("flash"):
    st.toast(st.session_state.pop("flash"))

cfg = load_config(CONFIG)
RECENT_RUNS = 8     # newest runs rebuilt from the database on each page load; older ids are only reserved


def get_dsn() -> str | None:
    """Database URL: env var first (tests, scheduled runs), then Streamlit secrets. FRESHROOTS_DISABLE_DB forces files-only."""
    if os.environ.get("FRESHROOTS_DISABLE_DB"):
        return None
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    try:
        return st.secrets["DATABASE_URL"]
    except Exception:       # no secrets file / key
        return None


@st.cache_resource
def get_store(dsn: str, schema: str) -> Store:
    store = Store(dsn, schema)
    store.ensure_schema()
    return store


store, db_note = None, "Local files only. Nothing is saved to a database."
if get_dsn():
    try:
        store = get_store(get_dsn(), os.environ.get("FRESHROOTS_DB_SCHEMA", "public"))
        st.session_state.setdefault("workdir", tempfile.mkdtemp(prefix="freshroots_"))
        OUT_BASE = Path(st.session_state.workdir)           # scratch copy; Postgres is the source of truth
        run_ids = store.list_runs()
        store.reserve(run_ids[RECENT_RUNS:], OUT_BASE)
        store.materialize(run_ids[:RECENT_RUNS], OUT_BASE)
        db_note = "Saved to the Neon database."
    except Exception as exc:                                  # unreachable DB must not take the app down
        store = None
        st.warning(f"Database unavailable ({type(exc).__name__}). Working with local files only; nothing will be saved to Neon.")


def sync_up(run_dir: Path, decisions_only: bool = False) -> None:
    """Mirror a changed run folder to Postgres (no-op without a database)."""
    if not store:
        return
    try:
        store.save_decisions(run_dir) if decisions_only else store.save_run(run_dir, cfg)
    except Exception as exc:
        st.error(f"Could not save to the database ({type(exc).__name__}). Your change is only on this server.")


def list_runs() -> list[Path]:
    if not OUT_BASE.exists():
        return []
    return sorted((p for p in OUT_BASE.glob("*") if (p / "planning_table.csv").exists()), reverse=True)


def upload_corner() -> None:
    """Top-right upload icon. Adding CSVs here starts a new run straight away."""
    n = st.session_state.setdefault("up_n", 0)
    with st.popover("⬆ Upload"):
        st.markdown("**Upload SAP files**  \nA new run starts as soon as the files are added.")
        ups = st.file_uploader("Add SAP files", type="csv", accept_multiple_files=True, key=f"uploads-{n}", label_visibility="collapsed")
        added = {u.name for u in ups or []}
        bad = sorted(added - set(REQUIRED) - set(OPTIONAL))
        st.markdown(f"**Required** · {len(added & set(REQUIRED))} of {len(REQUIRED)} added")
        st.markdown(fr.file_checklist(REQUIRED, added), unsafe_allow_html=True)
        st.markdown("**Optional**")
        st.markdown(fr.file_checklist(OPTIONAL, added), unsafe_allow_html=True)
        if bad:
            st.error(f"Unrecognised file name(s): {', '.join(bad)}.")
        elif ups:
            st.session_state.up_n = n + 1        # fresh uploader next time, so the same files never run twice
            start_run(ups)


hdr = st.container(key="hdr")


def render_header(line: str) -> None:
    with hdr:
        left, right = st.columns([5, 2])
        left.markdown(f'<h1 class="fr-title">Freshroots demand planning</h1><p class="fr-sub">{line}</p>', unsafe_allow_html=True)
        with right:
            upload_corner()


def start_run(ups) -> None:
    try:
        new_dir = outputs.plan_with_overrides(DATA_DIR, {u.name: u.getvalue() for u in ups or []}, cfg, OUT_BASE)
        sync_up(new_dir)
    except PlannerError as e:
        st.error(str(e))
        return
    st.rerun()


# ---- A. empty state ------------------------------------------------------------------------
runs = list_runs()
if not runs:
    render_header("Review exceptions, then generate purchase orders.")
    with st.container(border=True, key="empty"):
        st.markdown("#### No planning run yet")
        st.write("Run planning to load the SAP data, apply the rules and list the lines that need your decision.")
        if st.button("Run planning", type="primary", width="stretch", key="run_now"):
            start_run([])
        st.caption("Uses the SAP files already on the server. Use Upload (top right) to run on fresh SAP files instead.")
    st.stop()

# ---- B. header -----------------------------------------------------------------------------
with st.expander("Run details and new run"):
    run_dir = st.selectbox("Run", runs, format_func=lambda p: p.name, help="One planning snapshot, named by the stock-count date.")
    files = list(json.loads((run_dir / "run_log.json").read_text()).get("file_hashes_sha256", {}))
    st.caption("Source files: " + ", ".join(files))
    st.caption(db_note)
    if st.button("Start a new run", key="new_run", type="secondary", width="stretch",
                 help="Plan again on the files already on the server. To use fresh SAP files, tap Upload (top right)."):
        start_run([])

table = outputs.load_planning_table(run_dir)
log_path = run_dir / "review_log.csv"
decisions = review.latest_decisions(review.read_log(log_path))
decided = decisions.set_index("sku_id") if not decisions.empty else pd.DataFrame()
pending = review.pending_review(table, decisions)
needs = table[table.status == STATUS_REVIEW]
auto = table[table.status == STATUS_AUTO]
n_done = len(needs) - len(pending)
run_line = f"Run <b>{run_dir.name.split('_')[0]}</b>"
if bool(table.is_festival.iloc[0]):
    run_line += f" · festival month, demand +{table.uplift.iloc[0] * 100 - 100:.0f}%"
render_header(run_line)

reviewer = st.text_input("Reviewer name", key="reviewer", placeholder="Type your name, then press Enter",
                         help="Recorded in the review log next to every decision you make.")
if reviewer.strip():
    st.caption(f"Saving decisions as **{reviewer.strip()}** ✓")


def save_decision(sku: str, system_qty: float, action: str, qty: float, note: str) -> None:
    try:
        review.append_log(log_path, [review.make_decision(sku, system_qty, action, reviewer, final_qty=qty, note=note)])
    except PlannerError as e:
        st.error(str(e))
        return
    sync_up(run_dir, decisions_only=True)
    st.session_state.reopen.pop(sku, None)
    st.session_state.flash = f"Saved: {sku} {PAST[action]} at {int(qty):,}."
    st.rerun()


def save_many(changes: list[tuple[str, float, str, float, str]]) -> None:
    try:
        review.append_log(log_path, [review.make_decision(sku, sq, action, reviewer, final_qty=q, note=note) for sku, sq, action, q, note in changes])
    except PlannerError as e:
        st.error(str(e))
        return
    sync_up(run_dir, decisions_only=True)
    for sku, *_ in changes:
        st.session_state.reopen.pop(sku, None)
    st.session_state.flash = f"Saved {len(changes)} decision{'s' if len(changes) != 1 else ''}."
    st.rerun()


def reopen(sku: str) -> None:
    st.session_state.reopen[sku] = True
    st.rerun()


def current(sku: str):
    return decided.loc[sku] if len(decided) and sku in decided.index else None


with st.container(key="stats"):
    s = st.columns(4)
    s[0].metric("SKUs", len(table), help="Products planned in this run (SKU = one product).")
    s[1].metric("Review", len(needs), help="Lines a person must decide on before any PO can be made.")
    s[2].metric("Auto", len(auto), help="Lines the rules approved on their own: an order is needed and nothing looks unusual.")
    s[3].metric("No order", len(table) - len(needs) - len(auto), help="Healthy or overstocked: no order this run. See All SKUs.")
if len(needs):
    st.progress(n_done / len(needs), text=f"{n_done} of {len(needs)} exceptions decided" if pending else f"All {len(needs)} exceptions decided")

view = st.segmented_control("View", ["Cards", "Rows"], default="Cards", key="view_mode", label_visibility="collapsed",
                            help="Cards: one card per product. Rows: all products in one table, to decide many at once.")
rows_mode = view == "Rows"
t_review, t_auto, t_orders, t_all = st.tabs([f"Review · {len(pending)}", f"Auto · {len(auto)}", "Orders", "All SKUs"])

# ---- C. review tab ---------------------------------------------------------------------------
with t_review:
    if needs.empty:
        st.success("No exceptions this run.")
    ordered = needs.assign(_open=needs.sku_id.isin(pending)).sort_values(["_open", "is_urgent", "sku_id"], ascending=[False, False, True])
    if rows_mode:
        rows_view(ordered, decided, reviewer, save_many, "review")
    else:
        for r in ordered[ordered._open].itertuples():
            open_card(r, current(r.sku_id), False, reviewer, save_decision)
        done = ordered[~ordered._open]
        if len(done):
            st.markdown(f'<p class="fr-divider">Decided · {len(done)}</p>', unsafe_allow_html=True)
        for r in done.itertuples():
            if st.session_state.reopen.get(r.sku_id):
                open_card(r, current(r.sku_id), True, reviewer, save_decision)
            else:
                done_card(r, current(r.sku_id), reopen)

# ---- D. orders tab ---------------------------------------------------------------------------
with t_orders:
    render_orders(run_dir, cfg, table, needs, auto, pending, decided, reviewer, log_path, sync_up)

# ---- E. auto tab -----------------------------------------------------------------------------
with t_auto:
    if auto.empty:
        st.info("No auto-approved lines.")
    else:
        st.markdown(f"**{len(auto)} lines ordered by the rules with nothing unusual.** They go into the POs as shown. Edit one only if your judgment differs.")
    if rows_mode:
        rows_view(auto, decided, reviewer, save_many, "auto")
    else:
        for r in auto.itertuples():
            auto_card(r, current(r.sku_id), reviewer, save_decision)

# ---- F. all SKUs tab -------------------------------------------------------------------------
with t_all:
    render_all_skus(table, needs, auto)
