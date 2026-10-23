"""HTML builders for the custom parts of the Freshroots review screen.

Pair with app/style.css. Every function returns one HTML string with no
newlines or leading spaces (Markdown would turn indented HTML into a code
block). Render with st.markdown(html, unsafe_allow_html=True).

Pure presentation: no planning logic lives here.
"""
from html import escape

import streamlit as st

BAD = {"URGENT", "BELOW_MIN_AFTER_ORDER", "SHARP_DROP", "DATA_ISSUE"}
FLAGS = {"STOCKOUT_RISK", "HIGH_DEMAND", "OVERSTOCK", "NOT_PLANNED"}

# Tooltip text. Thresholds match config.yaml defaults.
GLOSSARY = {
    "URGENT": "Cover is below the safe minimum right now. Decide these first.",
    "HEALTHY": "Cover is inside the safe band and demand has not jumped. Nothing to order.",
    "STOCKOUT_RISK": "Cover is below the minimum (6 weeks, or 3 for perishables). The rules order now and mark it URGENT.",
    "HIGH_DEMAND": "The last 4 weeks sold more than 20% above the 12-week average. The order is 1.5x the standard quantity.",
    "OVERSTOCK": "Cover is above the maximum (14 weeks, or 4 for perishables). The order is paused at 0.",
    "NOT_PLANNED": "The rules did not plan this product this run. The exception reason says why.",
    "BORDERLINE": "A value sits close to a rule threshold: within 2 points of the +20% demand line, or within 0.25 weeks of a band edge. A small data change would flip the decision.",
    "BELOW_MIN_AFTER_ORDER": "Even after the recommended order, cover stays below the minimum. A top-up quantity is suggested.",
    "ABOVE_MAX_AFTER_ORDER": "The recommended order would push cover above the maximum. A smaller quantity is suggested.",
    "NEW_LAUNCH": "Fewer than 12 weeks of sales history, so the demand average is not reliable. Check against the launch plan.",
    "DATA_ISSUE": "Something in the SAP data for this product is missing or looks wrong. Check it before ordering.",
    "SHARP_DROP": "The last 4 weeks fell more than 30% against the 12-week average. The rules do not cover falling demand. Check for a delisting or data error.",
    "DISTRIBUTOR_ANOMALY": "One distributor's 4-week sales moved more than 50% (a placeholder in config.yaml) against its 12-week average. Only active when distributor-level sales are supplied.",
    "HIGH_VALUE": "The order value is above the review limit set in config.yaml. Only active when prices and a limit are supplied.",
    "On hand": "Units in stock at the stock count. Open POs are added when cover is worked out.",
    "4w vs 12w": "Average weekly sales over the last 4 weeks compared with the last 12. More than +20% marks HIGH_DEMAND.",
    "System qty": "The order quantity the rules work out. HIGH_DEMAND orders 1.5x the standard quantity; OVERSTOCK orders 0.",
}


def theme_marker() -> str:
    """Empty marker that switches the --fr-* tokens to dark."""
    try:
        is_dark = st.context.theme.type == "dark"  # Streamlit 1.46+
    except Exception:
        is_dark = False
    return '<span class="fr-theme-dark"></span>' if is_dark else ""


def severity(code: str) -> str:
    if code in BAD:
        return "bad"
    if code == "HEALTHY":
        return "good"
    if code in FLAGS:
        return "info"
    return "warn"


def tip(term: str, text: str | None = None, small: bool = False) -> str:
    text = text or GLOSSARY.get(term, "")
    # &#10; keeps the HTML on one line; CSS white-space: pre-line shows the break.
    body = escape(term, quote=True) + "&#10;" + escape(text, quote=True)
    label = escape(f"{term}: {text}", quote=True)
    cls = "fr-tip fr-tip--sm" if small else "fr-tip"
    return f'<span class="{cls}" tabindex="0" role="button" aria-label="{label}" data-tip="{body}"></span>'


def badge(code: str) -> str:
    return f'<span class="fr-badge fr-badge--{severity(code)}">{escape(code)}{tip(code)}</span>'


def badges(urgent: bool, exceptions: list[str], flags: list[str]) -> str:
    codes = (["URGENT"] if urgent else []) + list(exceptions) + list(flags)
    return '<div class="fr-badges">' + "".join(badge(c) for c in codes) + "</div>"


def _pct(v: float, scale_max: float) -> float:
    return max(0.0, min(100.0, v / scale_max * 100.0))


