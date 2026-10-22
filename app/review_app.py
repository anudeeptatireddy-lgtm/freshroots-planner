"""Human review: decide every exception, then generate POs.  Run: streamlit run app/review_app.py"""
from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from planner import outputs, review
from planner.common import PlannerError, load_config

ROOT = Path(__file__).resolve().parents[1]
OUT_BASE = Path(os.environ.get("FRESHROOTS_OUTPUTS", ROOT / "outputs"))
CONFIG = Path(os.environ.get("FRESHROOTS_CONFIG", ROOT / "config.yaml"))
DATA_DIR = ROOT / "data" / "raw"
UPLOADABLE = ["weekly_sales.csv", "sku_master.csv", "distributor_master.csv", "current_inventory.csv", "calendar.csv",
              "open_purchase_orders.csv", "sku_prices.csv", "distributor_sales.csv"]

st.set_page_config(page_title="Freshroots review", page_icon="🌿", layout="centered")
st.markdown("""
<style>
.block-container{padding-top:3.2rem;padding-bottom:4rem;max-width:760px}
.fr-badge{display:inline-block;font-size:.72rem;font-weight:600;border-radius:99px;padding:2px 9px;margin:2px 4px 2px 0;
  background:rgba(31,111,235,.14);color:#1f6feb}
.fr-badge.warn{background:rgba(217,119,6,.16);color:#c2670a}
.fr-badge.bad{background:rgba(209,69,59,.16);color:#d1453b}
.fr-badge.ok{background:rgba(46,160,67,.16);color:#2a9a43}
.fr-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.fr-grid div{background:rgba(128,128,128,.10);border-radius:10px;padding:8px 10px}
.fr-grid b{display:block;font-size:1.05rem}
.fr-grid span{font-size:.72rem;opacity:.7}
.fr-gauge{position:relative;height:12px;border-radius:99px;background:rgba(128,128,128,.18);margin:14px 0 4px}
.fr-band{position:absolute;top:0;bottom:0;border-radius:99px;background:rgba(46,160,67,.35)}
.fr-mark{position:absolute;top:-4px;width:6px;height:20px;border-radius:3px;transform:translateX(-3px)}
.fr-gl{font-size:.75rem;opacity:.75}
.fr-title{font-weight:650;font-size:1.02rem}
.fr-sub{opacity:.7;font-size:.82rem}
.st-key-stats [data-testid="stHorizontalBlock"]{flex-wrap:nowrap;gap:.4rem}
.st-key-stats [data-testid="stColumn"]{min-width:0;flex:1 1 0}
.st-key-stats [data-testid="stMetricValue"]{font-size:1.5rem}
.st-key-stats [data-testid="stMetricLabel"] p{font-size:.72rem}
[class*="st-key-actions_"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap;gap:.4rem}
[class*="st-key-actions_"] [data-testid="stColumn"]{min-width:0;flex:1 1 0}
[class*="st-key-actions_"] button p{font-size:.82rem;white-space:nowrap}
</style>
""", unsafe_allow_html=True)

cfg = load_config(CONFIG)


def list_runs() -> list[Path]:
    if not OUT_BASE.exists():
        return []
    return sorted((p for p in OUT_BASE.glob("*") if (p / "planning_table.csv").exists()), reverse=True)


def run_planner(uploads) -> None:
    """Run stages 1-6 on the bundled data, with any uploaded CSVs replacing the bundled ones."""
    import shutil
    import tempfile

    from planner.outputs import write_run
    from planner.pipeline import run_pipeline
    with tempfile.TemporaryDirectory() as tmp:
        for f in DATA_DIR.glob("*.csv"):
            shutil.copy(f, Path(tmp) / f.name)
        for up in uploads or []:
            (Path(tmp) / up.name).write_bytes(up.getvalue())
        result = run_pipeline(tmp, None, cfg)
        OUT_BASE.mkdir(parents=True, exist_ok=True)
        write_run(result, cfg, OUT_BASE)


# ---- header + run selection --------------------------------------------------------------
st.markdown("### 🌿 Freshroots planning")
runs = list_runs()
with st.expander("▶ Run planning" + ("  (start here)" if not runs else ""), expanded=not runs):
    st.caption("Uses the files in data/raw. Upload fresh SAP exports to replace any of them (same file names and columns).")
    uploads = st.file_uploader("Replace input files (optional)", type="csv", accept_multiple_files=True, key="uploads")
    bad = [u.name for u in uploads or [] if u.name not in UPLOADABLE]
    if bad:
        st.error(f"Unrecognised file name(s): {', '.join(bad)}. Expected: {', '.join(UPLOADABLE)}")
    if st.button("Run planning", type="primary", disabled=bool(bad), key="run_now", width="stretch"):
        try:
            run_planner(uploads)
            st.rerun()
        except PlannerError as e:
            st.error(str(e))
