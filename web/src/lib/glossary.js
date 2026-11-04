// Plain-language meanings, shown behind the "?" next to each term.
export const TIPS = {
  sku: "One product, for example one flavour and pack size.",
  review: "Lines a person must decide on before any purchase order (PO) can be made.",
  auto: "Lines the rules approved on their own: an order is needed and nothing looks unusual.",
  noorder: "Healthy or overstocked: no order this run.",
  cover: "Weeks of cover: how many weeks the stock on hand lasts at the expected weekly demand.",
  festival: "Festival month: expected demand is raised by 25% because shoppers buy more.",
  override: "Share of decided lines where the final quantity differs from the system quantity. A rejected order counts.",
  run: "One planning snapshot, named by the date of the stock count.",
  HIGH_DEMAND: "The last 4 weeks sold at least 20% more than the 12-week average, so the order is 1.5x the standard quantity.",
  STOCKOUT_RISK: "Stock covers fewer weeks than the minimum for this product, so it could run out before the next delivery.",
  OVERSTOCK: "Stock covers more weeks than the maximum, so no order is placed.",
  HEALTHY: "Stock is inside the safe range and demand is normal. No order needed.",
  BORDERLINE: "Close to a rule threshold, so a small data change would flip the decision. A person should look.",
  BELOW_MIN_AFTER_ORDER: "Even after the recommended order, stock would still cover fewer weeks than the minimum.",
  ABOVE_MAX_AFTER_ORDER: "After the recommended order, stock would cover more weeks than the maximum.",
  NEW_LAUNCH: "Too little sales history to trust the forecast.",
  SHARP_DROP: "Sales fell sharply versus the 12-week average.",
  DATA_ISSUE: "The data for this product had a problem, such as missing weeks.",
  HIGH_VALUE: "The order is unusually large in value, so a person confirms it.",
  DISTRIBUTOR_ANOMALY: "This distributor's sales moved unusually compared with normal.",
  suggested: "The smallest top-up that brings stock back to the minimum weeks of cover.",
};

export const FLAG_LABEL = {
  HIGH_DEMAND: "High demand", STOCKOUT_RISK: "Stockout risk", OVERSTOCK: "Overstock", HEALTHY: "Healthy", NOT_PLANNED: "Not planned",
};

export const label = (code) => (code || "").replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
export const num = (v, d = 0) => (v == null || Number.isNaN(Number(v)) ? "–" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d }));
export const money = (v) => (v == null ? "–" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
