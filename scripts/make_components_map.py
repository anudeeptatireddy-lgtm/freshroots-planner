"""Draws docs/components-map.svg (then PNG via headless Chrome). Run: python scripts/make_components_map.py"""
from html import escape
from pathlib import Path

W, H = 1764, 1180
INK, MUTED, LINE, ACC, ACC_SOFT, OK = "#141414", "#6b6b66", "#d9d7d0", "#e8573a", "#fdece7", "#2f9e6b"
o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Inter, Helvetica, Arial, sans-serif">',
     f'<rect width="{W}" height="{H}" fill="#f4f3f0"/>',
     '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#141414"/></marker></defs>']


def t(x, y, s, size=17, weight=400, fill=INK, anchor="start"):
    o.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{escape(s)}</text>')


def box(x, y, w, h, title, lines=(), fill="#fff", stroke=LINE, tcol=INK, sw=1.5, tsize=18):
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    t(x + 16, y + 28, title, tsize, 700, tcol)
    for i, ln in enumerate(lines):
        t(x + 14, y + 54 + i * 23, ln, 15, 400, MUTED if not ln.startswith("•") else INK)


def col(x, w, label, color):
    o.append(f'<rect x="{x}" y="118" width="{w}" height="34" rx="17" fill="{color}"/>')
    t(x + w / 2, 141, label, 15, 700, "#fff", "middle")


def arrow(x1, y1, x2, y2, label=(), both=False):
    ms = ' marker-start="url(#a)"' if both else ""
    o.append(f'<line x1="{x1 + 4}" y1="{y1}" x2="{x2 - 4}" y2="{y2}" stroke="{INK}" stroke-width="2.4" marker-end="url(#a)"{ms}/>')
    for i, ln in enumerate(reversed(label)):
        t((x1 + x2) / 2, y1 - 9 - i * 15, ln, 13, 700, INK, "middle")


t(40, 52, "Freshroots demand planning and PO automation: components map", 32, 800)
t(40, 84, "Rules-based planning (no ML) reads SAP files, flags exceptions for a human, then builds purchase orders and drafts them in Zoho.", 17.5, 400, MUTED)

X = [40, 390, 740, 1090, 1440]
CW = 284
col(X[0], CW, "1 · DATA SOURCES", "#555")
col(X[1], CW, "2 · USER INTERFACE", ACC)
col(X[2], CW, "3 · API", INK)
col(X[3], CW, "4 · PLANNING ENGINE (PYTHON)", "#2d5bd0")
col(X[4], CW, "5 · STORAGE, TOOLS, OUTPUTS", OK)

# 1 data sources
box(X[0], 168, CW, 262, "SAP CSV exports", ["Required:", "• weekly_sales.csv", "• sku_master.csv", "• distributor_master.csv", "• current_inventory.csv", "• calendar.csv (festival months)", "Optional: open_purchase_orders,", "sku_prices, distributor_sales"])
box(X[0], 446, CW, 128, "Bundled copy", ["data/raw/ in the repo is the", "default input, so a run works", "with no upload."])
box(X[0], 590, CW, 190, "config.yaml (all thresholds)", ["• high demand: +20% → order 1.5×", "• cover: 6–14 wk (perishable 3–4)", "• festival uplift 1.25 (calendar)", "• borderline: 2 pts / 0.25 wk", "• Zoho columns, sending switch"])
box(X[0], 796, CW, 118, "Reviewer (human)", ["Names every decision. Decides all", "exceptions before any PO exists."], fill=ACC_SOFT, stroke=ACC)

# 2 UI
box(X[1], 168, CW, 100, "React web app (Vite)", ["Static site on Vercel.", "Desktop-first. No business logic."], stroke=ACC, sw=2)
box(X[1], 284, CW, 96, "Header", ["Reviewer name, run picker,", "Upload files, run details, new run"])
box(X[1], 396, CW, 140, "Review tab", ["Exception cards: headline, compare", "table, reasons, then Approve, Use", "suggested, Edit qty or Reject, plus", "a note. Auto lines listed below."])
box(X[1], 552, CW, 96, "Stock tab (warehouse rack)", ["Each carton = 1 week of cover;", "dashed boxes = incoming order"])
box(X[1], 664, CW, 116, "Orders tab", ["Generate POs (locked until all", "decided), override rate, PO PDFs,", "CSV downloads, Send to Zoho"])
box(X[1], 796, CW, 118, "All SKUs + tooltips", ["Filter and sortable table of all 15", "SKUs. Tooltips explain every term."])

# 3 API
box(X[2], 168, CW, 100, "Vercel Python function", ["api/index.py → api/_core.py", "JSON over HTTPS, one endpoint"], fill="#fff", stroke=INK, sw=2)
box(X[2], 284, CW, 196, "Operations", ["GET   runs · run · file", "POST  plan  (optional CSV uploads)", "POST  decide (approve/edit/reject)", "POST  generate (POs)", "POST  zoho (preview | send)", "Errors become readable messages"])
box(X[2], 496, CW, 232, "Guards (server side)", ["• reviewer name required", "• “system:” names rejected", "• no PO while an exception is open", "• run ids never reused (_r2, _r3)", "• file names validated", "• Zoho send needs confirm + keys"])
box(X[2], 744, CW, 170, "Hosting", ["Vercel: site + API (public link)", "GitHub: code, branches", "Env vars: DATABASE_URL, ZOHO_*"])

