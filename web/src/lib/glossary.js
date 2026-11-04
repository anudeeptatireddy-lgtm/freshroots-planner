// Plain-language meanings, shown behind the "?" next to each term.
export const TIPS = {
  sku: "One product, for example one flavour and pack size.",
  review: "Lines a person must decide on before any purchase order (PO) can be made.",
  auto: "Lines the rules approved on their own: an order is needed and nothing looks unusual.",
  noorder: "Healthy or overstocked: no order this run. See All SKUs.",
  cover: "Weeks of cover: how many weeks the stock lasts at expected demand. Festival months add a 25% uplift first.",
  band: "Minimum to maximum weeks of cover for this product. Inside the range is healthy.",
  festival: "Festival month: expected demand is raised by 25% because shoppers buy more.",
  override: "Share of decided lines where the final quantity differs from the system quantity. A rejected order counts.",
  run: "One planning snapshot, named by the date of the stock count.",
  URGENT: "Cover is below the safe minimum right now. Decide these first.",
  HEALTHY: "Cover is inside the safe band and demand has not jumped. Nothing to order.",
  STOCKOUT_RISK: "Cover is below the minimum (6 weeks, or 3 for perishables). The rules order now and mark it URGENT.",
  HIGH_DEMAND: "The last 4 weeks sold more than 20% above the 12-week average. The order is 1.5x the standard quantity.",
  OVERSTOCK: "Cover is above the maximum (14 weeks, or 4 for perishables). The order is paused at 0.",
  NOT_PLANNED: "The rules did not plan this product this run. The exception reason says why.",
  BORDERLINE: "A value sits close to a rule threshold: within 2 points of the +20% demand line, or within 0.25 weeks of a band edge. A small data change would flip the decision.",
  BELOW_MIN_AFTER_ORDER: "Even after the recommended order, cover stays below the minimum. A top-up quantity is suggested.",
  ABOVE_MAX_AFTER_ORDER: "The recommended order would push cover above the maximum. A smaller quantity is suggested.",
  NEW_LAUNCH: "Fewer than 12 weeks of sales history, so the demand average is not reliable. Check against the launch plan.",
  DATA_ISSUE: "Something in the SAP data for this product is missing or looks wrong. Check it before ordering.",
  SHARP_DROP: "The last 4 weeks fell more than 30% against the 12-week average. The rules do not cover falling demand. Check for a delisting or data error.",
  DISTRIBUTOR_ANOMALY: "One distributor's 4-week sales moved more than 50% (a placeholder in config.yaml) against its 12-week average. Only active when distributor-level sales are supplied.",
  HIGH_VALUE: "The order value is above the review limit set in config.yaml. Only active when prices and a limit are supplied.",
};

export const FLAG_LABEL = {
  HIGH_DEMAND: "High demand", STOCKOUT_RISK: "Stockout risk", OVERSTOCK: "Overstock", HEALTHY: "Healthy", NOT_PLANNED: "Not planned",
};

export const label = (code) => (code || "").replaceAll("_", " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
export const num = (v, d = 0) => (v == null || Number.isNaN(Number(v)) ? "–" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d }));
export const money = (v) => (v == null ? "–" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
