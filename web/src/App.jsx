import { useState } from "react";
import AllSkus from "./components/AllSkus";
import Header from "./components/Header";
import Orders from "./components/Orders";
import ReviewCard from "./components/ReviewCard";
import { Tip } from "./components/ui";
import { useApp } from "./lib/app";

function Stats({ d }) {
  const c = d.counts, none = c.skus - c.review - c.auto, done = c.review - d.pending.length;
  return (
    <section className="stats">
      {[["SKUs", c.skus, "sku"], ["Review", c.review, "review"], ["Auto", c.auto, "auto"], ["No order", none, "noorder"]].map(([name, n, tip]) => (
        <div className="stat" key={name}><span>{name} <Tip k={tip} /></span><b>{n}</b></div>
      ))}
      {c.review > 0 && <div className="progress"><i style={{ width: `${(done / c.review) * 100}%` }} /><small>{done} of {c.review} exceptions decided</small></div>}
    </section>
  );
}

export default function App() {
  const { data: d, busy, error, flash, clearError } = useApp();
  const [tab, setTab] = useState("review");
  const [mode, setMode] = useState("cards");
  if (!d) return <main className="app"><Header />{error ? <div className="notice warn">{error}</div> : <p className="loading">Loading…</p>}</main>;

  const dec = Object.fromEntries(d.decisions.map((x) => [x.sku_id, x]));
  const needs = d.rows.filter((r) => r.status === "NEEDS_REVIEW");
  const auto = d.rows.filter((r) => r.status === "AUTO_APPROVED");
  const open = needs.filter((r) => d.pending.includes(r.sku_id)).sort((a, b) => b.is_urgent - a.is_urgent);
  const decided = needs.filter((r) => !d.pending.includes(r.sku_id));
  const list = (rows) => rows.map((r) => <ReviewCard key={r.sku_id + (dec[r.sku_id]?.timestamp || "")} r={r} d={dec[r.sku_id]} compact={mode === "rows"} />);
  const tabs = [["review", `Review · ${d.pending.length}`], ["auto", `Auto · ${auto.length}`], ["orders", "Orders"], ["all", "All SKUs"]];

  return (
    <main className="app">
      <Header d={d} />
      <p className="runline">Run <b>{d.id}</b>{d.festival && ` · festival month, demand +${Math.round((d.uplift - 1) * 100)}%`}<Tip k="festival" /></p>
      <Stats d={d} />
      <nav className="tabs">{tabs.map(([k, t]) => <button key={k} className={tab === k ? "tab on" : "tab"} onClick={() => setTab(k)}>{t}</button>)}</nav>
      {(tab === "review" || tab === "auto") && (
        <div className="seg" role="group" aria-label="View">{["cards", "rows"].map((m) => <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>{m === "cards" ? "Cards" : "Rows"}</button>)}</div>
      )}
      {tab === "review" && (needs.length === 0 ? <p>No exceptions this run.</p> : <>{list(open)}{decided.length > 0 && <h4 className="divider">Decided · {decided.length}</h4>}{list(decided)}</>)}
      {tab === "auto" && <><p className="lead">{auto.length} lines ordered by the rules with nothing unusual. They go into the POs as shown.</p>{list(auto)}</>}
      {tab === "orders" && <Orders d={d} />}
      {tab === "all" && <AllSkus rows={d.rows} />}
      {error && <div className="toast toast-err" onClick={clearError}>{error}</div>}
      {!error && flash && <div className="toast">{flash}</div>}
      {busy && <div className="busy" aria-hidden />}
    </main>
  );
}