# 4 engine
stages = [("1 Load", "read 5 CSVs, hash them"), ("2 Clean and validate", "dupes, gaps, bad values flagged"), ("3 Organise", "weeks of cover, festival ×1.25"),
          ("4 Rules", "overstock, high demand, stockout"), ("5 Forecast", "4-week demand per SKU"), ("6 Exceptions", "flags lines that need a person"),
          ("7 Human review", "decision log, override rate"), ("8 PO generation", "one PO per supplier")]
for i, (a, b) in enumerate(stages):
    y = 168 + i * 66
    hl = i in (5, 6)
    o.append(f'<rect x="{X[3]}" y="{y}" width="{CW}" height="56" rx="14" fill="{ACC_SOFT if hl else "#fff"}" stroke="{ACC if hl else "#2d5bd0"}" stroke-width="1.8"/>')
    t(X[3] + 16, y + 24, a, 16.5, 700)
    t(X[3] + 16, y + 44, b, 14, 400, MUTED)
    if i < 7:
        o.append(f'<line x1="{X[3] + CW / 2}" y1="{y + 56}" x2="{X[3] + CW / 2}" y2="{y + 66}" stroke="#2d5bd0" stroke-width="2.4" marker-end="url(#a)"/>')
box(X[3], 706, CW, 208, "AI / model layer", ["None in the decision path:", "every number comes from written", "rules a person can read and check.", "Optional LLM summary hook: off.", "Acceptance run 2026-10-19 matches."], fill="#fff", stroke=INK, sw=2.4)

# 5 storage etc
box(X[4], 168, CW, 214, "Neon Postgres", ["Source of truth (psycopg).", "No DB: the browser holds the run.", "• runs, run_files, decisions (log)", "• planning_lines, data_issues", "• purchase_order_lines, reference data"], stroke=OK, sw=2)
box(X[4], 398, CW, 186, "Zoho Inventory API (zoho.in)", ["OAuth refresh token, org id.", "Finds vendor and item, then creates", "DRAFT purchase orders only.", "Dry-run preview first; duplicate", "guard; a person releases in Zoho."], stroke=OK, sw=2)
box(X[4], 600, CW, 150, "Libraries", ["pandas (data), PyYAML (config),", "ReportLab (PO PDFs), psycopg", "(Postgres), React + Vite (UI)"])
box(X[4], 766, CW, 148, "Outputs per run", ["• PO_<id>.pdf per supplier", "• purchase_orders_zoho_import.csv", "• sourcing_handoff.md", "• review_log.csv · run_log.json"], fill="#e9f6ef", stroke=OK, sw=2)

# arrows between columns
arrow(X[0] + CW, 290, X[1], 290, ["CSV", "files"])
arrow(X[1] + CW, 226, X[2], 226, ["JSON"], both=True)
arrow(X[1] + CW, 470, X[2], 470, ["actions"], both=True)
arrow(X[2] + CW, 330, X[3], 330, ["plan,", "run"], both=True)
arrow(X[3] + CW, 250, X[4], 250, ["save,", "load"], both=True)
arrow(X[3] + CW, 480, X[4], 480, ["POs to", "Zoho"])
arrow(X[3] + CW, 840, X[4], 840, ["write", "files"])
o.append(f'<path d="M{X[0] + CW} 700 H{X[0] + CW + 16} V1010 H{X[3] - 26} V394 H{X[3] - 4}" fill="none" stroke="{MUTED}" stroke-width="2" stroke-dasharray="6 6" marker-end="url(#a)"/>')
t(X[0] + CW + 28, 1034, "thresholds and the festival calendar feed the rules (stage 4)", 14, 700, MUTED)

# flow strip
o.append(f'<rect x="40" y="1050" width="1684" height="108" rx="20" fill="#fff" stroke="{INK}" stroke-width="2"/>')
t(60, 1080, "END-TO-END FLOW", 15, 800, ACC)
steps = ["1  SAP files loaded", "2  Rules plan every SKU", "3  Exceptions queue for review", "4  Human decides, logged", "5  Generate POs (PDF + CSV)", "6  Zoho draft POs"]
for i, s in enumerate(steps):
    x = 60 + i * 279
    o.append(f'<rect x="{x}" y="1094" width="258" height="46" rx="23" fill="{ACC_SOFT if i in (2, 3) else "#f4f3f0"}" stroke="{ACC if i in (2, 3) else LINE}" stroke-width="1.6"/>')
    t(x + 129, 1123, s, 15.5, 700, INK, "middle")
    if i < 5:
        o.append(f'<path d="M{x + 260} 1117 h16" stroke="{INK}" stroke-width="2.4" marker-end="url(#a)"/>')
o.append("</svg>")
out = Path(__file__).resolve().parent.parent / "docs" / "components-map.svg"
out.write_text("\n".join(o))
print(out)
