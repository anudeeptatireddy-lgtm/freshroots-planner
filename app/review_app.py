"""Human review: decide every exception, then generate POs.  Run: streamlit run app/review_app.py"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from components import line_card
from glossary import Glossary

from planner import outputs, review
from planner.common import STATUS_AUTO, STATUS_REVIEW, PlannerError, load_config

ROOT = Path(__file__).resolve().parents[1]
OUT_BASE = Path(os.environ.get("FRESHROOTS_OUTPUTS", ROOT / "outputs"))
CONFIG = Path(os.environ.get("FRESHROOTS_CONFIG", ROOT / "config.yaml"))
DATA_DIR = ROOT / "data" / "raw"
UPLOADABLE = ["weekly_sales.csv", "sku_master.csv", "distributor_master.csv", "current_inventory.csv", "calendar.csv",
              "open_purchase_orders.csv", "sku_prices.csv", "distributor_sales.csv"]

st.set_page_config(page_title="Freshroots review", page_icon="🌿", layout="centered")
st.markdown(f"<style>{(Path(__file__).parent / 'style.css').read_text()}</style>", unsafe_allow_html=True)

cfg = load_config(CONFIG)


gloss = Glossary(cfg)


def list_runs() -> list[Path]:
    if not OUT_BASE.exists():
        return []
    return sorted((p for p in OUT_BASE.glob("*") if (p / "planning_table.csv").exists()), reverse=True)


# ---- header + run selection --------------------------------------------------------------
st.markdown("### 🌿 Freshroots planning")
runs = list_runs()
with st.expander("▶ Run planning" + ("  (start here)" if not runs else ""), expanded=not runs):
    st.caption("Uses the files in data/raw. Upload fresh SAP exports to replace any of them (same file names and columns).")
    uploads = st.file_uploader("Replace input files (optional)", type="csv", accept_multiple_files=True, key="uploads",
                               help="Optional. Upload new SAP exports (same file names and columns) to plan on fresh data instead of the bundled files.")
    bad = [u.name for u in uploads or [] if u.name not in UPLOADABLE]
    if bad:
        st.error(f"Unrecognised file name(s): {', '.join(bad)}. Expected: {', '.join(UPLOADABLE)}")
    if st.button("Run planning", type="primary", disabled=bool(bad), key="run_now", width="stretch",
                 help="Loads the data, cleans it, applies the rules, and flags the lines that need a person."):
        try:
            outputs.plan_with_overrides(DATA_DIR, {u.name: u.getvalue() for u in uploads or []}, cfg, OUT_BASE)
            st.rerun()
        except PlannerError as e:
            st.error(str(e))
runs = list_runs()
if not runs:
    st.info("No runs yet. Open **Run planning** above and tap the button.")
    st.stop()

c1, c2 = st.columns([1, 1])
run_dir = c1.selectbox("Run", runs, format_func=lambda p: p.name, help="One planning snapshot, named by the stock-count date.")
reviewer = c2.text_input("Your name", key="reviewer", placeholder="Required to save decisions",
                         help="Recorded in the review log next to every decision you make.")

table = outputs.load_planning_table(run_dir)
log_path = run_dir / "review_log.csv"
decisions = review.latest_decisions(review.read_log(log_path))
decided = decisions.set_index("sku_id") if not decisions.empty else pd.DataFrame()
pending = review.pending_review(table, decisions)
needs = table[table.status == STATUS_REVIEW]
auto = table[table.status == STATUS_AUTO]
n_done = len(needs) - len(pending)

# ---- progress strip ----------------------------------------------------------------------
with st.container(key="stats"):
    s = st.columns(4)
    s[0].metric("SKUs", len(table), help="Products planned in this run (SKU = one product).")
    s[1].metric("Review", len(needs), help="Lines a person must decide on before any PO can be made.")
    s[2].metric("Auto", len(auto), help="Lines the rules approved on their own: an order is needed and nothing looks unusual. You can still edit them.")
    s[3].metric("No order", len(table) - len(needs) - len(auto), help="Healthy or overstocked: no order this run. See All SKUs.")
if len(needs):
    st.progress(n_done / len(needs), text=f"{n_done} of {len(needs)} exceptions decided")
    st.caption("Exception = a line the rules cannot safely decide alone. Tap or hover the ? marks for meanings.")


def decide(sku: str, system_qty: float, decision: str, qty: float | None = None, note: str = "") -> None:
    try:
        review.append_log(log_path, [review.make_decision(sku, system_qty, decision, reviewer, final_qty=qty, note=note)])
    except PlannerError as e:
        st.error(str(e))
        return
    st.rerun()


# ---- tabs --------------------------------------------------------------------------------
t_review, t_orders, t_auto, t_all = st.tabs([f"Review ({len(pending)})", "Orders", f"Auto ({len(auto)})", "All SKUs"])

with t_review:
    if needs.empty:
        st.success("No exceptions this run.")
    elif not pending:
        st.success("All exceptions decided. Go to **Orders** to generate the POs.", icon="🎉")
    for r in needs.assign(_done=needs.sku_id.isin(pending).map({True: 0, False: 1})).sort_values(
            ["_done", "is_urgent", "sku_id"], ascending=[True, False, True]).itertuples():
        line_card(r, "exc", gloss, decided, decide)

with t_orders:
    blocked = bool(pending)
    if blocked:
        st.error(f"Cannot generate POs yet: {len(pending)} exception(s) still need a decision ({', '.join(pending)}).")
    st.caption("Auto-approved lines you haven't touched go on the PO at the system quantity.")
    if st.button("Generate purchase orders", type="primary", disabled=blocked, key="generate", width="stretch",
                 help="Builds one PO per supplier from approved lines, plus the Zoho import file and a handoff note. Locked until every exception is decided."):
        try:
            if not reviewer.strip():
                raise PlannerError("Enter your name at the top of the page first")
            outputs.generate_pos(run_dir, cfg)
            st.rerun()
        except PlannerError as e:
            st.error(str(e))

    # Downloads are read from the run folder, so they survive reruns (a download click reruns the page).
    if (run_dir / "sourcing_handoff.md").exists():
        rl = json.loads((run_dir / "run_log.json").read_text())
        st.success(f"{rl.get('po_count', 0)} PO(s) · {rl.get('po_line_count', 0)} line(s) · {rl.get('lines_held_back', 0)} held back", icon="📦")
        rate = rl.get("override_rate")
        st.caption("Override rate = share of decided lines where the final quantity differs from the system quantity (a rejected order counts). If it stays above 30%, the rules do not match reality.")
        st.caption(f"Override rate: {'n/a' if rate is None or not rl.get('human_decisions') else format(rate, '.0%')} "
                   f"({rl.get('override_count')} of {rl.get('lines_decided')} lines)")
        zoho = run_dir / "purchase_orders_zoho_import.csv"
        if zoho.exists():
            st.dataframe(pd.read_csv(zoho), width="stretch", hide_index=True)
            st.download_button("⬇ Zoho import CSV", zoho.read_bytes(), file_name=zoho.name, mime="text/csv", key="dl_zoho", width="stretch")
        for p in sorted(run_dir.glob("PO_*.pdf")):
            st.download_button(f"⬇ {p.name}", p.read_bytes(), file_name=p.name, mime="application/pdf", key=f"dl_{p.name}", width="stretch")
        st.download_button("⬇ Sourcing handoff", (run_dir / "sourcing_handoff.md").read_bytes(), file_name="sourcing_handoff.md", key="dl_handoff", width="stretch")
        st.download_button("⬇ review_log.csv", log_path.read_bytes(), file_name=f"review_log_{run_dir.name}.csv", key="dl_log2", width="stretch",
                           help="Hosted disks are wiped on restart: keep a copy after each review.")

with t_auto:
    st.caption("No decision needed, but you can approve at a different quantity or reject.")
    if auto.empty:
        st.info("No auto-approved lines.")
    for r in auto.itertuples():
        line_card(r, "auto", gloss, decided, decide)

with t_all:
    show = table[["sku_id", "sku_name", "perishability", "weeks_of_cover", "change_4w_vs_12w", "flag", "order_qty",
                  "weeks_of_cover_after_order", "forecast_total_4w", "status", "exceptions"]]
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "weeks_of_cover": st.column_config.NumberColumn("Cover (wks)", format="%.2f", help=gloss.terms["Weeks of cover"]),
        "weeks_of_cover_after_order": st.column_config.NumberColumn("After order", format="%.2f", help=gloss.terms["after order"]),
        "change_4w_vs_12w": st.column_config.NumberColumn("4w vs 12w", format="percent", help=gloss.terms["4w vs 12w demand"]),
        "forecast_total_4w": st.column_config.NumberColumn("4-wk forecast", format="%.0f", help=gloss.terms["forecast"]),
        "order_qty": st.column_config.NumberColumn("Order qty", format="%.0f", help=gloss.terms["System order qty"]),
        "flag": st.column_config.TextColumn("Flag", help="The rule outcome: HEALTHY, STOCKOUT_RISK, HIGH_DEMAND or OVERSTOCK."),
        "status": st.column_config.TextColumn("Status", help="NEEDS_REVIEW = a person decides. AUTO_APPROVED = rules approved. NO_ORDER = nothing to order."),
        "exceptions": st.column_config.TextColumn("Exceptions", help="Why a person must look at this line.")})
    flag_counts = pd.Series([f for v in table.flag for f in str(v).split(" + ")]).value_counts()
    st.caption("Flags: " + " · ".join(f"{k} {v}" for k, v in flag_counts.items()))