runs = list_runs()
if not runs:
    st.info("No runs yet. Open **Run planning** above and tap the button.")
    st.stop()

c1, c2 = st.columns([1, 1])
run_dir = c1.selectbox("Run", runs, format_func=lambda p: p.name)
reviewer = c2.text_input("Your name", key="reviewer", placeholder="Required to save decisions")

table = outputs.load_planning_table(run_dir)
log_path = run_dir / "review_log.csv"
decisions = review.latest_decisions(review.read_log(log_path))
decided = decisions.set_index("sku_id") if not decisions.empty else pd.DataFrame()
pending = review.pending_review(table, decisions)
needs = table[table.status == "NEEDS_REVIEW"]
auto = table[table.status == "AUTO_APPROVED"]
n_done = len(needs) - len(pending)

# ---- progress strip ----------------------------------------------------------------------
with st.container(key="stats"):
    s = st.columns(4)
    s[0].metric("SKUs", len(table))
    s[1].metric("To review", len(pending))
    s[2].metric("Auto", len(auto))
    s[3].metric("Decided", n_done)
if len(needs):
    st.progress(n_done / len(needs), text=f"{n_done} of {len(needs)} exceptions decided")


# ---- helpers -----------------------------------------------------------------------------
def fmt(v, d=0, sign=False, pct=False):
    if pd.isna(v):
        return "n/a"
    if pct:
        return f"{v:+.1%}" if sign else f"{v:.1%}"
    return f"{v:,.{d}f}"


def gauge(r) -> str:
    cover, after, mn, mx = r.weeks_of_cover, r.weeks_of_cover_after_order, r.min_weeks, r.max_weeks
    if any(pd.isna(x) for x in (cover, after, mn, mx)):
        return ""
    scale = max(mx * 1.25, cover * 1.05, after * 1.05)
    pos = lambda x: min(100.0, max(0.0, x / scale * 100))
    out_of_band = cover < mn or cover > mx
    now_col = "#d1453b" if out_of_band else "#2a9a43"
    return (f'<div class="fr-gauge"><div class="fr-band" style="left:{pos(mn):.1f}%;width:{pos(mx) - pos(mn):.1f}%"></div>'
            f'<div class="fr-mark" style="left:{pos(cover):.1f}%;background:{now_col}"></div>'
            + (f'<div class="fr-mark" style="left:{pos(after):.1f}%;background:#1f6feb;opacity:.85"></div>' if abs(after - cover) > 0.05 else "")
            + f'</div><div class="fr-gl">Weeks of cover: <b style="color:{now_col}">now {cover:.2f}</b>'
            + (f' · <b style="color:#1f6feb">after order {after:.2f}</b>' if abs(after - cover) > 0.05 else "")
            + f' · safe band {mn:g}–{mx:g}</div>')


def badges(r) -> str:
    out = []
    if r.is_urgent:
        out.append('<span class="fr-badge bad">URGENT</span>')
    for code in (r.exceptions.split("; ") if r.exceptions else []):
        cls = "bad" if code in ("BELOW_MIN_AFTER_ORDER", "SHARP_DROP", "DATA_ISSUE") else "warn"
        out.append(f'<span class="fr-badge {cls}">{escape(code)}</span>')
    if r.flag != "NOT_PLANNED":
        out.append(f'<span class="fr-badge">{escape(r.flag)}</span>')
    return "".join(out)


def decide(sku: str, system_qty: float, decision: str, qty: float | None = None, note: str = "") -> None:
    try:
        review.append_log(log_path, [review.make_decision(sku, system_qty, decision, reviewer, final_qty=qty, note=note)])
    except PlannerError as e:
        st.error(str(e))
        return
    st.rerun()


