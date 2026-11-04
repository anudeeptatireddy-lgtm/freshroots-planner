import { useState } from "react";
import { useApp } from "../lib/app";
import { band, coverAfter, flagsOf, headline, parts, planned, wk } from "../lib/calc";
import { money, num } from "../lib/glossary";
import { Chip, Tip } from "./ui";

const LABEL = { approve: "Approved", edit: "Changed", reject: "Rejected" };
const NEED_NAME = "Add your name at the top to save decisions.";
const when = (t) => String(t).replace("T", " ").slice(0, 16);

function Compare({ r }) {
  const lo = r.min_weeks, hi = r.max_weeks, pos = r.inventory_position ?? r.units_on_hand;
  const cols = [["Now", null, pos, r.weeks_of_cover], ["Rules say", r.order_qty, pos + r.order_qty, coverAfter(r, r.order_qty)]];
  if (r.suggested_qty != null) cols.push(["Suggested", r.suggested_qty, pos + r.suggested_qty, coverAfter(r, r.suggested_qty)]);
  const cell = (q) => (q == null ? <td className="na">—</td> : q === 0 ? <td className="big zero">0<small>paused</small></td> : <td className="big">{num(q)}</td>);
  return (
    <table className="tbl">
      <thead><tr><th />{cols.map(([h], i) => <th key={h} className={i === 1 ? "rec" : ""}>{h}</th>)}</tr></thead>
      <tbody>
        <tr><th>Order (units)</th>{cols.map(([h, q]) => <Fragment2 key={h}>{cell(q)}</Fragment2>)}</tr>
        {r.unit_price != null && <tr><th>Order value</th>{cols.map(([h, q]) => <td key={h} className={q ? "" : "na"}>{q ? money(q * r.unit_price) : "—"}</td>)}</tr>}
        <tr><th>Stock (units)</th>{cols.map(([h, , u]) => <td key={h}>{num(u)}</td>)}</tr>
        <tr><th>Weeks of cover<Tip k="cover" /></th>{cols.map(([h, , , c]) => <td key={h} className={`is-${band(c, lo, hi)[0]}`}><b>{wk(c, lo, hi)}</b></td>)}</tr>
        <tr><th>Safe range {lo}–{hi} wk<Tip k="band" /></th>{cols.map(([h, , , c]) => <td key={h} className={`is-${band(c, lo, hi)[0]}`}>{band(c, lo, hi)[1]}</td>)}</tr>
      </tbody>
    </table>
  );
}
const Fragment2 = ({ children }) => children;

export default function ReviewCard({ r, d, variant = "open", onSaved }) {
  const { decide, busy, reviewer } = useApp();
  const [reopened, setReopened] = useState(false);
  const [qty, setQty] = useState(String(d ? d.final_qty : r.order_qty));
  const [note, setNote] = useState(d?.note || "");
  const human = d && !String(d.reviewer).startsWith("system:");
  const isDone = variant === "open" && d && !reopened;
  const n = Number(qty), valid = qty !== "" && Number.isInteger(n) && n >= 0, system = r.order_qty, changed = n !== system;
  const named = reviewer.trim().length > 0;
  const ok = planned(r);
  const save = (action) => decide([{ sku: r.sku_id, action, qty: action === "reject" ? 0 : n, note }], `Saved: ${r.sku_id} ${LABEL[action].toLowerCase()} at ${num(action === "reject" ? 0 : n)}.`)
    .then((x) => { if (x) { setReopened(false); onSaved?.(r.sku_id); } });
  const [h1, h2] = ok ? headline(r) : ["", ""];

  const head = (
    <div className="card-head">
      <div>
        <b>{r.sku_name}</b>
        <small>{r.sku_id} · {r.distributor_name} · {r.perishability} perishability</small>
        <small>{r.category || "No category"} · {r.unit_price != null ? `${money(r.unit_price)} per unit` : "Price not in data"}</small>
      </div>
      {r.is_urgent && ok && <Chip code="URGENT" />}
    </div>
  );

  if (isDone) {
    return (
      <article className="card card-done" id={`card-${r.sku_id}`}>
        {head}
        <div className="done-line">
          <span className={`chip chip-${d.decision}`}>{LABEL[d.decision]}</span>
          <b>{num(d.final_qty)} units</b><small>System said {num(system)} · {human ? d.reviewer : "Auto"} · {when(d.timestamp)}</small>
        </div>
        {d.note && <p className="why">“{d.note}”</p>}
        <button className="btn btn-ghost" onClick={() => setReopened(true)}>Change decision</button>
      </article>
    );
  }
  return (
    <article className={`card ${r.is_urgent && variant === "open" ? "card-urgent" : ""}`} id={`card-${r.sku_id}`}>
      {head}
      {ok && <p className="headline"><b>{h1}</b> {h2}</p>}
      {ok && <Compare r={r} />}
      {variant === "open" && parts(r).map(([code, reason]) => (
        <div className="callout" key={code}><div className="callout-head"><span>Why this needs you</span><Chip code={code} /></div><div>{reason}</div></div>
      ))}
      {reopened && d && <p className="current">Current decision: <b>{LABEL[d.decision]} · {num(d.final_qty)}</b> by {d.reviewer}, {when(d.timestamp)}{d.note && ` · “${d.note}”`}</p>}
      {variant === "auto" && !human && <small>Goes into the PO at {num(system)} units. No decision needed; change the quantity only if you disagree.</small>}
      {variant !== "info" && (<>
      <input className="note" placeholder="Note (optional), e.g. promo confirmed with sales" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Note" />
      <div className="dec-bar">
        <input className="qty-in" inputMode="numeric" aria-label="Quantity (units)" value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))} />
        <button className="btn btn-primary" disabled={busy || !valid || !named} onClick={() => save(changed ? "edit" : "approve")}>
          {changed ? `Save · ${num(n)} (changed)` : system ? `Approve · ${num(system)}` : "Approve · 0 (paused)"}
        </button>
      </div>
      {ok && valid && <small className="preview">With {num(n)} units, stock lasts {wk(coverAfter(r, n), r.min_weeks, r.max_weeks)} weeks: {({ below: "below the safe range", in: "inside the safe range", above: "above the safe range" })[band(coverAfter(r, n), r.min_weeks, r.max_weeks)[0]]}.</small>}
      <div className="alt-bar">
        {r.suggested_qty != null && <button className="btn" onClick={() => setQty(String(r.suggested_qty))}>Use suggested · {num(r.suggested_qty)}</button>}
        <button className="btn btn-ghost" disabled={busy || !named} onClick={() => save("reject")}>Reject · 0</button>
      </div>
      {!named && <small className="need-name">{NEED_NAME}</small>}
      </>)}
      <dl className="facts2">
        <dt>Sales, last 4 wk</dt><dd><b>{r.change_4w_vs_12w >= 0 ? "+" : "−"}{Math.abs((r.change_4w_vs_12w ?? 0) * 100).toFixed(1)}%</b> vs 12-week average</dd>
        <dt>Normal order</dt><dd><b>{num(r.standard_reorder_qty)}</b> units</dd>
        <dt>Rules fired</dt><dd>{flagsOf(r).map((f) => <Chip key={f} code={f} />)}</dd>
      </dl>
      <details><summary>How the rules decided</summary><p className="why">{r.flag_reasons}</p></details>
    </article>
  );
}
