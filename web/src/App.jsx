import { useState } from "react";
import AllSkus from "./components/AllSkus";
import Header from "./components/Header";
import Orders from "./components/Orders";
import Rack from "./components/Rack";
import ReviewCard from "./components/ReviewCard";
import { Tip } from "./components/ui";
import { useApp } from "./lib/app";

function Stats({ d }) {
  const c = d.counts, none = c.skus - c.review - c.auto, done = c.review - d.pending.length;
  return (
    <section className="stats">
      {[["SKUs", c.skus, "sku"], ["Review", c.review, "review"], ["Auto", c.auto, "auto"], ["No order", none, "noorder"]].map(([name, n, tip]) => (
        <div className="stat" key={name}><span>{name}<Tip k={tip} /></span><b>{n}</b></div>
      ))}
      {c.review > 0 && <div className="progress" role="progressbar" aria-valuenow={done} aria-valuemax={c.review}><i style={{ width: `${(done / c.review) * 100}%` }} /><small>{d.pending.length ? `${done} of ${c.review} exceptions decided` : `All ${c.review} exceptions decided`}</small></div>}
    </section>
  );
}

export default function App() {
  const { data: d, busy, error, flash, clearError, plan, generate, reviewer } = useApp();
  const [tab, setTab] = useState("review");
  const [sel, setSel] = useState(null);
  if (!d) {
    return (
      <main className="app"><Header />
        {busy ? <p className="loading">Loading…</p> : (
          <section className="panel empty">
            <h3>No planning run yet</h3>
            <p className="lead">Plan on the SAP files already on the server, or use the upload button (top right) to add fresh ones.</p>
            {error && <div className="notice warn">{error}</div>}
            <button className="btn btn-primary" onClick={() => plan([])}>Run planning</button>
          </section>
        )}
      </main>
    );
  }

  const dec = Object.fromEntries(d.decisions.map((x) => [x.sku_id, x]));
  const needs = d.rows.filter((r) => r.status === "NEEDS_REVIEW");
  const auto = d.rows.filter((r) => r.status === "AUTO_APPROVED");
  const open = needs.filter((r) => d.pending.includes(r.sku_id)).sort((a, b) => b.is_urgent - a.is_urgent || a.sku_id.localeCompare(b.sku_id));
  const decided = needs.filter((r) => !d.pending.includes(r.sku_id));
  const card = (r, variant = "open", onSaved) => <ReviewCard key={r.sku_id + (dec[r.sku_id]?.timestamp || "")} r={r} d={dec[r.sku_id]} variant={variant} onSaved={onSaved} />;
  const advance = (sku) => {          // after a save, bring the next undecided exception into view
    const next = open.find((r) => r.sku_id !== sku);
    if (tab === "stock") setSel(next ? next.sku_id : null);
    else if (next) setTimeout(() => document.getElementById(`card-${next.sku_id}`)?.scrollIntoView({ behavior: "smooth", block: "start" }), 250);
  };
  const tabs = [["review", `Review · ${d.pending.length}`], ["stock", "Stock"], ["orders", "Orders"], ["all", "All SKUs"]];
  const selRow = d.rows.find((r) => r.sku_id === sel);
  const selVariant = !selRow ? "" : selRow.status === "NEEDS_REVIEW" ? "open" : selRow.status === "AUTO_APPROVED" ? "auto" : "info";
  const ready = d.pending.length === 0 && !d.po_ready;

  return (
    <main className="app">
      <Header d={d} />
      <div className="summary">
        <div className="summary-text">
          <h2>{d.pending.length ? `${d.pending.length} line${d.pending.length === 1 ? "" : "s"} need${d.pending.length === 1 ? "s" : ""} your call.` : d.po_ready ? "Purchase orders are ready." : "Everything is decided."}</h2>
          <p className="runline">Run <b>{d.id}</b>{d.festival && <> · festival month, demand +{Math.round((d.uplift - 1) * 100)}%<Tip k="festival" /></>}</p>
        </div>
        <Stats d={d} />
      </div>
      <nav className="tabs" role="tablist">{tabs.map(([k, t]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "tab on" : "tab"} onClick={() => setTab(k)}>{t}</button>)}</nav>

      {tab === "review" && (
        <>
          {needs.length === 0 && <p className="lead">No exceptions this run.</p>}
          <div className="list">{open.map((r) => card(r, "open", advance))}</div>
          {decided.length > 0 && <h4 className="divider">Decided · {decided.length}</h4>}
          <div className="list">{decided.map((r) => card(r, "open", advance))}</div>
          {auto.length > 0 && (
            <details className="auto-block">
              <summary>Auto-approved · {auto.length} <Tip k="auto" /></summary>
              <p className="lead"><b>{auto.length} lines ordered by the rules with nothing unusual.</b> They go into the POs as shown. Edit one only if your judgment differs.</p>
              <div className="list">{auto.map((r) => card(r, "auto"))}</div>
            </details>
          )}
        </>
      )}
      {tab === "stock" && (
        <div className="rack-layout">
          <Rack d={d} sel={sel} setSel={setSel} />
          {selRow ? <aside className="sheet"><button className="sheet-x" aria-label="Close" onClick={() => setSel(null)}>×</button>{card(selRow, selVariant, advance)}</aside>
            : <aside className="sheet sheet-empty">Click a bay on the rack to see its stock and decide.</aside>}
        </div>
      )}
      {tab === "orders" && <Orders d={d} />}
      {tab === "all" && <AllSkus rows={d.rows} />}

      {ready && tab !== "orders" && (
        <div className="stickybar"><span>{needs.length ? `All ${needs.length} exceptions decided.` : "No exceptions."}</span>
          <button className="btn btn-primary" disabled={busy || !reviewer.trim()} onClick={() => generate().then((r) => r && setTab("orders"))}>Generate purchase orders</button>
          {!reviewer.trim() && <small>Add your name at the top first.</small>}
        </div>
      )}
      {error && <div className="toast toast-err" role="alert" onClick={clearError}>{error}</div>}
      {!error && flash && <div className="toast" role="status">{flash}</div>}
      {busy && <div className="busy" aria-hidden />}
    </main>
  );
}
