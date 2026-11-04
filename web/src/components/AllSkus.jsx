import { FLAG_LABEL, num } from "../lib/glossary";

const STATUS = { NEEDS_REVIEW: "Review", AUTO_APPROVED: "Auto", NO_ORDER: "No order" };

export default function AllSkus({ rows }) {
  return (
    <section className="panel">
      <table className="table">
        <thead><tr><th>SKU</th><th>Product</th><th>Cover</th><th>Status</th><th>Order</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.sku_id}><td>{r.sku_id}</td><td>{r.sku_name}<small>{FLAG_LABEL[(r.flag || "").split(" + ")[0]] || r.flag}</small></td>
            <td>{num(r.weeks_of_cover, 1)} wks</td><td>{STATUS[r.status]}</td><td><b>{num(r.order_qty)}</b></td></tr>
        ))}</tbody>
      </table>
    </section>
  );
}
