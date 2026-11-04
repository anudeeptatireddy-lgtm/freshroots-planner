"""Draws docs/components-map.html and renders docs/components-map.png (swimlane format: actors x Trigger/Input/Context/Processing/AI/Output).
Run: python scripts/make_components_map.py   (needs Google Chrome for the PNG)"""
import subprocess
from html import escape
from pathlib import Path

COLS = ["Trigger", "Input", "Context", "Processing", "AI", "Output"]
PURPLE, BLUE, GREEN, ORANGE, PINK, RED = "#7a3db8", "#2f6fd0", "#1f9a52", "#df8f1f", "#d6338a", "#e8553a"
# (actor, sub label, row colour, {column: (text, colour)})
ROWS = [
    ("Planner", "(Buyer / Reviewer)", "#e9f0fb", {
        "Trigger": ("① Opens the link and clicks Run planning, or uploads fresh SAP exports (twice a week)", PURPLE),
        "Input": ("② Types a name, then decides each exception: Approve, Use suggested, Edit qty or Reject, plus a note", BLUE)}),
    ("System", "(React app + Python API on Vercel)", "#fdf6e3", {
        "Context": ("③ Loads the 5 SAP CSVs (sales, SKU master, distributors, inventory, calendar) and config.yaml thresholds", GREEN),
        "Processing": ("④ Cleans data, works out weeks of cover (festival ×1.25), forecasts 4 weeks, queues exceptions. No PO until all are decided", ORANGE)}),
    ("Rules Engine", "(No ML, by design)", "#e8f4ea", {
        "AI": ("⑤ Written rules flag HIGH_DEMAND, STOCKOUT_RISK, OVERSTOCK and exceptions like BORDERLINE, with reasons. No ML; LLM hook off", PINK)}),
    ("Integrations", "(Neon + Zoho + files)", "#fbe8ef", {
        "Context": ("⑥ Neon Postgres keeps runs, the append-only decision log and PO lines (without a DB the browser holds the run)", GREEN),
        "Output": ("⑦ Builds PO PDFs, Zoho import CSV and handoff note; previews or creates DRAFT POs in Zoho Inventory", BLUE)}),
    ("Sourcing Team", "(Raghav + buyers)", "#efedf9", {
        "Output": ("⑧ Gets urgent-first POs, releases the Zoho drafts; the run log tracks the override rate (above 30% = review the rules)", RED)}),
]
NAVY = "#14284b"


def build() -> str:
    head = "".join(f"<div class='h'>{c}</div>" for c in ["Actor"] + COLS)
    body = []
    for actor, sub, bg, cells in ROWS:
        body.append(f"<div class='a' style='background:{bg}'><b>{escape(actor)}</b><span>{escape(sub)}</span></div>")
        for c in COLS:
            if c in cells:
                text, col = cells[c]
                body.append(f"<div class='c' style='background:{bg}'><div class='box' style='color:{col};border-color:{col}'>{escape(text)}</div></div>")
            else:
                body.append(f"<div class='c' style='background:{bg}'></div>")
    return f"""<!doctype html><meta charset='utf-8'><style>
body{{margin:0;background:#fff;font-family:Helvetica,Arial,sans-serif}}
h1{{margin:0;padding:22px 0 16px;text-align:center;font-size:25px;color:{NAVY}}}
.g{{margin:0 15px 15px;display:grid;grid-template-columns:150px repeat(6,1fr);border:2px solid {NAVY};border-right:0;border-bottom:0}}
.g>div{{border-right:1px solid {NAVY};border-bottom:1px solid {NAVY}}}
.h{{background:{NAVY};color:#fff;font-weight:700;font-size:18px;padding:19px 0;text-align:center;border-color:{NAVY}!important}}
.a{{display:flex;flex-direction:column;justify-content:center;padding:0 14px;color:{NAVY};font-size:18px;min-height:170px}}
.a span{{font-size:14px;color:#555;margin-top:4px;line-height:1.3}}
.c{{display:flex;align-items:center;justify-content:center;padding:10px}}
.box{{background:#fff;border:2px solid;border-radius:9px;padding:11px 12px;font-size:15px;line-height:1.38;text-align:center;width:100%}}
</style><h1>Freshroots · Demand Planning and PO Automation — Components Map</h1><div class='g'>{head}{''.join(body)}</div>"""


if __name__ == "__main__":
    docs = Path(__file__).resolve().parent.parent / "docs"
    (docs / "components-map.html").write_text(build())
    subprocess.run(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=1", "--window-size=1600,1048", f"--screenshot={docs / 'components-map.png'}",
                    f"file://{docs / 'components-map.html'}"], check=False, capture_output=True)
    print(docs / "components-map.png")
