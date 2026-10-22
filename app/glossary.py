"""Plain-English meanings shown behind the ? marks. Numbers come from config so they never drift."""
from __future__ import annotations

from html import escape


class Glossary:
    def __init__(self, cfg: dict):
        ec, thr, mult = cfg["exceptions"], cfg["rules"]["high_demand_threshold"], cfg["rules"]["high_demand_multiplier"]
        self.flags = {
            "URGENT": "Stock cover is below the minimum weeks for this product, so an order is needed now.",
            "HIGH_DEMAND": f"Sales over the last 4 weeks are more than {thr:.0%} above the 12-week average. The rule orders {mult:g}x the standard quantity.",
            "STOCKOUT_RISK": "Stock lasts fewer weeks than the minimum (3 weeks for perishables, 6 for others), so you may run out before the next delivery.",
            "OVERSTOCK": "Stock lasts more weeks than the maximum (4 for perishables, 14 for others). The rule is to pause the next order.",
            "HEALTHY": "Stock is between the minimum and maximum weeks and demand is not spiking. No order this run.",
            "BORDERLINE": f"Close to a rule line (within {ec['borderline_change_pp'] * 100:g} points of the {thr:.0%} demand trigger, or within {ec['borderline_weeks']:g} weeks of a min/max). A small data change would flip the decision, so a person confirms.",
            "BELOW_MIN_AFTER_ORDER": "Even after the recommended order, stock would still last fewer weeks than the minimum. A bigger top-up is suggested.",
            "ABOVE_MAX_AFTER_ORDER": "The recommended order would push stock above the maximum weeks. For perishables that risks write-off.",
            "NEW_LAUNCH": "Fewer than 12 weeks of sales history, so the averages are not reliable. A person decides.",
            "DATA_ISSUE": "Something in the input data for this product needs checking (a missing week, unknown ID, etc.). See data_quality_report.csv.",
            "SHARP_DROP": f"Demand fell by more than {abs(ec['sharp_drop_threshold']):.0%}. The rules do not cover falling demand, so a person decides.",
            "DISTRIBUTOR_ANOMALY": "A distributor's buying moved unusually. Only active when distributor-level sales are supplied.",
            "HIGH_VALUE": "The order value is above the review limit. Only active when prices are supplied.",
            "NOT_PLANNED": "The rules could not run because required data (stock, sales or master data) is missing.",
        }
        self.terms = {
            "On hand": "Units in the Pune Central Warehouse on the stock-count date, plus any open POs.",
            "4w vs 12w demand": f"Average weekly sales over the last 4 weeks compared with the last 12 weeks. More than +{thr:.0%} triggers the high-demand rule.",
            "System order qty": "What the rules recommend ordering. 0 means no order.",
            "Weeks of cover": f"How many weeks the current stock lasts at expected weekly demand. Festival months add a {cfg['festival']['uplift'] - 1:.0%} uplift to demand first.",
            "safe band": "Minimum to maximum weeks of cover for this product's perishability. Inside the green band is healthy.",
            "after order": "Weeks of cover you would have once the recommended order arrives.",
            "forecast": "Expected units over the next 4 weeks: the 12-week average times each week's festival uplift.",
        }

    @staticmethod
    def tip(text: str, right: bool = False) -> str:
        """A ? mark that shows `text` on hover (desktop) or tap (phone)."""
        return f'<i class="fr-tip{" r" if right else ""}" tabindex="0" data-tip="{escape(text, quote=True)}">?</i>'

    def flag_tip(self, code: str) -> str:
        return self.tip(self.flags.get(code, code))

    def term_tip(self, term: str, right: bool = False) -> str:
        return self.tip(self.terms[term], right)
