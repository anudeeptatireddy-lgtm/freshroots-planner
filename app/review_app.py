"""Human review: decide every exception, then generate POs.  Run: streamlit run app/review_app.py"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from planner import outputs, review
from planner.common import PlannerError, load_config

ROOT = Path(__file__).resolve().parents[1]
OUT_BASE = Path(os.environ.get("FRESHROOTS_OUTPUTS", ROOT / "outputs"))
CONFIG = Path(os.environ.get("FRESHROOTS_CONFIG", ROOT / "config.yaml"))

st.set_page_config(page_title="Freshroots review", layout="wide")
st.title("Freshroots demand planning: review")

# ---- choose run ------------------------------------------------------------------------
runs = sorted((p for p in OUT_BASE.glob("*") if (p / "planning_table.csv").exists()), reverse=True) if OUT_BASE.exists() else []
if not runs:
    st.error(f"No runs found in {OUT_BASE}. Run `python -m planner run` first.")
    st.stop()
with st.sidebar:
    run_dir = st.selectbox("Run", runs, format_func=lambda p: p.name)
    reviewer = st.text_input("Your name (required to save decisions)", key="reviewer")
    st.caption("Decisions are appended to review_log.csv in the run folder.")

cfg = load_config(CONFIG)
table = outputs.load_planning_table(run_dir)
log_path = run_dir / "review_log.csv"
decisions = review.latest_decisions(review.read_log(log_path))
decided = decisions.set_index("sku_id") if not decisions.empty else pd.DataFrame()
pending = review.pending_review(table, decisions)

# ---- summary ---------------------------------------------------------------------------
needs = table[table.status == "NEEDS_REVIEW"]
auto = table[table.status == "AUTO_APPROVED"]
c = st.columns(4)
c[0].metric("SKUs processed", len(table))
c[1].metric("Exceptions waiting", len(pending))
c[2].metric("Lines ready (auto-approved)", len(auto))
c[3].metric("Exceptions decided", len(needs) - len(pending))
flag_counts = pd.Series([f for v in table.flag for f in str(v).split(" + ")]).value_counts()
exc_counts = pd.Series([e for v in table.exceptions if v for e in str(v).split("; ")], dtype=object).value_counts()
l, r = st.columns(2)
l.caption("Flags")
l.dataframe(flag_counts.rename("SKUs"), use_container_width=True)
r.caption("Exceptions")
r.dataframe(exc_counts.rename("SKUs") if len(exc_counts) else pd.Series(dtype=int, name="SKUs"), use_container_width=True)


def line_card(row, key_prefix: str) -> None:
    sku = row.sku_id
    cur = decided.loc[sku] if sku in getattr(decided, "index", []) else None
    cols = st.columns(6)
    cols[0].metric("On hand", f"{row.units_on_hand:,.0f}")
    cols[1].metric("Cover now (wks)", f"{row.weeks_of_cover:.2f}" if pd.notna(row.weeks_of_cover) else "n/a")
    cols[2].metric("Cover after (wks)", f"{row.weeks_of_cover_after_order:.2f}" if pd.notna(row.weeks_of_cover_after_order) else "n/a")
    cols[3].metric("4w vs 12w", f"{row.change_4w_vs_12w:+.1%}" if pd.notna(row.change_4w_vs_12w) else "n/a")
    cols[4].metric("System qty", f"{row.order_qty:,.0f}")
    cols[5].metric("Min / max wks", f"{row.min_weeks:g} / {row.max_weeks:g}" if pd.notna(row.min_weeks) else "n/a")
    st.write(f"**Rule triggered:** {row.flag}: {row.flag_reasons}")
    if row.exception_reasons:
        for part in str(row.exception_reasons).split(" | "):
            st.warning(part)
    if pd.notna(row.suggested_qty):
        st.info(f"Suggested alternative: {row.suggested_qty:,.0f} units. {row.suggested_note}")
    if cur is not None:
        st.success(f"Decided: {cur.decision} at {cur.final_qty:,.0f} by {cur.reviewer} ({cur.timestamp})" + (f" - {cur.note}" if cur.note else ""))
    with st.form(f"{key_prefix}_{sku}"):
        choice = st.radio("Decision", ["Approve", "Edit quantity", "Reject"], horizontal=True, key=f"{key_prefix}_{sku}_choice")
        default = int(row.suggested_qty) if pd.notna(row.suggested_qty) else int(row.order_qty)
        qty = st.number_input("Quantity (used when editing)", min_value=0, step=1, value=default, key=f"{key_prefix}_{sku}_qty")
        note = st.text_input("Note (optional)", key=f"{key_prefix}_{sku}_note")
        if st.form_submit_button("Save decision"):
            try:
                d = review.make_decision(sku, row.order_qty, {"Approve": "approve", "Edit quantity": "edit", "Reject": "reject"}[choice],
                                         reviewer, final_qty=qty, note=note)
                review.append_log(log_path, [d])
                st.rerun()
            except PlannerError as e:
                st.error(str(e))


# ---- exceptions first --------------------------------------------------------------------
st.header("Exceptions")
if needs.empty:
    st.success("No exceptions this run.")
for row in needs.sort_values(["is_urgent", "sku_id"], ascending=[False, True]).itertuples():
    done = row.sku_id not in pending
    label = f"{'DONE' if done else 'WAITING'}  {row.sku_id} {row.sku_name}  [{row.exceptions}]" + ("  URGENT" if row.is_urgent else "")
    with st.expander(label, expanded=not done):
        line_card(row, "exc")

# ---- auto-approved lines (still editable) ------------------------------------------------
st.header("Auto-approved lines")
st.caption("These need no decision but can be edited or rejected. Undecided ones are approved at the system quantity when you generate POs.")
for row in auto.itertuples():
    with st.expander(f"{row.sku_id} {row.sku_name}: {row.order_qty:,.0f} units ({row.flag})"):
        line_card(row, "auto")

with st.expander("All SKUs"):
    st.dataframe(table[["sku_id", "sku_name", "perishability", "weeks_of_cover", "change_4w_vs_12w", "flag", "order_qty",
                        "weeks_of_cover_after_order", "forecast_total_4w", "status", "exceptions"]], use_container_width=True)

# ---- generate POs ------------------------------------------------------------------------
st.header("Purchase orders")
blocked = bool(pending)
if blocked:
    st.error(f"Cannot generate POs: {len(pending)} exception(s) still need a decision ({', '.join(pending)}).")
if st.button("Generate purchase orders", type="primary", disabled=blocked, key="generate"):
    try:
        if not reviewer.strip():
            raise PlannerError("Enter your name in the sidebar first")
        undecided_auto = auto[~auto.sku_id.isin(set(decisions.sku_id) if not decisions.empty else set())]
        review.append_log(log_path, [review.make_decision(r.sku_id, r.order_qty, "approve", review.AUTO_REVIEWER) for r in undecided_auto.itertuples()])
        res = outputs.finalize_run(run_dir, cfg)
        st.success(f"{res['lines'].po_number.nunique() if not res['lines'].empty else 0} PO(s) written to {run_dir}")
        stt = res["stats"]
        st.write(f"Override rate: {'n/a' if stt['override_rate'] is None else format(stt['override_rate'], '.0%')} ({stt['overrides']} of {stt['decided_lines']} lines)")
        if not res["lines"].empty:
            st.dataframe(res["lines"].drop(columns="is_urgent"), use_container_width=True)
        for p in res["pdfs"]:
            st.download_button(f"Download {p.name}", p.read_bytes(), file_name=p.name, mime="application/pdf", key=f"dl_{p.name}")
        if (run_dir / "purchase_orders_zoho_import.csv").exists():
            st.download_button("Download Zoho import CSV", (run_dir / "purchase_orders_zoho_import.csv").read_bytes(),
                               file_name="purchase_orders_zoho_import.csv", key="dl_zoho")
        st.download_button("Download sourcing handoff", (run_dir / "sourcing_handoff.md").read_bytes(), file_name="sourcing_handoff.md", key="dl_handoff")
    except PlannerError as e:
        st.error(str(e))
