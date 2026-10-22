# Handoff: redesign the Freshroots review screen (Streamlit)

You are implementing a finished UI design for the existing Freshroots demand-planning app.
**Only the look, layout and flow change. Planning logic, rules, thresholds, exception triggers
and the decision model must not change.** If something in this spec seems to need a logic
change, stop and ask instead.

## 0. Files that come with this handoff

| File | Put it at | What it is |
|---|---|---|
| `style.css` | `app/style.css` (replace) | All custom CSS: tokens (light + dark), badges, tooltip, gauge, tiles, card option B, key-scoped Streamlit overrides |
| `config.toml` | `.streamlit/config.toml` (merge the `[theme*]` tables) | Streamlit theme, light and dark (Streamlit 1.46+) |
| `fr_html.py` | `app/fr_html.py` (new) | Pure functions that return the HTML strings the CSS expects, plus the glossary text |
| `HANDOFF.md` | repo root | This file |

First, find the current review screen (look for `st.tabs`, `st.download_button`, the
decision log, and where `app/style.css` is loaded). Keep its data access and its
save-decision / generate-POs functions; re-wire only the rendering.

## 1. Non-negotiables (from the brief)

- Do not touch rules, thresholds, exception triggers, status/flag codes or PO generation.
- Decision model stays: Approve (system qty), Use suggested (if any), Edit quantity, Reject; optional note;
  saved immediately on button press; appended to the log with the reviewer name; last decision per SKU wins.
- POs cannot be generated while any exception is undecided.
- Reviewer name is required before any decision can be saved (disable the buttons, show a caption).
- Codes stay visible as badge text (`BORDERLINE`, `STOCKOUT_RISK`, …).
- Streamlit only: native widgets + static HTML/CSS via `st.markdown(..., unsafe_allow_html=True)`.
  No JavaScript, no iframes, no components, no hosted images. No sticky bars, modals or animation.
- Every tap target ≥ 44px. Colour never the only signal. Works at 375px wide and on desktop (`layout="centered"`).

## 2. Global setup

```python
from pathlib import Path
import streamlit as st
import fr_html as fr

st.set_page_config(page_title="Freshroots demand planning", layout="centered")
st.markdown(f"<style>{Path('app/style.css').read_text()}</style>", unsafe_allow_html=True)
st.markdown(fr.theme_marker(), unsafe_allow_html=True)   # switches custom HTML to dark tokens
```

All HTML must be passed as one line (fr_html already does this). Indented multi-line HTML
inside `st.markdown` turns into a code block.

## 3. Screen by screen

### A. Empty state (no run yet)
- `st.markdown('<h1 class="fr-title">Freshroots demand planning</h1><p class="fr-sub">Review exceptions, then generate purchase orders.</p>')`
- `st.container(border=True, key="empty")`: heading "No planning run yet", body text, `st.button("Run planning", type="primary", use_container_width=True)`, caption "Uses the SAP files already on the server unless you add fresh ones below."
- `st.expander("Use fresh SAP files (optional)", expanded=True)`: `st.file_uploader(accept_multiple_files=True, type="csv")`, then
  `fr.file_checklist(REQUIRED, added_names)` under "Required · x of 5 added" and `fr.file_checklist(OPTIONAL, added_names)` under "Optional".
  Required: weekly_sales, sku_master, distributor_master, current_inventory, calendar. Optional: open_purchase_orders, sku_prices, distributor_sales.

### B. Header (every screen once a run exists), top to bottom
1. Title + `fr-sub` run line: `Run <b>2026-10-19</b> · festival month, demand +25%` (drop the festival part outside Oct/Nov/Mar).
2. `st.expander("Run details and new run")` (collapsed): source files, uploader, secondary "Start a new run".
3. `st.text_input("Reviewer name", key="reviewer", help=...)`.
4. Summary strip: `with st.container(key="stats"):` → `st.columns(4)` → `st.metric` for SKUs, Review, Auto, No order, each with `help=`. The four must add up (15 = 4 + 2 + 9).
5. `st.progress(decided/total, text="1 of 4 exceptions decided")` → "All 4 exceptions decided". Hide when there are no exceptions.
6. `st.tabs([f"Review · {left}", "Orders", f"Auto · {n_auto}", "All SKUs"])`.

### C. Review tab — exception cards (use **card option B**)
Sort: undecided first, then URGENT first. Decided cards go under a small "Decided · n" divider.

**Undecided card**, inside `st.container(border=True, key=f"card-open-{sku}")`:
1. One `st.markdown` block: `fr.card_head_b(sku, name, supplier, perishable, urgent, fr.headline(...), fr.gauge(..., verdict=False))`
   (name + URGENT badge, plain-English headline, cover gauge).