def _align(p: float) -> str:
    return " is-start" if p < 12 else (" is-end" if p > 88 else "")


def gauge(now: float, after: float | None, lo: float, hi: float, perishable: bool, verdict: bool = True) -> str:
    """Weeks-of-cover gauge. after=None when the order is 0. verdict=False for card option B (the headline says it)."""
    scale_max = 8 if perishable else 20
    p_lo, p_hi, p_now = _pct(lo, scale_max), _pct(hi, scale_max), _pct(now, scale_max)
    out = now < lo or now > hi
    state = "Below" if now < lo else ("Above" if now > hi else "Inside")
    now_txt = f"Now {wk(now, lo, hi)} wk" + (" ›" if now > scale_max else "")
    o = " is-out" if out else ""
    lo_s, hi_s = f"{lo:g}", f"{hi:g}"

    parts = [
        f'<div class="fr-gauge" role="img" aria-label="Weeks of cover: now {now:.1f}'
        + (f", after order {after:.1f}" if after is not None else "")
        + f'; safe band {lo_s} to {hi_s} weeks">',
        f'<div class="fr-grow"><span class="fr-glabel fr-glabel--now{o}{_align(p_now)}" style="left:{p_now:.1f}%">{now_txt}</span></div>',
        '<div class="fr-track">',
        f'<div class="fr-band" style="left:{p_lo:.1f}%;width:{p_hi - p_lo:.1f}%"></div>',
    ]
    if after is not None:
        p_after = _pct(after, scale_max)
        parts.append(f'<div class="fr-seg" style="left:{min(p_now, p_after):.1f}%;width:{abs(p_after - p_now):.1f}%"></div>')
    parts.append(f'<div class="fr-mark fr-mark--now{o}" style="left:{p_now:.1f}%"></div>')
    if after is not None:
        parts.append(f'<div class="fr-mark fr-mark--after" style="left:{p_after:.1f}%"></div>')
    parts.append("</div>")
    after_label = (
        f'<span class="fr-glabel fr-glabel--after{_align(p_after)}" style="left:{p_after:.1f}%">After order {wk(after, lo, hi)} wk</span>'
        if after is not None else ""
    )
    parts.append(f'<div class="fr-grow">{after_label}</div>')
    parts.append(
        f'<div class="fr-gl"><span>0</span><span style="left:{p_lo:.1f}%">{lo_s}</span>'
        f'<span style="left:{p_hi:.1f}%">{hi_s}</span><span>{scale_max}+ wk</span></div>'
    )
    if after is None:
        v2 = "No order, so cover stays here."
    elif after < lo:
        v2 = "After the order: still below the band."
    elif after > hi:
        v2 = "After the order: above the band."
    else:
        v2 = "After the order: inside the band."
    if verdict:
        parts.append(
            f'<p class="fr-verdict"><b class="{o.strip()}">{state} the safe band now</b> '
            f"(safe band {lo_s}–{hi_s} wk). {v2}</p>"
        )
    parts.append("</div>")
    return "".join(parts)


def tiles(on_hand: int, change_pct: float, system_qty: int, system_note: str = "units") -> str:
    change_note = "high-demand line +20%" if change_pct > 18 else "vs 12-week avg"
    sign = "+" if change_pct >= 0 else "−"
    items = [
        ("On hand", f"{on_hand:,}", "units"),
        ("4w vs 12w", f"{sign}{abs(change_pct):.1f}%", change_note),
        ("System qty", f"{system_qty:,}", system_note),
    ]
    cells = "".join(
        f'<div class="fr-tile"><div class="fr-tile-label">{escape(label)}{tip(label, small=True)}</div>'
        f'<div class="fr-tile-value">{v}</div><div class="fr-tile-note">{escape(n)}</div></div>'
        for label, v, n in items
    )
    return f'<div class="fr-grid">{cells}</div>'


def card_head(sku: str, name: str, supplier: str, perishable: bool, urgent: bool,
              exceptions: list[str], flags: list[str], gauge_html: str, tiles_html: str) -> str:
    """Badges + name + gauge + tiles as ONE markdown block (fewer elements, faster reruns)."""
    per = "High perishability" if perishable else "Low perishability"
    return (
        badges(urgent, exceptions, flags)
        + f'<p class="fr-name">{escape(name)}</p>'
        + f'<p class="fr-meta">{escape(sku)} · {escape(supplier)} · {per}</p>'
        + gauge_html
        + tiles_html
    )


