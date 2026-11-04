import { useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../lib/app";
import { num } from "../lib/glossary";
import { Tip } from "./ui";

const MIME = { pdf: "application/pdf", csv: "text/csv", md: "text/markdown", json: "application/json" };
/** With a database the file comes from the API; without one the browser already holds it (the run's bundle). */
const Download = ({ d, name, children, primary }) => {
  const b64 = d.bundle?.[name];
  const href = b64 ? `data:${MIME[name.split(".").pop()] || "application/octet-stream"};base64,${b64}` : api.fileUrl(d.id, name);
  return <a className={`btn ${primary ? "btn-primary" : "btn-soft"}`} href={href} download={name}>{children}</a>;
};

function Zoho({ d }) {
  const { zoho, busy } = useApp();
  const z = d.zoho;
  const [ok, setOk] = useState(false);
  const todo = z.todo.length;
  return (
    <section className="panel">
      <h3>Send to Zoho</h3>
      <button className="btn btn-soft" disabled={busy} onClick={() => zoho("preview")}>Preview Zoho drafts (dry run)</button>
      {z.preview && (
        <div className="notice">
          Preview only: nothing was sent.
          {z.preview.purchase_orders.map((p) => <div key={p.po_number}><b>{p.po_number}</b> → {p.vendor}: {p.lines} lines, {num(p.units)} units, created as a draft</div>)}
          {z.preview.issues?.length > 0 && <ul>{z.preview.issues.map((i) => <li key={i}>{i}</li>)}</ul>}
        </div>
      )}
      {Object.keys(z.sent).length > 0 && <div className="notice ok">Already in Zoho as drafts: {Object.entries(z.sent).map(([po, v]) => `${po} (${v.detail})`).join(", ")}</div>}
      <label className="check"><input type="checkbox" checked={ok} disabled={!z.live || !todo} onChange={(e) => setOk(e.target.checked)} />
        I understand this creates {todo} draft PO{todo === 1 ? "" : "s"} in Zoho</label>
      <button className="btn btn-primary" disabled={busy || !z.live || !todo || !ok} onClick={() => zoho("send", true).then(() => setOk(false))}>Send to Zoho</button>
      {!z.live && <small>Sending is locked: Zoho credentials are missing or live sending is switched off.</small>}
    </section>
  );
}

export default function Orders({ d }) {
  const { generate, busy, reviewer } = useApp();
  const pending = d.pending;
  if (!d.po_ready) {
    return (
      <section className="panel">
        {pending.length > 0 && <div className="notice warn"><b>{pending.length} exception{pending.length === 1 ? "" : "s"} still need a decision</b><br />Purchase orders can be generated once every exception is decided. Open the Review tab to decide them.
          <ul>{pending.map((s) => <li key={s}><b>{s}</b> {d.rows.find((r) => r.sku_id === s)?.sku_name}{d.rows.find((r) => r.sku_id === s)?.is_urgent && " · URGENT"}</li>)}</ul></div>}
        <button className="btn btn-primary" disabled={busy || pending.length > 0} onClick={generate}>Generate purchase orders</button>
        <small>{pending.length ? `Unlocks when all ${d.counts.review} exceptions are decided. ` : "Builds one PO per supplier from approved lines, plus the Zoho import file and a handoff note. "}The {d.counts.auto} auto-approved lines are included automatically.{pending.length === 0 && !reviewer.trim() && " Add your name at the top first."}</small>
      </section>
    );
  }
  const rl = d.run_log, rate = d.stats.override_rate;
  return (
    <>
      <section className="panel">
        <div className="notice ok"><b>{rl.po_count} purchase orders ready</b> · {rl.po_line_count} lines · {rl.lines_held_back} held back</div>
        <div className="override">
          <span>Override rate <Tip k="override" /></span>
          <b>{rate == null ? "n/a" : `${Math.round(rate * 100)}%`}</b>
          <div className="meter"><i style={{ width: `${Math.min(100, (rate || 0) * 100)}%` }} /><em /></div>
          <small>{d.stats.overrides} of {d.stats.decided_lines} decided lines</small>
        </div>
        {rate > 0.3 && <div className="notice">Above 30% this run. One run is not a trend; if it stays above 30% over several runs, the rules may not match reality and are worth revisiting.</div>}
        <Download d={d} name="purchase_orders_zoho_import.csv" primary>Download Zoho import (CSV)</Download>
      </section>
      {d.orders.map((o) => (
        <section className="panel" key={o.po}>
          <div className="card-head"><div><b>{o.po}</b><small>{o.vendor} · {o.lines.length} line{o.lines.length === 1 ? "" : "s"} · {num(o.units)} units</small></div>
            <Download d={d} name={o.pdf}>PDF</Download></div>
          <table className="table"><thead><tr><th>SKU</th><th>Product</th><th>Final</th><th>System</th><th>Source</th></tr></thead>
            <tbody>{o.lines.map((l) => <tr key={l.sku}><td>{l.sku}</td><td>{l.name}</td><td><b>{num(l.final)}</b></td><td>{num(l.system)}</td><td>{l.source}</td></tr>)}</tbody></table>
        </section>
      ))}
      {!d.rows.some((r) => r.unit_price != null) && <small className="foot">Unit prices are not in this run's data, so order values are not shown.</small>}
      <Zoho d={d} />
      <section className="panel row-btns">
        <Download d={d} name="sourcing_handoff.md">Sourcing handoff note</Download>
        <Download d={d} name="review_log.csv">Review log (CSV)</Download>
      </section>
    </>
  );
}