2. One `fr.callout(code, reason)` per exception reason (reason text verbatim from the pipeline).
3. `fr.facts(on_hand, change_pct, rule_flags)`.
4. `st.expander("How the rules decided")` containing the existing rule explanation sentence.
5. If the card was re-opened: `fr.current_decision(label, qty, by, at, note)`.
6. `st.text_input("Note (optional)", key=f"note-{sku}", placeholder="Why, e.g. promo confirmed with sales")`.
7. `st.markdown(fr.DECISION_HEAD)` then one row per option:
   ```python
   for i, (label, action, qty, cover_after) in enumerate(options):
       with st.container(key=f"opt-{sku}-{i}"):
           b, o = st.columns([3, 2])
           if b.button(label, key=f"btn-{sku}-{i}", type="primary" if i == 0 else "secondary",
                       use_container_width=True, disabled=not st.session_state.reviewer):
               save_decision(sku, action, qty, note, reviewer)   # existing function, unchanged
               st.session_state.reopen.pop(sku, None)
               st.rerun()
           o.markdown(fr.outcome(cover_after, lo, hi), unsafe_allow_html=True)
   ```
   Options, in this order (first one is primary):
   - with a suggestion: `Use suggested · {sug}`, `Approve · {sys}`, `Reject · 0`
   - without: `Approve · {sys}` (or `Approve · 0 (paused)` when sys is 0), `Reject · 0`
   `cover_after` for a quantity q = cover_now + q / expected_weekly_demand, using the
   festival-adjusted weekly demand the pipeline already computed (Reject → cover_now).
   If the pipeline exposes cover-after only for the system qty, add a small pure helper
   that reuses its existing weekly-demand value; do not re-derive demand or thresholds.
8. Under the rows, when no reviewer name: `st.caption("Add your name at the top to save decisions.")`.
9. `st.expander("Edit quantity")`: `st.number_input("Order quantity (units)", min_value=0, step=1, value=current)` + `st.button(f"Save · {qty}")` → saves as an edit with the note.

**Decided card**, `st.container(border=True, key=f"card-done-{sku}")`: `fr.done(...)` (state, qty, system qty, who, when, note)
and `st.button("Change decision")` which sets `st.session_state.reopen[sku] = True` and reruns.
Optional `st.toast("Saved: SKU001 approved at 750.")` after each save.

### D. Orders tab
- **Blocked** (any exception undecided): `st.warning` with title "{n} exceptions still need a decision", the sentence
  "Purchase orders can be generated once every exception is decided.", a list of each undecided SKU + name (+ URGENT),
  and "Open the Review tab to decide them." Then `st.button("Generate purchase orders", type="primary", disabled=True)`
  and caption "Unlocks when all {n} exceptions are decided. The {a} auto-approved lines are included automatically."
- **Generated**: `st.success("3 purchase orders ready · 5 lines · 0 held back")`; override rate block
  (`st.metric("Override rate", "50%", help=...)`, caption "2 of 4 decided lines", `fr.override_meter(rate)`,
  and only if rate > 30%: `st.info("Above 30% this run. One run is not a trend; if it stays above 30% over several runs, the rules may not match reality and are worth revisiting.")`);
  primary `st.download_button("Download Zoho import (CSV)")`; one bordered container per PO (id, supplier, "2 lines · 911 units", `PDF` download);
  `st.dataframe` of PO lines (PO, SKU, Final, System, Source = Approved / Changed / Auto, Product), `hide_index=True`;
  caption "Unit prices are not in this run's data, so order values are not shown."; secondary downloads "Sourcing handoff note", "Review log (CSV)".

### E. Auto tab
Intro: "**{n} lines ordered by the rules with nothing unusual.** They go into the POs as shown. Edit one only if your judgment differs."
Same card head, facts and rule expander, no callouts, no decision rows. Show "Goes into the PO at {qty} units. No decision needed."
and the Edit quantity expander. Key: `card-auto-{sku}`.

### F. All SKUs tab
`st.selectbox("Show", ["All statuses (15)", "Needs review", "Auto-approved", "No order"])` and one `st.dataframe`
(never cards): SKU (pinned), Status, Cover, Order, After, Flag, 4w vs 12w, 4-week forecast, Exceptions, Product.
Use `st.column_config` with `help=` on headers (glossary in `fr.GLOSSARY`). Caption:
"Swipe the table sideways for flag, demand change, 4-week forecast and exceptions. Tap a column name to sort."

## 4. Tooltips
- Custom "?" on badges and tiles: produced by `fr.tip()` inside `fr.badge()` etc. CSS-only; opens on hover/focus,
  closes on tap elsewhere; the bubble is anchored to its row so it never clips. Nothing to wire.
- Native widgets: pass `help=` using the texts in `fr.GLOSSARY` / the Microcopy section of the design.

## 5. Acceptance checklist
- [ ] At 375px: summary strip stays 4 across; decision rows stay [button | outcome]; nothing scrolls sideways except the All SKUs table.
- [ ] Every button, tab and expander header ≥ 44px tall.
- [ ] Light and dark both readable (switch theme in Streamlit settings; custom HTML follows).
- [ ] Tapping a "?" opens its tooltip inside the screen; tapping elsewhere closes it.
- [ ] Decisions save on one tap, appear in the log with reviewer name; re-opening and re-deciding replaces the shown decision.
- [ ] With no reviewer name, all decision buttons are disabled with the caption.
- [ ] Orders tab is blocked until every exception is decided; generated view shows counts, override rate, all downloads.
- [ ] Sample run 2026-10-19 reproduces: SKU001 headline "Stock lasts 3.4 weeks; the minimum is 6. The rules order 750 (1.5× standard, for high demand), which brings it to 6.1 weeks."; SKU013 rows show 161 → 6.0 wk in band, 120 → 5.3 wk below band, 0 → 3.2 wk below band; SKU003 shows 5.95 (not 6.0) after 300.
- [ ] No planning-logic file changed (check the diff).

## 6. Open items to confirm with the team
Tooltip thresholds for NEW_LAUNCH, SHARP_DROP, DISTRIBUTOR_ANOMALY and HIGH_VALUE are marked `[confirm]` in
`fr.GLOSSARY`; replace them with the real values from the rules code (read only, don't change the rules).