def current_decision(label: str, qty: int, by: str, at: str, note: str = "") -> str:
    meta = f"{escape(by)} · {escape(at)}" + (f" · “{escape(note)}”" if note else "")
    return f'<div class="fr-decision"><b>Current decision: {escape(label)} · {qty:,}</b><small>{meta}</small></div>'


def done(sku: str, name: str, label: str, qty: int, system_qty: int, by: str, at: str, note: str = "") -> str:
    meta = f"{escape(by)} · {escape(at)}" + (f" · “{escape(note)}”" if note else "")
    return (
        '<div class="fr-done"><span class="fr-done-icon" aria-hidden="true"></span><div>'
        f'<div class="fr-done-kicker">Decided · {escape(label)}</div>'
        f'<p class="fr-name" style="margin:2px 0 0">{escape(name)} <span class="fr-meta">· {escape(sku)}</span></p>'
        f'<div><span class="fr-done-qty">{qty:,}</span> <span class="fr-meta">units · system {system_qty:,}</span></div>'
        f'<div class="fr-done-meta">{meta}</div></div></div>'
    )


# ---------- Card option B (answer first, outcome per choice) ----------

def wk(v: float, lo: float, hi: float) -> str:
    """Format weeks with 1 decimal, or 2 when rounding would hide which side of a band edge it is on.
    5.95 against a minimum of 6 must read 5.95, not 6.0."""
    one = round(v, 1)
    for edge in (lo, hi):
        if (v < edge) != (one < edge) or (v > edge) != (one > edge):
            return f"{v:.2f}"
    return f"{v:.1f}"


def headline(now: float, after: float | None, lo: float, hi: float, system_qty: int,
             perishable: bool, high_demand: bool) -> str:
    """Plain-English answer: where stock is, and what the rules' order does."""
    per = " for perishables" if perishable else ""
    n = wk(now, lo, hi)
    if now < lo:
        first = f"Stock lasts {n} weeks; the minimum{per} is {lo:g}."
    elif now > hi:
        first = f"Stock lasts {n} weeks, over the {hi:g}-week maximum{per}."
    else:
        first = f"Stock lasts {n} weeks, inside the {lo:g}–{hi:g} week band."
    if system_qty == 0 or after is None:
        rest = "The rules pause the order at 0."
    else:
        why = " (1.5× standard, for high demand)" if high_demand else ""
        a = wk(after, lo, hi)
        if after < lo:
            rest = f"The rules order {system_qty:,}{why}, but that only reaches {a} weeks."
        elif after > hi:
            rest = f"The rules order {system_qty:,}{why}, which pushes it to {a} weeks, over the maximum."
        else:
            rest = f"The rules order {system_qty:,}{why}, which brings it to {a} weeks."
    return f'<p class="fr-headline"><b>{escape(first)}</b> {escape(rest)}</p>'


def card_head_b(sku: str, name: str, supplier: str, perishable: bool, urgent: bool, headline_html: str, gauge_html: str, extra: str = "") -> str:
    """Name + URGENT + headline + gauge as ONE markdown block. Build gauge_html with verdict=False."""
    per = "High perishability" if perishable else "Low perishability"
    urgent_html = f'<div class="fr-badges">{badge("URGENT")}</div>' if urgent else ""
    return (
        f'<div class="fr-head"><div><p class="fr-name">{escape(name)}</p>'
        f'<p class="fr-meta">{escape(sku)} · {escape(supplier)} · {per}</p>{extra}</div>{urgent_html}</div>'
        + headline_html + gauge_html
    )


def callout(code: str, reason: str) -> str:
    """One exception: code chip + reason in a single warning box."""
    return (
        f'<div class="fr-callout"><div class="fr-callout-head"><span>Why this needs you</span>{badge(code)}</div>'
        f'<div>{escape(reason)}</div></div>'
    )


def facts(on_hand: int, change_pct: float, flags: list[str]) -> str:
    sign = "+" if change_pct >= 0 else "−"
    chips = "".join(badge(f) for f in flags)
    return (
        '<dl class="fr-facts">'
        f'<dt>On hand</dt><dd><b>{on_hand:,}</b> units</dd>'
        f'<dt>Demand, last 4 wk</dt><dd><b>{sign}{abs(change_pct):.1f}%</b> vs 12-week average</dd>'
        f'<dt>Rule flags</dt><dd>{chips}</dd>'
        '</dl>'
    )


