"""Reusable UI pieces for the review page: HTML fragments and the per-line decision card."""
from __future__ import annotations

from collections.abc import Callable
from html import escape

import pandas as pd
import streamlit as st
from glossary import Glossary

BAD_EXCEPTIONS = {"BELOW_MIN_AFTER_ORDER", "SHARP_DROP", "DATA_ISSUE"}


def fmt(v, d: int = 0, sign: bool = False, pct: bool = False) -> str:
    if pd.isna(v):
        return "n/a"
    if pct:
        return f"{v:+.1%}" if sign else f"{v:.1%}"
    return f"{v:,.{d}f}"


def gauge(r, g: Glossary) -> str:
    """Bar of weeks of cover: green safe band, now marker and after-order marker."""
    cover, after, mn, mx = r.weeks_of_cover, r.weeks_of_cover_after_order, r.min_weeks, r.max_weeks
    if any(pd.isna(x) for x in (cover, after, mn, mx)):
        return ""
    scale = max(mx * 1.25, cover * 1.05, after * 1.05)

    def pos(x: float) -> float:
        return min(100.0, max(0.0, x / scale * 100))

    moved = abs(after - cover) > 0.05
    now_col = "#d1453b" if cover < mn or cover > mx else "#2a9a43"
    after_marker = f'<div class="fr-mark" style="left:{pos(after):.1f}%;background:#1f6feb;opacity:.85"></div>' if moved else ""
    after_label = f' · <b style="color:#1f6feb">after order {after:.2f}</b>{g.term_tip("after order")}' if moved else ""
    return (f'<div class="fr-gauge"><div class="fr-band" style="left:{pos(mn):.1f}%;width:{pos(mx) - pos(mn):.1f}%"></div>'
            f'<div class="fr-mark" style="left:{pos(cover):.1f}%;background:{now_col}"></div>{after_marker}</div>'
            f'<div class="fr-gl">Weeks of cover{g.term_tip("Weeks of cover")}: <b style="color:{now_col}">now {cover:.2f}</b>'
            f'{after_label} · safe band {mn:g}–{mx:g}{g.term_tip("safe band", right=True)}</div>')


def badges(r, g: Glossary) -> str:
    out = []
    if r.is_urgent:
        out.append(f'<span class="fr-badge bad">URGENT{g.flag_tip("URGENT")}</span>')
    for code in (r.exceptions.split("; ") if r.exceptions else []):
        cls = "bad" if code in BAD_EXCEPTIONS else "warn"
        out.append(f'<span class="fr-badge {cls}">{escape(code)}{g.flag_tip(code)}</span>')
    if r.flag != "NOT_PLANNED":
        tips = "".join(g.flag_tip(f) for f in r.flag.split(" + "))
        out.append(f'<span class="fr-badge">{escape(r.flag)}{tips}</span>')
    return "".join(out)


def _tiles(r, g: Glossary) -> str:
    tile = lambda value, label, **kw: f"<div><b>{value}</b><span>{label}{g.term_tip(label, **kw)}</span></div>"  # noqa: E731
    return ('<div class="fr-grid">' + tile(fmt(r.units_on_hand), "On hand")
            + tile(fmt(r.change_4w_vs_12w, sign=True, pct=True), "4w vs 12w demand")
            + tile(fmt(r.order_qty), "System order qty", right=True) + "</div>")


# decide(sku, system_qty, decision, qty=None, note="") records a decision and reruns the page
Decide = Callable[..., None]


def line_card(r, prefix: str, g: Glossary, decided: pd.DataFrame, decide: Decide) -> None:
    """One SKU: facts, why it is here, and one-tap Approve / Use suggested / Reject / Edit."""
    sku = r.sku_id
    cur = decided.loc[sku] if len(decided) and sku in decided.index else None
    has_sug = pd.notna(r.suggested_qty)
    with st.container(border=True):
        st.markdown(f'<div class="fr-title">{escape(sku)} · {escape(r.sku_name)}</div>'
                    f'<div class="fr-sub">{escape(r.distributor_name or r.distributor_id)} · {escape(r.perishability or "n/a")} perishability</div>'
                    f'{badges(r, g)}', unsafe_allow_html=True)
        st.markdown(gauge(r, g), unsafe_allow_html=True)
        st.markdown(_tiles(r, g), unsafe_allow_html=True)
        st.caption(f"Rule: {r.flag_reasons}")
        for part in (str(r.exception_reasons).split(" | ") if r.exception_reasons else []):
            st.warning(part, icon="⚠️")
        if has_sug:
            st.info(f"Suggested alternative: **{r.suggested_qty:,.0f}** units. {r.suggested_note}", icon="💡")
        if cur is not None:
            st.success(f"{cur.decision.title()}: {cur.final_qty:,.0f} units by {cur.reviewer}" + (f" · “{cur.note}”" if cur.note else ""), icon="✅")
        note = st.text_input("Note (optional)", key=f"{prefix}_note_{sku}", help="Saved in the review log with your decision, e.g. why you changed the quantity.")
        cols = st.container(key=f"actions_{prefix}_{sku}").columns(3 if has_sug else 2)
        approve_label = f"✓ {r.order_qty:,.0f}" if has_sug else f"✓ Approve {r.order_qty:,.0f}"
        if cols[0].button(approve_label, key=f"{prefix}_approve_{sku}", width="stretch", type="primary", help="Accept the rules' quantity as it is."):
            decide(sku, r.order_qty, "approve", note=note)
        if has_sug and cols[1].button(f"Use {r.suggested_qty:,.0f}", key=f"{prefix}_suggest_{sku}", width="stretch",
                                      help="Order the suggested quantity instead (the amount that reaches the minimum weeks of cover)."):
            decide(sku, r.order_qty, "edit", qty=float(r.suggested_qty), note=note or "Used suggested quantity")
        if cols[-1].button("✕ Reject", key=f"{prefix}_reject_{sku}", width="stretch",
                           help="Do not order this product this run. It is logged as an override if the system quantity was above 0."):
            decide(sku, r.order_qty, "reject", note=note)
        with st.expander("Edit quantity"):
            default = int(r.suggested_qty) if has_sug else int(r.order_qty)
            qty = st.number_input("Quantity", min_value=0, step=1, value=default, key=f"{prefix}_qty_{sku}", help="Your own order quantity, in whole units.")
            if st.button("Save edited quantity", key=f"{prefix}_saveedit_{sku}", width="stretch"):
                decide(sku, r.order_qty, "edit", qty=float(qty), note=note)
