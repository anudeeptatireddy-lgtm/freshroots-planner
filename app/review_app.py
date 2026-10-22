"""Human review: decide every exception, then generate POs.  Run: streamlit run app/review_app.py"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))   # always run the repo code, never a stale installed copy

import fr_html as fr
import pandas as pd
import streamlit as st
from cards import auto_card, done_card, open_card

from planner import outputs, review
from planner.common import STATUS_AUTO, STATUS_REVIEW, PlannerError, load_config

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


def list_runs() -> list[Path]:
    if not OUT_BASE.exists():
        return []
    return sorted((p for p in OUT_BASE.glob("*") if (p / "planning_table.csv").exists()), reverse=True)


def uploader(key: str):
    """File uploader + required/optional checklist; returns (uploaded files, True when a name is unrecognised)."""
    ups = st.file_uploader("Add SAP files", type="csv", accept_multiple_files=True, key=key, label_visibility="collapsed")
    added = {u.name for u in ups or []}
    bad = sorted(added - set(REQUIRED) - set(OPTIONAL))
    st.markdown(f"**Required** · {len(added & set(REQUIRED))} of {len(REQUIRED)} added")
    st.markdown(fr.file_checklist(REQUIRED, added), unsafe_allow_html=True)
    st.markdown("**Optional**")
    st.markdown(fr.file_checklist(OPTIONAL, added), unsafe_allow_html=True)
    if bad:
        st.error(f"Unrecognised file name(s): {', '.join(bad)}.")
    return ups, bool(bad)


def start_run(ups) -> None:
    try:
        outputs.plan_with_overrides(DATA_DIR, {u.name: u.getvalue() for u in ups or []}, cfg, OUT_BASE)
    except PlannerError as e:
        st.error(str(e))
        return
    st.rerun()


# ---- A. empty state ------------------------------------------------------------------------
runs = list_runs()
if not runs:
    st.markdown('<h1 class="fr-title">Freshroots demand planning</h1><p class="fr-sub">Review exceptions, then generate purchase orders.</p>',
                unsafe_allow_html=True)
    with st.container(border=True, key="empty"):
        st.markdown("#### No planning run yet")
        st.write("Run planning to load the SAP data, apply the rules and list the lines that need your decision.")
        go = st.button("Run planning", type="primary", width="stretch", key="run_now")
        st.caption("Uses the SAP files already on the server unless you add fresh ones below.")
    with st.expander("Use fresh SAP files (optional)", expanded=True):
        ups, bad = uploader("uploads")
    if go and not bad:
        start_run(ups)
    st.stop()

# ---- B. header -----------------------------------------------------------------------------
with st.expander("Run details and new run"):
    run_dir = st.selectbox("Run", runs, format_func=lambda p: p.name, help="One planning snapshot, named by the stock-count date.")
    files = list(json.loads((run_dir / "run_log.json").read_text()).get("file_hashes_sha256", {}))
    st.caption("Source files: " + ", ".join(files))
    ups, bad = uploader("uploads")
    if st.button("Start a new run", key="new_run", type="secondary", width="stretch", disabled=bad):
        start_run(ups)

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
st.markdown(f'<h1 class="fr-title">Freshroots demand planning</h1><p class="fr-sub">{run_line}</p>', unsafe_allow_html=True)

reviewer = st.text_input("Reviewer name", key="reviewer", placeholder="Required to save decisions",
                         help="Recorded in the review log next to every decision you make.")


def save_decision(sku: str, system_qty: float, action: str, qty: float, note: str) -> None:
    try:
        review.append_log(log_path, [review.make_decision(sku, system_qty, action, reviewer, final_qty=qty, note=note)])
    except PlannerError as e:
        st.error(str(e))
        return
    st.session_state.reopen.pop(sku, None)
    st.session_state.flash = f"Saved: {sku} {PAST[action]} at {int(qty):,}."
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

t_review, t_orders, t_auto, t_all = st.tabs([f"Review · {len(pending)}", "Orders", f"Auto · {len(auto)}", "All SKUs"])

# ---- C. review tab ---------------------------------------------------------------------------
with t_review:
    if needs.empty:
        st.success("No exceptions this run.")
    ordered = needs.assign(_open=needs.sku_id.isin(pending)).sort_values(["_open", "is_urgent", "sku_id"], ascending=[False, False, True])
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
    names = needs.set_index("sku_id")
    if pending:
        lines = "\n".join(f"- **{s}** {names.loc[s, 'sku_name']}" + (" · URGENT" if names.loc[s, "is_urgent"] else "") for s in pending)
        st.warning(f"**{len(pending)} exception{'s' if len(pending) != 1 else ''} still need a decision**\n\n"
                   f"Purchase orders can be generated once every exception is decided.\n\n{lines}\n\nOpen the Review tab to decide them.")
    if not (run_dir / "sourcing_handoff.md").exists():
        if st.button("Generate purchase orders", type="primary", disabled=bool(pending), width="stretch", key="generate",
                     help="Builds one PO per supplier from approved lines, plus the Zoho import file and a handoff note."):
            try:
                if not reviewer.strip():
                    raise PlannerError("Enter your name at the top of the page first")
                outputs.generate_pos(run_dir, cfg)
                st.rerun()
            except PlannerError as e:
                st.error(str(e))
        if pending:
            st.caption(f"Unlocks when all {len(needs)} exceptions are decided. The {len(auto)} auto-approved lines are included automatically.")
    else:
        # Downloads are read from the run folder, so they survive reruns (a download click reruns the page).
        rl = json.loads((run_dir / "run_log.json").read_text())
        st.success(f"{rl.get('po_count', 0)} purchase orders ready · {rl.get('po_line_count', 0)} lines · {rl.get('lines_held_back', 0)} held back")
        rate, human = rl.get("override_rate"), rl.get("human_decisions")
        st.metric("Override rate", "n/a" if rate is None or not human else f"{rate:.0%}",
                  help="Share of decided lines where the final quantity differs from the system quantity (a rejected order counts).")
        st.caption(f"{rl.get('override_count')} of {rl.get('lines_decided')} decided lines")
        if rate is not None and human:
            st.markdown(fr.override_meter(rate), unsafe_allow_html=True)
            if rate > 0.30:
                st.info("Above 30% this run. One run is not a trend; if it stays above 30% over several runs, the rules may not match reality and are worth revisiting.")
        zoho = run_dir / "purchase_orders_zoho_import.csv"
        if zoho.exists():
            zc = cfg["po"]["zoho_columns"]
            z = pd.read_csv(zoho)
            st.download_button("Download Zoho import (CSV)", zoho.read_bytes(), file_name=zoho.name, mime="text/csv", type="primary",
                               width="stretch", key="dl_zoho")
            by_sku = table.set_index("sku_id")
            src = {sku: "Auto" if str(row.reviewer).startswith("system:") else ("Changed" if row.decision == "edit" else "Approved")
                   for sku, row in (decided.iterrows() if len(decided) else [])}
            for po, g in z.groupby(zc["po_number"]):
                with st.container(border=True, key=f"po-{po}"):
                    st.markdown(f"**{po}**  \n{g[zc['vendor_name']].iloc[0]} · {len(g)} line{'s' if len(g) != 1 else ''} · {int(g[zc['quantity']].sum()):,} units")
                    pdf = run_dir / f"PO_{po}.pdf"
                    if pdf.exists():
                        st.download_button("PDF", pdf.read_bytes(), file_name=pdf.name, mime="application/pdf", key=f"dl_{pdf.name}", width="stretch")
            st.dataframe(pd.DataFrame({
                "PO": z[zc["po_number"]], "SKU": z[zc["sku"]], "Final": z[zc["quantity"]],
                "System": [int(by_sku.loc[s, "order_qty"]) for s in z[zc["sku"]]],
                "Source": [src.get(s, "Auto") for s in z[zc["sku"]]], "Product": z[zc["item_name"]]}), width="stretch", hide_index=True)
        st.caption("Unit prices are not in this run's data, so order values are not shown.")
        st.download_button("Sourcing handoff note", (run_dir / "sourcing_handoff.md").read_bytes(), file_name="sourcing_handoff.md",
                           key="dl_handoff", width="stretch")
        st.download_button("Review log (CSV)", log_path.read_bytes(), file_name=f"review_log_{run_dir.name}.csv", key="dl_log2", width="stretch",
                           help="Hosted disks are wiped on restart: keep a copy after each review.")

# ---- E. auto tab -----------------------------------------------------------------------------
with t_auto:
    if auto.empty:
        st.info("No auto-approved lines.")
    else:
        st.markdown(f"**{len(auto)} lines ordered by the rules with nothing unusual.** They go into the POs as shown. Edit one only if your judgment differs.")
    for r in auto.itertuples():
        auto_card(r, current(r.sku_id), reviewer, save_decision)

# ---- F. all SKUs tab -------------------------------------------------------------------------
with t_all:
    choice = st.selectbox("Show", [f"All statuses ({len(table)})", "Needs review", "Auto-approved", "No order"], key="all_filter")
    shown = {"Needs review": needs, "Auto-approved": auto, "No order": table[~table.status.isin([STATUS_REVIEW, STATUS_AUTO])]}.get(choice, table)
    cols = ["sku_id", "status", "weeks_of_cover", "order_qty", "weeks_of_cover_after_order", "flag", "change_4w_vs_12w",
            "forecast_total_4w", "exceptions", "sku_name"]
    st.dataframe(shown[cols], width="stretch", hide_index=True, column_config={
        "sku_id": st.column_config.TextColumn("SKU", pinned=True),
        "status": st.column_config.TextColumn("Status", help="NEEDS_REVIEW = a person decides. AUTO_APPROVED = rules approved. NO_ORDER = nothing to order."),
        "weeks_of_cover": st.column_config.NumberColumn("Cover", format="%.1f", help="Weeks the current stock lasts at expected demand."),
        "order_qty": st.column_config.NumberColumn("Order", format="%.0f", help=fr.GLOSSARY["System qty"]),
        "weeks_of_cover_after_order": st.column_config.NumberColumn("After", format="%.1f", help="Weeks of cover once the order arrives."),
        "flag": st.column_config.TextColumn("Flag", help="The rule outcome: HEALTHY, STOCKOUT_RISK, HIGH_DEMAND or OVERSTOCK."),
        "change_4w_vs_12w": st.column_config.NumberColumn("4w vs 12w", format="percent", help=fr.GLOSSARY["4w vs 12w"]),
        "forecast_total_4w": st.column_config.NumberColumn("4-week forecast", format="%.0f",
                                                           help="Expected units over the next 4 weeks: the 12-week average times each week's festival uplift."),
        "exceptions": st.column_config.TextColumn("Exceptions", help="Why a person must look at this line."),
        "sku_name": st.column_config.TextColumn("Product")})
    st.caption("Swipe the table sideways for flag, demand change, 4-week forecast and exceptions. Tap a column name to sort.")
