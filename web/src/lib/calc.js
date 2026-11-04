// Display helpers ported from the Streamlit design (fr_html.py / cards.py). No planning logic lives here: the rules already ran on the server.
export const wk = (v, lo, hi) => {
  const one = Math.round(v * 10) / 10;
  for (const e of [lo, hi]) if ((v < e) !== (one < e) || (v > e) !== (one > e)) return v.toFixed(2); // 5.95 vs a minimum of 6 must not read 6.0
  return v.toFixed(1);
};
export const band = (c, lo, hi) => (c < lo ? ["below", "↓ Low"] : c > hi ? ["above", "↑ High"] : ["in", "✓ OK"]);
export const planned = (r) => r.weeks_of_cover != null && r.adjusted_weekly_demand != null;
export const coverAfter = (r, q) => r.weeks_of_cover + q / r.adjusted_weekly_demand;
export const flagsOf = (r) => (r.flag || "").split(" + ").filter(Boolean);
export const parts = (r) => (r.exception_reasons ? r.exception_reasons.split(" | ") : []).map((c) => { const i = c.indexOf(": "); return [c.slice(0, i), c.slice(i + 2)]; });
const n0 = (v) => Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 });

export function headline(r) {
  const lo = r.min_weeks, hi = r.max_weeks, now = r.weeks_of_cover, after = r.weeks_of_cover_after_order, q = r.order_qty;
  const per = r.perishability === "High" ? " for perishables" : "";
  const g = (x) => wk(x, lo, hi);
  const first = now < lo ? `Stock lasts ${g(now)} weeks; the minimum${per} is ${lo}.` : now > hi ? `Stock lasts ${g(now)} weeks, over the ${hi}-week maximum${per}.` : `Stock lasts ${g(now)} weeks, inside the ${lo}–${hi} week band.`;
  if (!q || after == null) return [first, "The rules pause the order at 0."];
  const why = flagsOf(r).includes("HIGH_DEMAND") ? " (1.5× standard, for high demand)" : "";
  const rest = after < lo ? `The rules order ${n0(q)}${why}, but that only reaches ${g(after)} weeks.` : after > hi ? `The rules order ${n0(q)}${why}, which pushes it to ${g(after)} weeks, over the maximum.` : `The rules order ${n0(q)}${why}, which brings it to ${g(after)} weeks.`;
  return [first, rest];
}
