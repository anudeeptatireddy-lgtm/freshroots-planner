"""Rows view: every line in one editable table, so many decisions can be made and saved at once."""
from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import streamlit as st
from cards import NEED_NAME

# apply_many([(sku, system_qty, action, qty, note), ...]) saves decisions in one go and reruns the page
ApplyMany = Callable[[list[tuple[str, float, str, float, str]]], None]
EDITABLE = ("Final qty", "Decision", "Note")


def _current_values(sku: str, system: int, decided: pd.DataFrame) -> tuple[str, int, str]:
    if len(decided) and sku in decided.index:
        cur = decided.loc[sku]
        return ("Reject" if cur.decision == "reject" else "Approve"), int(cur.final_qty), str(cur.note)
    return "Pending", system, ""


def compute_changes(old_rows: list[dict], new_rows: list[dict]) -> list[tuple[str, float, str, float, str]]:
    """Decisions to save: rows whose Decision is not Pending and that differ from what was last saved."""
    changes = []
    for old, new in zip(old_rows, new_rows, strict=True):
        if new["Decision"] == "Pending":
            continue
        qty = 0 if new["Decision"] == "Reject" else int(new["Final qty"] if pd.notna(new["Final qty"]) else new["Rules"])
        note = new["Note"] or ""
        old_qty = 0 if old["Decision"] == "Reject" else old["Final qty"]
        if (new["Decision"], qty, note) == (old["Decision"], old_qty, old["Note"]):
            continue                                          # unchanged since it was last saved
        action = "reject" if new["Decision"] == "Reject" else ("approve" if qty == new["Rules"] else "edit")
        changes.append((new["SKU"], float(new["Rules"]), action, float(qty), note))
    return changes


def rows_view(lines: pd.DataFrame, decided: pd.DataFrame, reviewer: str, apply_many: ApplyMany, label: str) -> None:
    if lines.empty:
        st.info("Nothing here.")
        return
    records = []
    for r in lines.itertuples():
        decision, qty, note = _current_values(r.sku_id, int(r.order_qty), decided)
        records.append({"SKU": r.sku_id, "Product": r.sku_name, "Category": r.category, "On hand": r.units_on_hand,
                        "Cover wk": r.weeks_of_cover, "Rules": int(r.order_qty),
                        "Suggested": None if pd.isna(r.suggested_qty) else int(r.suggested_qty),
                        "Final qty": qty, "Decision": decision, "Note": note})
    # what you act on first, so it is on screen on a phone; the descriptive columns scroll to the right
    base = pd.DataFrame(records)[["SKU", "Rules", "Suggested", "Final qty", "Decision", "Cover wk", "On hand", "Product", "Category", "Note"]]
    ver = st.session_state.setdefault("rows_ver", 0)
    st.caption("Set Decision to Approve or Reject (change Final qty if you disagree), then tap Save. Pending rows are left as they are.")
    edited = st.data_editor(
        base, key=f"rows-{label}-{ver}", hide_index=True, width="stretch", num_rows="fixed",
        disabled=[c for c in base.columns if c not in EDITABLE],
        column_config={
            "SKU": st.column_config.TextColumn(pinned=True),
            "On hand": st.column_config.NumberColumn(format="%d"),
            "Cover wk": st.column_config.NumberColumn(format="%.1f", help="Weeks the current stock lasts."),
            "Rules": st.column_config.NumberColumn(format="%d", help="What the rules recommend ordering."),
            "Suggested": st.column_config.NumberColumn(format="%d", help="Suggested alternative quantity, when there is one."),
            "Final qty": st.column_config.NumberColumn(min_value=0, step=1, format="%d", help="The quantity that will be saved."),
            "Decision": st.column_config.SelectboxColumn(options=["Pending", "Approve", "Reject"], required=True),
            "Note": st.column_config.TextColumn(),
        })
    if st.button("Save decisions", type="primary", width="stretch", key=f"rows-save-{label}"):
        if not reviewer.strip():
            st.error(NEED_NAME)
            return
        changes = compute_changes(base.to_dict("records"), edited.to_dict("records"))
        if not changes:
            st.warning("Nothing to save: set a Decision on at least one row.")
            return
        st.session_state.rows_ver = ver + 1
        apply_many(changes)
