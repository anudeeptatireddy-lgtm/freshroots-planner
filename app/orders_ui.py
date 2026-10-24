"""Orders tab: generate the POs, then downloads, the PO table and the Send to Zoho section."""
from __future__ import annotations

import json
import os
from pathlib import Path

import fr_html as fr
import pandas as pd
import streamlit as st
from cards import NEED_NAME

from planner import outputs, zoho
from planner.common import PlannerError


def secret(name: str) -> str:
    """A secret from Streamlit Secrets or the environment; empty string if absent."""
    try:
        v = st.secrets[name]
    except Exception:
        v = os.environ.get(name, "")
    return str(v or "")


def zoho_values() -> dict[str, str]:
    return {k: secret(k) for k in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_DC", "ZOHO_ORG_ID")}


def render_zoho(run_dir: Path, cfg: dict, sync_up) -> None:
    """Send to Zoho: always a dry-run preview; live sending only when config and credentials allow it."""
    zoho_csv = run_dir / "purchase_orders_zoho_import.csv"
    if not zoho_csv.exists():
        return
    st.markdown("#### Send to Zoho")
    drafts = zoho.build_drafts(zoho_csv, cfg)
    if st.button("Preview Zoho drafts (dry run)", key="zoho_preview", width="stretch",
                 help="Shows exactly what would be created in Zoho. Nothing is sent."):
        zoho.write_preview(run_dir, zoho.send(drafts, dry_run=True), zoho.check_drafts(drafts))
        sync_up(run_dir)
        st.rerun()
    preview = run_dir / zoho.PREVIEW_FILE
    if preview.exists():
        data = json.loads(preview.read_text())
        st.success("Preview only: nothing was sent to Zoho.", icon="🔒")
        for r in data["purchase_orders"]:
            with st.container(border=True):
                st.markdown(f"**{r['po_number']}** → {r['vendor']}  \n{r['lines']} lines · {r['units']:,} units · would be created as a **draft**")
                st.dataframe(pd.DataFrame(r["payload"]["line_items"]), width="stretch", hide_index=True)
        if data["issues"]:
            st.warning("**Before you send**\n\n" + "\n".join(f"- {i}" for i in data["issues"]))
        st.download_button("Zoho preview (JSON)", preview.read_bytes(), file_name=preview.name, mime="application/json", key="dl_zoho_preview", width="stretch")
    settings = zoho.settings_from(zoho_values())
    live_ok = settings is not None and not cfg.get("zoho", {}).get("dry_run_only", True)
    if st.button("Send to Zoho", key="zoho_send", type="primary", disabled=not live_ok, width="stretch",
                 help="Creates the POs as drafts in Zoho. Locked until dry_run_only is false in config.yaml and Zoho credentials are saved."):
        results = zoho.send(drafts, dry_run=False, client=zoho.ZohoClient(settings))
        for r in results:
            (st.success if r["status"] == "created" else st.error)(f"{r['po_number']}: {r['detail']}")
        st.caption("Check the first draft in Zoho by hand before releasing it.")
    if not live_ok:
        have = zoho.credentials_status(zoho_values())
        st.caption("Sending is locked (dry run only). " + "Credentials: " + ", ".join(f"{k.removeprefix('ZOHO_').lower().replace('_', ' ')} {'✓' if v else '✗'}" for k, v in have.items()) + ".")


def render_orders(run_dir: Path, cfg: dict, table: pd.DataFrame, needs: pd.DataFrame, auto: pd.DataFrame, pending: list[str],
                  decided: pd.DataFrame, reviewer: str, log_path: Path, sync_up) -> None:
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
                    raise PlannerError(NEED_NAME)
                outputs.generate_pos(run_dir, cfg)
                sync_up(run_dir)
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
        zoho_file = run_dir / "purchase_orders_zoho_import.csv"
        if zoho_file.exists():
            zc = cfg["po"]["zoho_columns"]
            z = pd.read_csv(zoho_file)
            st.download_button("Download Zoho import (CSV)", zoho_file.read_bytes(), file_name=zoho_file.name, mime="text/csv", type="primary",
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
        render_zoho(run_dir, cfg, sync_up)
        st.download_button("Sourcing handoff note", (run_dir / "sourcing_handoff.md").read_bytes(), file_name="sourcing_handoff.md",
                           key="dl_handoff", width="stretch")
        st.download_button("Review log (CSV)", log_path.read_bytes(), file_name=f"review_log_{run_dir.name}.csv", key="dl_log2", width="stretch",
                           help="Hosted disks are wiped on restart: keep a copy after each review.")
