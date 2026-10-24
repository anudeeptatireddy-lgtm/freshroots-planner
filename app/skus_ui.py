"""All SKUs tab: one table of every product with a status filter."""
from __future__ import annotations

import fr_html as fr
import pandas as pd
import streamlit as st

from planner.common import STATUS_AUTO, STATUS_REVIEW


def render_all_skus(table: pd.DataFrame, needs: pd.DataFrame, auto: pd.DataFrame) -> None:
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