def outcome(cover: float, lo: float, hi: float) -> str:
    """Right-hand cell of a decision row: cover after this choice, in words and glyph."""
    if cover < lo:
        cls, word = "below", "below band"
    elif cover > hi:
        cls, word = "above", "above band"
    else:
        cls, word = "in", "in band"
    return f'<div class="fr-outcome fr-outcome--{cls}"><b>{wk(cover, lo, hi)} wk</b><small>{word}</small></div>'


DECISION_HEAD = '<div class="fr-dhead"><span>Your decision</span><span>Cover after</span></div>'


def override_meter(rate: float) -> str:
    """rate in 0..1. The 30% tick is fixed by the brief."""
    return (
        '<div class="fr-meter"><div class="fr-meter-track">'
        f'<div class="fr-meter-fill" style="width:{rate * 100:.0f}%"></div></div>'
        '<div class="fr-meter-tick" aria-hidden="true"></div></div>'
    )


def file_checklist(expected: list[str], added: set[str]) -> str:
    rows = "".join(
        f'<li><code>{escape(f)}</code><span class="{"is-added" if f in added else "is-missing"}">'
        f'{"Added" if f in added else "Not added"}</span></li>'
        for f in expected
    )
    return f'<ul class="fr-files">{rows}</ul>'


def _status(cover: float, lo: float, hi: float) -> tuple[str, str]:
    if cover < lo:
        return "below", "↓ Low"
    if cover > hi:
        return "above", "↑ High"
    return "in", "✓ OK"


def compare_table(cols: list[tuple[str, int | None, float, float]], lo: float, hi: float, unit_price: float | None = None) -> str:
    """The at-a-glance table. cols = [(header, order_qty or None for 'now', stock_units, weeks_of_cover)].
    Rows: order, stock, weeks of cover, status. One column per choice, so every option reads straight down."""
    heads = []
    for i, (h, *_rest) in enumerate(cols):
        cls = ' class="is-rec"' if i == 1 else ""
        heads.append(f'<th scope="col"{cls}>{escape(h)}</th>')
    head = "".join(heads)
    order = "".join(
        '<td class="fr-na">—</td>' if q is None else f'<td class="fr-big">{q:,}</td>' if q else '<td class="fr-big fr-zero">0<small>paused</small></td>'
        for _, q, _, _ in cols)
    value_row = ""
    if unit_price is not None:
        cells = "".join('<td class="fr-na">—</td>' if not q else f"<td>₹{q * unit_price:,.0f}</td>" for _, q, _, _ in cols)
        value_row = f'<tr><th scope="row">Order value</th>{cells}</tr>'
    stock = "".join(f"<td>{u:,.0f}</td>" for _, _, u, _ in cols)
    cover = "".join(f'<td class="is-{_status(c, lo, hi)[0]}"><b>{wk(c, lo, hi)}</b></td>' for *_, c in cols)
    status = "".join(f'<td class="is-{_status(c, lo, hi)[0]}">{_status(c, lo, hi)[1]}</td>' for *_, c in cols)
    return (
        '<table class="fr-tbl"><thead><tr><th></th>' + head + "</tr></thead><tbody>"
        f'<tr><th scope="row">Order (units)</th>{order}</tr>' + value_row +
        f'<tr><th scope="row">Stock (units)</th>{stock}</tr>'
        f'<tr><th scope="row">Weeks of cover{tip("Weeks of cover", "How many weeks the stock lasts at expected demand. Festival months add a 25% uplift first.", small=True)}</th>{cover}</tr>'
        f'<tr><th scope="row">Safe range {lo:g}–{hi:g} wk{tip("Safe range", "Minimum to maximum weeks of cover for this product. Inside the range is healthy.", small=True)}</th>{status}</tr>'
        "</tbody></table>"
    )


def facts2(change_pct: float, standard_qty: int, flags: list[str]) -> str:
    """Three compact context rows under the table (stock is already in the table)."""
    sign = "+" if change_pct >= 0 else "−"
    chips = "".join(badge(f) for f in flags)
    return (
        '<dl class="fr-facts">'
        f'<dt>Sales, last 4 wk</dt><dd><b>{sign}{abs(change_pct):.1f}%</b> vs 12-week average</dd>'
        f'<dt>Normal order</dt><dd><b>{standard_qty:,}</b> units</dd>'
        f'<dt>Rules fired</dt><dd>{chips}</dd>'
        '</dl>'
    )
