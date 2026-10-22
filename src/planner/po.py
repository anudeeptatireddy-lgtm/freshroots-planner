"""Stage 8a: group approved lines into POs, write the Zoho import CSV and a PDF per PO."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_po_lines(table: pd.DataFrame, decisions: pd.DataFrame, cfg: dict, run_date: dt.date) -> pd.DataFrame:
    """One row per PO line (approved, final qty > 0), numbered by counterparty."""
    cols = ["po_number", "po_date", "vendor_id", "vendor_name", "sku_id", "item_name", "quantity", "unit",
            "unit_price", "notes", "is_urgent"]
    if decisions is None or decisions.empty:
        return pd.DataFrame(columns=cols)
    pc = cfg["po"]
    t = table.merge(decisions[["sku_id", "final_qty", "decision", "reviewer", "note", "system_qty"]], on="sku_id")
    t = t[(t.final_qty > 0) & (t.decision != "reject")].copy()
    if t.empty:
        return pd.DataFrame(columns=cols)
    ov = pc.get("vendor_overrides") or {}

    def vendor(r):
        key = r[pc["counterparty_column"]]
        o = ov.get(key, {})
        return o.get("vendor_id", key), o.get("vendor_name", r["distributor_name"])

    t[["vendor_id", "vendor_name"]] = [vendor(r) for r in t.to_dict("records")]
    t = t.sort_values(["vendor_id", "is_urgent", "sku_id"], ascending=[True, False, True])
    nums = {v: f"{pc['po_prefix']}-{run_date:%Y%m%d}-{i:02d}" for i, v in enumerate(sorted(t.vendor_id.unique()), start=1)}
    t["po_number"] = t.vendor_id.map(nums)

    def notes(r):
        parts = []
        if r["is_urgent"]:
            parts.append("URGENT - stockout risk")
        if "HIGH_DEMAND" in r["flag"]:
            parts.append("High demand")
        if r["decision"] == "edit":
            parts.append(f"Quantity edited by reviewer (system {r['system_qty']:g})")
        if r["note"]:
            parts.append(f"Reviewer note: {r['note']}")
        return "; ".join(parts)

    out = pd.DataFrame({
        "po_number": t.po_number, "po_date": run_date.isoformat(), "vendor_id": t.vendor_id,
        "vendor_name": t.vendor_name, "sku_id": t.sku_id, "item_name": t.sku_name,
        "quantity": t.final_qty.astype(int), "unit": t.unit, "unit_price": t.unit_price,
        "notes": [notes(r) for r in t.to_dict("records")], "is_urgent": t.is_urgent})
    return out.reset_index(drop=True)[cols]


def write_zoho_csv(lines: pd.DataFrame, cfg: dict, path: Path) -> None:
    zc = cfg["po"]["zoho_columns"]
    keys = ["po_number", "po_date", "vendor_id", "vendor_name", "sku_id", "item_name", "quantity", "unit", "unit_price", "notes"]
    df = lines[keys].rename(columns={"sku_id": "sku"})
    df = df.rename(columns={k: zc[k] for k in zc})
    df[zc["unit_price"]] = df[zc["unit_price"]].apply(lambda v: "" if pd.isna(v) else f"{v:g}")
    df.to_csv(path, index=False)


def write_po_pdf(po_number: str, lines: pd.DataFrame, cfg: dict, path: Path) -> None:
    ss = getSampleStyleSheet()
    first = lines.iloc[0]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
                            title=f"Purchase Order {po_number}")
    story = [Paragraph(f"Purchase Order {po_number}", ss["Title"]),
             Paragraph("<b>Freshroots</b> - Pune Central Warehouse", ss["Normal"]),
             Paragraph(f"PO date: {first.po_date}", ss["Normal"]),
             Paragraph(f"{cfg['po']['counterparty_label']}: <b>{first.vendor_name}</b> ({first.vendor_id})", ss["Normal"]),
             Spacer(1, 8 * mm)]
    priced = lines.unit_price.notna().all()
    head = ["#", "SKU", "Item", "Qty", "Unit"] + (["Unit price", "Amount"] if priced else []) + ["Notes"]
    data = [head]
    for i, r in enumerate(lines.itertuples(), start=1):
        row = [i, r.sku_id, Paragraph(r.item_name, ss["BodyText"]), f"{r.quantity:,}", r.unit]
        if priced:
            row += [f"{r.unit_price:,.2f}", f"{r.unit_price * r.quantity:,.2f}"]
        row.append(Paragraph(r.notes, ss["BodyText"]))
        data.append(row)
    widths = [8, 20, 55, 15, 14] + ([20, 22] if priced else []) + [None]
    tbl = Table(data, colWidths=[w * mm if w else None for w in widths], repeatRows=1)
    tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e3d")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                             ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("FONTSIZE", (0, 0), (-1, -1), 8.5)]))
    story += [tbl, Spacer(1, 6 * mm)]
    if priced:
        story.append(Paragraph(f"<b>Total: {(lines.unit_price * lines.quantity).sum():,.2f}</b>", ss["Normal"]))
    else:
        story.append(Paragraph("Unit prices were not provided, so no order value is shown.", ss["Italic"]))
    story.append(Paragraph("Generated by the Freshroots demand planner. Release the PO in Zoho Inventory after procurement sign-off.", ss["Italic"]))
    doc.build(story)


def write_pos(lines: pd.DataFrame, cfg: dict, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    paths = []
    if not lines.empty:
        write_zoho_csv(lines, cfg, out_dir / "purchase_orders_zoho_import.csv")
    for po, g in lines.groupby("po_number"):
        p = out_dir / f"PO_{po}.pdf"
        write_po_pdf(po, g.reset_index(drop=True), cfg, p)
        paths.append(p)
    return paths
