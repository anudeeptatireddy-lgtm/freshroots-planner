import { useState } from "react";
import { num } from "../lib/glossary";
import { Tip } from "./ui";

const STATUS = { NEEDS_REVIEW: "Needs review", AUTO_APPROVED: "Auto-approved", NO_ORDER: "No order" };
const COLS = [
  ["sku_id", "SKU"], ["status", "Status"], ["weeks_of_cover", "Cover (wk)", "cover"], ["order_qty", "Order"], ["weeks_of_cover_after_order", "After (wk)"],
  ["flag", "Flag"], ["change_4w_vs_12w", "4w vs 12w"], ["forecast_total_4w", "4-week forecast"], ["exceptions", "Exceptions"], ["sku_name", "Product"],
];

export default function AllSkus({ rows }) {
  const [filter, setFilter] = useState("ALL");
  const [sort, setSort] = useState(["sku_id", 1]);
  const shown = rows.filter((r) => filter === "ALL" || r.status === filter).sort((a, b) => {
    const [k, dir] = sort, x = a[k] ?? "", y = b[k] ?? "";
    return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
  });
  const fmt = (r, k) => (k === "status" ? STATUS[r.status] : k === "change_4w_vs_12w" ? (r[k] == null ? "–" : `${r[k] >= 0 ? "+" : "−"}${Math.abs(r[k] * 100).toFixed(1)}%`) : k === "weeks_of_cover" || k === "weeks_of_cover_after_order" ? num(r[k], 1) : typeof r[k] === "number" ? num(r[k]) : r[k] || "–");
  return (
    <section className="panel">
      <label className="filter">Show
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="ALL">All statuses ({rows.length})</option>
          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v} ({rows.filter((r) => r.status === k).length})</option>)}
        </select>
      </label>
      <div className="scroll">
        <table className="table wide">
          <thead><tr>{COLS.map(([k, h, tip]) => <th key={k} onClick={() => setSort([k, sort[0] === k ? -sort[1] : 1])} className="sortable" aria-sort={sort[0] === k ? (sort[1] > 0 ? "ascending" : "descending") : "none"}>{h}{sort[0] === k && (sort[1] > 0 ? " ↑" : " ↓")}{tip && <Tip k={tip} />}</th>)}</tr></thead>
          <tbody>{shown.map((r) => <tr key={r.sku_id}>{COLS.map(([k]) => <td key={k} className={k === "sku_id" ? "sticky-col" : ""}>{k === "order_qty" ? <b>{fmt(r, k)}</b> : fmt(r, k)}</td>)}</tr>)}</tbody>
        </table>
      </div>
      <small>Scroll the table sideways for flag, demand change, 4-week forecast and exceptions. Click a column name to sort.</small>
    </section>
  );
}
