import { useMemo } from "react";
import { num } from "../lib/glossary";
import { Tip } from "./ui";

const SCALE = 16; // weeks shown on the rack ruler

function Bay({ r, dec, pending, selected, onPick }) {
  const cover = Math.min(r.weeks_of_cover, SCALE);
  const after = Math.min(r.weeks_of_cover_after_order, SCALE);
  const state = r.weeks_of_cover < r.min_weeks ? "low" : r.weeks_of_cover > r.max_weeks ? "high" : "ok";
  const mark = pending ? "ask" : dec ? (dec.decision === "reject" ? "no" : "yes") : "";
  return (
    <button className={`bay bay-${state} ${selected ? "sel" : ""}`} onClick={() => onPick(r.sku_id)} aria-label={`${r.sku_name}: ${r.weeks_of_cover.toFixed(1)} weeks of cover`}>
      <span className="bay-head">
        <i className={`mark mark-${mark}`}>{mark === "ask" ? "!" : mark === "yes" ? "✓" : mark === "no" ? "✕" : ""}</i>
        <b>{r.order_qty > 0 ? `+${num(dec ? dec.final_qty : r.order_qty)}` : ""}</b>
      </span>
      <span className="stack" style={{ "--c": cover, "--a": after, "--min": Math.min(r.min_weeks, SCALE), "--max": Math.min(r.max_weeks, SCALE) }}>
        <span className="band" />
        {after > cover && <span className="ghost" />}
        <span className="cartons" />
      </span>
      <span className="bay-foot"><b>{r.sku_id.replace("SKU", "")}</b><em>{r.sku_name.replace("Freshroots ", "")}</em><small>{r.weeks_of_cover.toFixed(1)} wks</small></span>
    </button>
  );
}

export default function Rack({ d, sel, setSel }) {
  const dec = useMemo(() => Object.fromEntries(d.decisions.map((x) => [x.sku_id, x])), [d.decisions]);
  const zones = useMemo(() => {
    const by = {};
    d.rows.forEach((r) => (by[r.distributor_id] ||= { name: r.distributor_name, rows: [] }).rows.push(r));
    return Object.entries(by).sort(([a], [b]) => a.localeCompare(b)).map(([id, z]) => ({ id, ...z }));
  }, [d.rows]);

  return (
    <section className="rack-wrap">
      <div className="legend">
        <span><i className="lg lg-low" />Below min <Tip text="Stock covers fewer weeks than the minimum." /></span>
        <span><i className="lg lg-ok" />In range</span>
        <span><i className="lg lg-high" />Above max</span>
        <span><i className="lg lg-ghost" />Incoming order <Tip text="Dashed boxes show what the order adds to the shelf." /></span>
      </div>
      <div className="rack">
        {zones.map((z) => (
          <div className="shelf" key={z.id}>
            <div className="shelf-label">{z.name}</div>
            <div className="bays">{z.rows.map((r) => <Bay key={r.sku_id} r={r} dec={dec[r.sku_id]} pending={d.pending.includes(r.sku_id)} selected={sel === r.sku_id} onPick={setSel} />)}</div>
            <div className="beam" />
          </div>
        ))}
      </div>
      <small className="rack-note">Each carton is one week of cover. Green band is the safe range (min to max weeks). Tap a bay to review it.</small>
    </section>
  );
}
