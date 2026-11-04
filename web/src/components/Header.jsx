import { useRef, useState } from "react";
import { useApp } from "../lib/app";

const REQUIRED = ["weekly_sales.csv", "sku_master.csv", "distributor_master.csv", "current_inventory.csv", "calendar.csv"];
const OPTIONAL = ["open_purchase_orders.csv", "sku_prices.csv", "distributor_sales.csv"];

function Upload() {
  const { plan, busy } = useApp();
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState([]);
  const [bad, setBad] = useState("");
  const ref = useRef();
  const onPick = async (e) => {
    const files = [...e.target.files];
    const unknown = files.filter((f) => ![...REQUIRED, ...OPTIONAL].includes(f.name)).map((f) => f.name);
    setPicked(files.map((f) => f.name));
    setBad(unknown.length ? `Unrecognised file name(s): ${unknown.join(", ")}.` : "");
    if (!unknown.length && files.length && (await plan(files))) setOpen(false);
    e.target.value = "";
  };
  return (
    <div className="upload">
      <button className="icon-btn" aria-label="Upload SAP files" onClick={() => setOpen(!open)}>↑</button>
      {open && (
        <div className="popover">
          <b>Upload SAP files</b>
          <small>A new run starts as soon as the files are added. Files you skip use the ones already on the server.</small>
          <ul className="checklist">{REQUIRED.map((n) => <li key={n} className={picked.includes(n) ? "on" : ""}>{n}</li>)}</ul>
          <small>Optional</small>
          <ul className="checklist">{OPTIONAL.map((n) => <li key={n} className={picked.includes(n) ? "on" : ""}>{n}</li>)}</ul>
          {bad && <div className="notice warn">{bad}</div>}
          <input ref={ref} type="file" accept=".csv" multiple hidden onChange={onPick} />
          <button className="btn btn-primary" disabled={busy} onClick={() => ref.current.click()}>{busy ? "Planning…" : "Choose files"}</button>
        </div>
      )}
    </div>
  );
}

export default function Header({ d }) {
  const { runs, openRun, busy, reviewer, setReviewer, plan } = useApp();
  return (
    <header className="top">
      <div className="brand"><span className="logo">Fr</span><div><h1>Freshroots</h1><small>Demand planning</small></div></div>
      <div className="top-actions">
        {runs.length > 1 && <select value={d?.id} onChange={(e) => openRun(e.target.value)} disabled={busy} aria-label="Run">{runs.map((id) => <option key={id}>{id}</option>)}</select>}
        <Upload />
      </div>
      {d && (
        <details className="run-details">
          <summary>Run details and new run</summary>
          <small>Source files: {Object.keys(d.run_log.file_hashes_sha256 || {}).join(", ") || "bundled files"}</small>
          <button className="btn" disabled={busy} onClick={() => plan([])} title="Plan again on the files already on the server. To use fresh SAP files, use the upload button.">Start a new run</button>
        </details>
      )}
      <label className="who"><span>Your name</span><input value={reviewer} onChange={(e) => setReviewer(e.target.value)} placeholder="Type your name" /></label>
    </header>
  );
}
