"""Per-line cards for the review screen. Rendering only; saving goes through the `save` callback."""
from __future__ import annotations

from collections.abc import Callable
from html import escape

import fr_html as fr
import pandas as pd
import streamlit as st

# save(sku, system_qty, action, qty, note) records a decision and reruns the page
Save = Callable[[str, float, str, float, str], None]

DECISION_LABEL = {"approve": "Approved", "edit": "Changed", "reject": "Rejected"}
NEED_NAME = "Enter your name at the top first, then tap again."


def _parts(r) -> list[tuple[str, str]]:
    """(code, reason) for each exception, split from 'CODE: reason | CODE: reason'."""
    chunks = r.exception_reasons.split(" | ") if r.exception_reasons else []
    return [(c, reason) for c, _, reason in (chunk.partition(": ") for chunk in chunks)]


def _planned(r) -> bool:
    return pd.notna(r.weeks_of_cover) and pd.notna(r.adjusted_weekly_demand)


def cover_after(r, qty: float) -> float:
    """Cover once `qty` arrives, from the pipeline's own festival-adjusted weekly demand."""
    return r.weeks_of_cover + qty / r.adjusted_weekly_demand


def _price(r) -> float | None:
    return float(r.unit_price) if pd.notna(r.unit_price) else None


def _head(r) -> str:
    """Name, supplier, category and price (or 'not in data'), plus URGENT."""
    price = _price(r)
    price_txt = f"₹{price:,.2f} per unit" if price is not None else "Price not in data"
    extra = f'<p class="fr-meta">{escape(r.category or "No category")} · {price_txt}</p>'
    return fr.card_head_b(r.sku_id, r.sku_name, r.distributor_name or r.distributor_id, r.perishability == "High",
                          bool(r.is_urgent) and _planned(r), "", "", extra=extra)


def _table(r) -> str:
    """Now vs what the rules say vs the suggestion, one column each."""
    if not _planned(r):
        return ""
    pos, system = r.inventory_position, int(r.order_qty)
    cols = [("Now", None, pos, r.weeks_of_cover), ("Rules say", system, pos + system, cover_after(r, system))]
    if pd.notna(r.suggested_qty):
        sug = int(r.suggested_qty)
        cols.append(("Suggested", sug, pos + sug, cover_after(r, sug)))
    return fr.compare_table(cols, r.min_weeks, r.max_weeks, _price(r))


def _facts(r) -> str:
    change = 0.0 if pd.isna(r.change_4w_vs_12w) else r.change_4w_vs_12w * 100
    std = int(r.standard_reorder_qty) if pd.notna(r.standard_reorder_qty) else 0
    return fr.facts2(change, std, [f for f in r.flag.split(" + ") if f])


def _current(cur) -> str:
    return fr.current_decision(DECISION_LABEL[cur.decision], int(cur.final_qty), cur.reviewer, str(cur.timestamp), cur.note)


def _set(key: str, value: int) -> None:
    st.session_state[key] = value


def _preview(r, qty: int) -> str:
    """One line under the quantity box: what that quantity does to stock."""
    if not _planned(r):
        return ""
    c = cover_after(r, qty)
    word = {"below": "below the safe range", "in": "inside the safe range", "above": "above the safe range"}[fr._status(c, r.min_weeks, r.max_weeks)[0]]
    return f"With {qty:,} units, stock lasts {fr.wk(c, r.min_weeks, r.max_weeks)} weeks: {word}."


def decision_bar(r, reviewer: str, save: Save, default_qty: int | None = None) -> None:
    """Quantity box next to ONE button: it approves the rules' quantity, or saves your changed quantity as an edit."""
    sku, system = r.sku_id, int(r.order_qty)
    has_sug = pd.notna(r.suggested_qty)
    qkey = f"qty-{sku}"
    if qkey not in st.session_state:
        st.session_state[qkey] = system if default_qty is None else int(default_qty)
    note = st.text_input("Note (optional)", key=f"note-{sku}", placeholder="Why, e.g. promo confirmed with sales")

    def go(action: str, qty: int) -> None:
        if not reviewer.strip():
            st.error(NEED_NAME)
            return
        save(sku, r.order_qty, action, float(qty), note)

    with st.container(key=f"bar-{sku}"):
        box, main = st.columns([2, 3])
        qty = int(box.number_input("Quantity (units)", min_value=0, step=1, key=qkey, label_visibility="collapsed"))
        changed = qty != system
        label = f"Save · {qty:,} (changed)" if changed else (f"Approve · {system:,}" if system else "Approve · 0 (paused)")
        if main.button(label, key=f"go-{sku}", type="primary", width="stretch",
                       help="Accept the rules' quantity, or save the quantity you typed instead."):
            go("edit" if changed else "approve", qty)
    st.caption(_preview(r, qty))
    with st.container(key=f"alt-{sku}"):
        cols = st.columns(2 if has_sug else 1)
        if has_sug:
            sug = int(r.suggested_qty)
            cols[0].button(f"Use suggested · {sug:,}", key=f"sug-{sku}", width="stretch", on_click=_set, args=(qkey, sug),
                           help="Put the suggested quantity in the box. Then tap the green button to save it.")
        if cols[-1].button("Reject · 0", key=f"rej-{sku}", width="stretch",
                           help="Do not order this product this run. Logged as an override if the system quantity was above 0."):
            go("reject", 0)


def open_card(r, cur, reopened: bool, reviewer: str, save: Save) -> None:
    sku = r.sku_id
    with st.container(border=True, key=f"card-open-{sku}"):
        st.markdown(_head(r) + _table(r), unsafe_allow_html=True)
        st.markdown("".join(fr.callout(code, reason) for code, reason in _parts(r)), unsafe_allow_html=True)
        if reopened and cur is not None:
            st.markdown(_current(cur), unsafe_allow_html=True)
        decision_bar(r, reviewer, save, int(cur.final_qty) if reopened and cur is not None else None)
        st.markdown(_facts(r), unsafe_allow_html=True)
        with st.expander("How the rules decided"):
            st.write(r.flag_reasons)


def done_card(r, cur, reopen: Callable[[str], None]) -> None:
    sku = r.sku_id
    with st.container(border=True, key=f"card-done-{sku}"):
        st.markdown(fr.done(sku, r.sku_name, DECISION_LABEL[cur.decision], int(cur.final_qty), int(r.order_qty),
                            cur.reviewer, str(cur.timestamp), cur.note), unsafe_allow_html=True)
        if st.button("Change decision", key=f"change-{sku}", width="stretch"):
            reopen(sku)


def auto_card(r, cur, reviewer: str, save: Save) -> None:
    sku = r.sku_id
    with st.container(border=True, key=f"card-auto-{sku}"):
        st.markdown(_head(r) + _table(r), unsafe_allow_html=True)
        if cur is not None and not str(cur.reviewer).startswith("system:"):
            st.markdown(_current(cur), unsafe_allow_html=True)
        else:
            st.caption(f"Goes into the PO at {int(r.order_qty):,} units. No decision needed; change the quantity only if you disagree.")
        decision_bar(r, reviewer, save)
        st.markdown(_facts(r), unsafe_allow_html=True)
        with st.expander("How the rules decided"):
            st.write(r.flag_reasons)
