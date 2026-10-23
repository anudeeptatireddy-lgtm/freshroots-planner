"""Per-line cards for the review screen (design: card option B). Rendering only; saving goes through the `save` callback."""
from __future__ import annotations

from collections.abc import Callable

import fr_html as fr
import pandas as pd
import streamlit as st

# save(sku, system_qty, action, qty, note) records a decision and reruns the page
Save = Callable[[str, float, str, float, str], None]

DECISION_LABEL = {"approve": "Approved", "edit": "Changed", "reject": "Rejected"}


def _parts(r) -> list[tuple[str, str]]:
    """(code, reason) for each exception, split from 'CODE: reason | CODE: reason'."""
    chunks = r.exception_reasons.split(" | ") if r.exception_reasons else []
    return [(c, reason) for c, _, reason in (chunk.partition(": ") for chunk in chunks)]


def _planned(r) -> bool:
    return pd.notna(r.weeks_of_cover) and pd.notna(r.adjusted_weekly_demand)


def cover_after(r, qty: float) -> float:
    """Cover once `qty` arrives, from the pipeline's own festival-adjusted weekly demand."""
    return r.weeks_of_cover + qty / r.adjusted_weekly_demand


def options_for(r) -> list[tuple[str, str, int, float | None]]:
    """(label, action, qty, cover_after) in display order; the first is the primary button."""
    system = int(r.order_qty)
    out = []
    if pd.notna(r.suggested_qty):
        sug = int(r.suggested_qty)
        out.append((f"Use suggested · {sug:,}", "edit", sug, cover_after(r, sug) if _planned(r) else None))
    approve = f"Approve · {system:,}" if system else "Approve · 0 (paused)"
    out.append((approve, "approve", system, cover_after(r, system) if _planned(r) else None))
    out.append(("Reject · 0", "reject", 0, r.weeks_of_cover if _planned(r) else None))
    return out


def _head(r) -> str:
    """Name, supplier and URGENT only: the facts are in the table below."""
    return fr.card_head_b(r.sku_id, r.sku_name, r.distributor_name or r.distributor_id, r.perishability == "High",
                          bool(r.is_urgent) and _planned(r), "", "")


def _table(r) -> str:
    """Now vs what the rules say vs the suggestion, one column each."""
    if not _planned(r):
        return ""
    pos, system = r.inventory_position, int(r.order_qty)
    cols = [("Now", None, pos, r.weeks_of_cover), ("Rules say", system, pos + system, cover_after(r, system))]
    if pd.notna(r.suggested_qty):
        sug = int(r.suggested_qty)
        cols.append(("Suggested", sug, pos + sug, cover_after(r, sug)))
    return fr.compare_table(cols, r.min_weeks, r.max_weeks)


def _facts(r) -> str:
    change = 0.0 if pd.isna(r.change_4w_vs_12w) else r.change_4w_vs_12w * 100
    std = int(r.standard_reorder_qty) if pd.notna(r.standard_reorder_qty) else 0
    return fr.facts2(change, std, [f for f in r.flag.split(" + ") if f])


def _current(cur) -> str:
    return fr.current_decision(DECISION_LABEL[cur.decision], int(cur.final_qty), cur.reviewer, str(cur.timestamp), cur.note)


def _edit_quantity(r, default: int, note: str, save: Save, reviewer: str) -> None:
    with st.expander("Edit quantity"):
        qty = st.number_input("Order quantity (units)", min_value=0, step=1, value=default, key=f"qty-{r.sku_id}")
        if st.button(f"Save · {int(qty):,}", key=f"save-{r.sku_id}", width="stretch", disabled=not reviewer.strip()):
            save(r.sku_id, r.order_qty, "edit", float(qty), note)


def open_card(r, cur, reopened: bool, reviewer: str, save: Save) -> None:
    sku = r.sku_id
    with st.container(border=True, key=f"card-open-{sku}"):
        st.markdown(_head(r) + _table(r), unsafe_allow_html=True)
        st.markdown("".join(fr.callout(code, reason) for code, reason in _parts(r)), unsafe_allow_html=True)
        st.markdown(_facts(r), unsafe_allow_html=True)
        with st.expander("How the rules decided"):
            st.write(r.flag_reasons)
        if reopened and cur is not None:
            st.markdown(_current(cur), unsafe_allow_html=True)
        note = st.text_input("Note (optional)", key=f"note-{sku}", placeholder="Why, e.g. promo confirmed with sales")
        st.markdown(fr.DECISION_HEAD, unsafe_allow_html=True)
        for i, (label, action, qty, after) in enumerate(options_for(r)):
            with st.container(key=f"opt-{sku}-{i}"):
                b, o = st.columns([3, 2])
                if b.button(label, key=f"btn-{sku}-{i}", type="primary" if i == 0 else "secondary", width="stretch",
                            disabled=not reviewer.strip()):
                    save(sku, r.order_qty, action, float(qty), note)
                if after is None:
                    o.markdown('<div class="fr-outcome"><b>n/a</b></div>', unsafe_allow_html=True)
                else:
                    o.markdown(fr.outcome(after, r.min_weeks, r.max_weeks), unsafe_allow_html=True)
        if not reviewer.strip():
            st.caption("Add your name at the top to save decisions.")
        _edit_quantity(r, int(r.suggested_qty) if pd.notna(r.suggested_qty) else int(r.order_qty), note, save, reviewer)


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
        st.markdown(_facts(r), unsafe_allow_html=True)
        with st.expander("How the rules decided"):
            st.write(r.flag_reasons)
        if cur is not None and not str(cur.reviewer).startswith("system:"):
            st.markdown(_current(cur), unsafe_allow_html=True)
        else:
            st.caption(f"Goes into the PO at {int(r.order_qty):,} units. No decision needed.")
        note = st.text_input("Note (optional)", key=f"note-{sku}", placeholder="Only if you change it")
        _edit_quantity(r, int(r.order_qty), note, save, reviewer)
