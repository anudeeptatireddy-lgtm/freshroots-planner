"""Page header with the corner Upload button (adding SAP files starts a new run straight away)."""
from __future__ import annotations

import fr_html as fr
import streamlit as st
from workspace import Workspace

REQUIRED = ["weekly_sales.csv", "sku_master.csv", "distributor_master.csv", "current_inventory.csv", "calendar.csv"]
OPTIONAL = ["open_purchase_orders.csv", "sku_prices.csv", "distributor_sales.csv"]


def upload_corner(ws: Workspace) -> None:
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
            ws.start_run(ups)


def render_header(ws: Workspace, slot, line: str) -> None:
    """`slot` is a container created at the top of the page, so the header lands there even when drawn later."""
    with slot:
        left, right = st.columns([5, 2])
        left.markdown(f'<h1 class="fr-title">Freshroots demand planning</h1><p class="fr-sub">{line}</p>', unsafe_allow_html=True)
        with right:
            upload_corner(ws)