def line_card(r, prefix: str) -> None:
    sku = r.sku_id
    cur = decided.loc[sku] if len(decided) and sku in decided.index else None
    with st.container(border=True):
        st.markdown(f'<div class="fr-title">{escape(sku)} · {escape(r.sku_name)}</div>'
                    f'<div class="fr-sub">{escape(r.distributor_name or r.distributor_id)} · {escape(r.perishability or "n/a")} perishability</div>'
                    f'{badges(r)}', unsafe_allow_html=True)
        st.markdown(gauge(r), unsafe_allow_html=True)
        st.markdown(f'<div class="fr-grid">'
                    f'<div><b>{fmt(r.units_on_hand)}</b><span>On hand</span></div>'
                    f'<div><b>{fmt(r.change_4w_vs_12w, sign=True, pct=True)}</b><span>4w vs 12w demand</span></div>'
                    f'<div><b>{fmt(r.order_qty)}</b><span>System order qty</span></div></div>', unsafe_allow_html=True)
        st.caption(f"Rule: {r.flag_reasons}")
        for part in (str(r.exception_reasons).split(" | ") if r.exception_reasons else []):
            st.warning(part, icon="⚠️")
        has_sug = pd.notna(r.suggested_qty)
        if has_sug:
            st.info(f"Suggested alternative: **{r.suggested_qty:,.0f}** units. {r.suggested_note}", icon="💡")
        if cur is not None:
            st.success(f"{cur.decision.title()}: {cur.final_qty:,.0f} units by {cur.reviewer}" + (f" · “{cur.note}”" if cur.note else ""), icon="✅")
        note = st.text_input("Note (optional)", key=f"{prefix}_note_{sku}")
        actions = st.container(key=f"actions_{prefix}_{sku}")
        cols = actions.columns(3 if has_sug else 2)
        if cols[0].button((f"✓ {r.order_qty:,.0f}" if has_sug else f"✓ Approve {r.order_qty:,.0f}"), key=f"{prefix}_approve_{sku}", width="stretch", type="primary"):
            decide(sku, r.order_qty, "approve", note=note)
        i = 1
        if has_sug and cols[i].button(f"Use {r.suggested_qty:,.0f}", key=f"{prefix}_suggest_{sku}", width="stretch"):
            decide(sku, r.order_qty, "edit", qty=float(r.suggested_qty), note=note or "Used suggested quantity")
        if has_sug:
            i += 1
        if cols[i].button("✕ Reject", key=f"{prefix}_reject_{sku}", width="stretch"):
            decide(sku, r.order_qty, "reject", note=note)
        with st.expander("Edit quantity"):
            default = int(r.suggested_qty) if has_sug else int(r.order_qty)
            qty = st.number_input("Quantity", min_value=0, step=1, value=default, key=f"{prefix}_qty_{sku}")
            if st.button("Save edited quantity", key=f"{prefix}_saveedit_{sku}", width="stretch"):
                decide(sku, r.order_qty, "edit", qty=float(qty), note=note)


# ---- tabs --------------------------------------------------------------------------------
t_review, t_orders, t_auto, t_all = st.tabs([f"Review ({len(pending)})", "Orders", f"Auto ({len(auto)})", "All SKUs"])

with t_review:
    if needs.empty:
        st.success("No exceptions this run.")
    elif not pending:
        st.success("All exceptions decided. Go to **Orders** to generate the POs.", icon="🎉")
    for r in needs.assign(_done=needs.sku_id.isin(pending).map({True: 0, False: 1})).sort_values(
            ["_done", "is_urgent", "sku_id"], ascending=[True, False, True]).itertuples():
        line_card(r, "exc")

with t_orders:
    blocked = bool(pending)
    if blocked:
        st.error(f"Cannot generate POs yet: {len(pending)} exception(s) still need a decision ({', '.join(pending)}).")
    st.caption("Auto-approved lines you haven't touched go on the PO at the system quantity.")
    if st.button("Generate purchase orders", type="primary", disabled=blocked, key="generate", width="stretch"):
        try:
            if not reviewer.strip():
                raise PlannerError("Enter your name at the top of the page first")
            decided_ids = set(decisions.sku_id) if not decisions.empty else set()
            undecided_auto = auto[~auto.sku_id.isin(decided_ids)]
            review.append_log(log_path, [review.make_decision(r.sku_id, r.order_qty, "approve", review.AUTO_REVIEWER) for r in undecided_auto.itertuples()])
            outputs.finalize_run(run_dir, cfg)
            st.rerun()
        except PlannerError as e:
            st.error(str(e))

    # Downloads are read from the run folder, so they survive reruns (a download click reruns the page).
    if (run_dir / "sourcing_handoff.md").exists():
        rl = json.loads((run_dir / "run_log.json").read_text())
        st.success(f"{rl.get('po_count', 0)} PO(s) · {rl.get('po_line_count', 0)} line(s) · {rl.get('lines_held_back', 0)} held back", icon="📦")
        rate = rl.get("override_rate")
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
        line_card(r, "auto")

with t_all:
    show = table[["sku_id", "sku_name", "perishability", "weeks_of_cover", "change_4w_vs_12w", "flag", "order_qty",
                  "weeks_of_cover_after_order", "forecast_total_4w", "status", "exceptions"]]
    st.dataframe(show, width="stretch", hide_index=True, column_config={
        "weeks_of_cover": st.column_config.NumberColumn("Cover (wks)", format="%.2f"),
        "weeks_of_cover_after_order": st.column_config.NumberColumn("After order", format="%.2f"),
        "change_4w_vs_12w": st.column_config.NumberColumn("4w vs 12w", format="percent"),
        "forecast_total_4w": st.column_config.NumberColumn("4-wk forecast", format="%.0f"),
        "order_qty": st.column_config.NumberColumn("Order qty", format="%.0f")})
    flag_counts = pd.Series([f for v in table.flag for f in str(v).split(" + ")]).value_counts()
    st.caption("Flags: " + " · ".join(f"{k} {v}" for k, v in flag_counts.items()))
