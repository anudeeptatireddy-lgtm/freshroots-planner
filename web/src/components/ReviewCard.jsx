import { useState } from "react";
import { useApp } from "../lib/app";
import { FLAG_LABEL, TIPS, money, num } from "../lib/glossary";
import { Chip, CoverBar, Tip } from "./ui";

const PAST = { approve: "Approved", edit: "Changed", reject: "Rejected" };

export default function ReviewCard({ r, d, compact = false }) {
  const { decide, busy } = useApp();
  const [reopened, setReopened] = useState(false);
  const [qty, setQty] = useState(String(d ? d.final_qty : r.order_qty));
  const [note, setNote] = useState(d?.note || "");
  const done = d && !reopened;
  const n = Number(qty);
  const valid = qty !== "" && Number.isInteger(n) && n >= 0;
  const same = n === r.order_qty;
  const save = (action) => decide([{ sku: r.sku_id, action, qty: action === "reject" ? 0 : n, note }], `${r.sku_id} ${PAST[action].toLowerCase()}.`).then((x) => x && setReopened(false));
  const isAuto = d && String(d.reviewer).startsWith("system:");

  if (done) {
    return (
      <article className={`card card-done ${compact ? "compact" : ""}`}>
        <div className="card-head">
          <div><b>{r.sku_name}</b><small>{r.sku_id} · {r.category}</small></div>
          <span className={`chip chip-${d.decision}`}>{isAuto ? "Auto" : PAST[d.decision]} · {num(d.final_qty)}</span>
        </div>
        <button className="btn btn-ghost" onClick={() => setReopened(true)}>Change</button>
      </article>
    );
  }
  return (
    <article className={`card ${r.is_urgent ? "card-urgent" : ""} ${compact ? "compact" : ""}`}>
      <div className="card-head">
        <div><b>{r.sku_name}</b><small>{r.sku_id} · {r.category} · {r.distributor_name} · {money(r.unit_price)} each</small></div>
        <div className="chips">
          {r.is_urgent && <span className="chip chip-urgent">Urgent</span>}
          {(r.flag || "").split(" + ").filter(Boolean).map((f) => <Chip key={f} code={f} />)}
          {r.exceptions && <Chip code={r.exceptions} tone="exception" />}
        </div>
      </div>
      <div className="facts">
        <span>On hand <b>{num(r.units_on_hand)}</b></span>
        <span>Demand / wk <b>{num(r.adjusted_weekly_demand)}</b></span>
        <span>Cover <Tip k="cover" /> <b>{num(r.weeks_of_cover, 1)}</b> → <b>{num(r.weeks_of_cover_after_order, 1)}</b> wks</span>
      </div>
      <CoverBar now={r.weeks_of_cover} after={r.weeks_of_cover_after_order} min={r.min_weeks} max={r.max_weeks} />
      {!compact && <p className="why">{r.exception_reasons || r.flag_reasons}</p>}
      {r.suggested_qty != null && !compact && (
        <button className="btn btn-soft" onClick={() => setQty(String(r.suggested_qty))}>Use suggested {num(r.suggested_qty)} <Tip k="suggested" /></button>
      )}
      <div className="decide">
        <label className="qty">
          <span>Order qty</span>
          <input inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value.replace(/\D/g, ""))} />
          <small>system {num(r.order_qty)}</small>
        </label>
        {!compact && <input className="note" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />}
        <button className="btn btn-primary" disabled={busy || !valid} onClick={() => save(same ? "approve" : "edit")}>
          {same ? `Approve ${num(n)}` : `Approve ${num(n)} (changed)`}
        </button>
        <button className="btn btn-ghost" disabled={busy} onClick={() => save("reject")}>Reject</button>
      </div>
    </article>
  );
}
