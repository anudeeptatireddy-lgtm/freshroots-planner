# Freshroots demand planner

Automates the data work behind Raghav Kulkarni's demand planning and applies his documented rules exactly,
so the forecast can run twice a week instead of once a month. It runs: load, validate and clean, organise,
apply rules, forecast, work out order quantities, human review, purchase orders, sourcing handoff.

It does **not** use machine learning or statistics, and it does **not** make judgment calls. Anything outside
the rules goes to a person as an exception.

## Setup

Python 3.11+.

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
# or: python -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

## Run

```bash
python -m planner run --data data/raw --run-date 2026-10-19      # stages 1-6, writes outputs/2026-10-19/
streamlit run app/review_app.py                                   # review exceptions, then generate POs
python -m planner run --data data/raw --auto-approve-rules-only   # scheduled/test path: no human, exceptions left out
python -m planner generate-pos --run-dir outputs/2026-10-19       # POs from review_log.csv (the app does this too)
pytest                                                            # all tests, including the acceptance table
```

`--run-date` defaults to the inventory `As_Of_Date`. A run folder is never overwritten: a re-run for the same date
writes `outputs/<date>_r2`, `_r3`, ... The review app opens the newest run.

### Outputs (`outputs/<run_date>/`)

| File | Contents |
|---|---|
| `planning_table.csv` | One row per SKU: Stage 3 fields, flags and reasons, order quantity, 4-week forecast, exceptions, status |
| `exceptions.csv` | The `NEEDS_REVIEW` lines with plain-English reasons and suggested alternatives |
| `data_quality_report.csv` | Every cleaning issue: file, row, SKU, issue, action taken, severity |
| `review_log.csv` | Append-only: SKU, system qty, final qty, decision, reviewer, note, timestamp |
| `purchase_orders_zoho_import.csv`, `PO_<number>.pdf` | One CSV row per PO line; one PDF per PO |
| `sourcing_handoff.md` | POs (urgent first) and everything excluded pending review |
| `run_log.json` | Run date, file hashes, row counts, issues, flag and exception counts, override count and rate |

Until the review step is done, only the first four stage 1-6 files exist (plus `run_log.json`).

## Rules (all thresholds in `config.yaml`)

1. Uplift first: `adjusted_weekly_demand = avg_weekly_12w x 1.25` in festival months (from `calendar.csv`, not hard-coded).
2. `weeks_of_cover > max_weeks` -> `OVERSTOCK`, order 0, "Pause next order". Stop for this SKU.
3. `change_4w_vs_12w > 20%` -> `HIGH_DEMAND`.
4. `weeks_of_cover < min_weeks` -> `STOCKOUT_RISK`.
5. Order: `HIGH_DEMAND` -> 1.5 x standard qty; `STOCKOUT_RISK` only -> 1.0 x standard qty (urgent); neither -> `HEALTHY`, 0.
6. Windows: High perishability 3-4 weeks, Low 6-14 weeks.

No caps or top-ups are added to the rule output. Where the literal result looks wrong, the line becomes an exception
with a suggested alternative.

Exceptions (`NEEDS_REVIEW`): `NEW_LAUNCH`, `DATA_ISSUE`, `BELOW_MIN_AFTER_ORDER`, `ABOVE_MAX_AFTER_ORDER`, `BORDERLINE`,
`SHARP_DROP`, plus the hooks `DISTRIBUTOR_ANOMALY` and `HIGH_VALUE`. A line that is not an exception and has
an order above 0 is `AUTO_APPROVED` (the reviewer can still edit it). Lines with no order and no exception are `NO_ORDER`.

## Assumptions and interpretation choices

These are the places the brief left room; each is a config value or a one-line change.

- **Weeks:** the 12-week window is the 12 complete ISO weeks before the run date (W31-W42 for 2026-10-19). Weeks are
  keyed on their Monday. A partial current week is excluded and logged.
- **Forecast weeks** start from the Monday of the run date's week and look up each Monday's month in `calendar.csv`.
- **Order quantities** round **up** to whole units (`rules.order_qty_rounding`). Nothing in the sample data needs rounding.
- **Urgent** is set whenever `STOCKOUT_RISK` is present, including together with `HIGH_DEMAND`.
- **`BORDERLINE`** is measured on today's cover (before the order), against the high-demand threshold (2 percentage points)
  and the min/max weeks (0.25 weeks). Only thresholds relevant to the branch are checked; an `OVERSTOCK` line is checked
  against the maximum only.
- **`ABOVE_MAX_AFTER_ORDER`** only applies when the order is above 0. Otherwise every `OVERSTOCK` line (cover after order = cover now)
  would trigger it.
- **New launch** = fewer than 12 weeks between the first sales week and the last complete week. Weeks before launch are not
  "missing". The rules are computed for display but the line always goes to review.
- **Missing weeks** after a SKU's first sale week, inside the window, are treated as missing (not zero) and route the SKU to `DATA_ISSUE`.
- **Zero sales weeks** are kept in the averages but flagged for review (a zero can be real or a stock-out week). Options: `cleaning.zero_units_action`.
- **Duplicates** (same SKU + week): the last row is kept (`cleaning.duplicate_keep`). A copy with a different value inside the window routes the SKU to review.
- **Inventory date** that differs from the run date routes that SKU to review.
- **SKUs that cannot be planned** (not in the master, no inventory, no sales, bad perishability or standard quantity) still appear in
  the planning table as `NOT_PLANNED` with a `DATA_ISSUE` exception. Nothing is dropped silently.
- **Distributors outside Maharashtra/Goa** (DIST003 Karnataka, DIST004 Gujarat in the sample) are noted as info only, not as an issue.
  Treating them as an issue would send SKU011 to review, contradicting the expected auto-approvals.
- **Override** = final quantity differs from system quantity (rejecting a line with a quantity above 0 counts). The rate's denominator is
  decided lines where either quantity is above 0. Auto-approvals by `--auto-approve-rules-only` are logged as `system:` decisions,
  count in the denominator as non-overrides, and do not count as human decisions.
- **PO numbers** are `FR-PO-<YYYYMMDD>-<NN>`, numbered by sorted vendor ID, one PO per counterparty per run.

## Known data gaps (handled explicitly, nothing invented)

1. **No open purchase orders.** Open PO quantity is 0. Provide `data/raw/open_purchase_orders.csv` (`SKU_ID, Open_PO_Qty`) and
   the inventory position becomes stock + open POs.
2. **No unit prices or lead times.** PO prices are blank and no order value is calculated unless `data/raw/sku_prices.csv`
   (`SKU_ID, Unit_Price`) is supplied. Lead times are not used anywhere.
3. **Who receives the PO.** The only party linked to a SKU is `sku_master.Distributor_ID`, so POs are grouped by it and labelled
   "Supplier (from sku_master.Distributor_ID)". Change `po.counterparty_column` or `po.vendor_overrides` in `config.yaml` once
   procurement confirms the real supplier.
4. **Sales are SKU-level, not distributor-level.** `DISTRIBUTOR_ANOMALY` is a hook: it switches on when
   `data/raw/distributor_sales.csv` (`Distributor_ID, SKU_ID, Week, Units_Sold`) exists. Its threshold
   (`exceptions.distributor_anomaly_change`, 50%) is a **placeholder**: confirm it with Raghav.
   `HIGH_VALUE` is likewise inactive until prices exist and `exceptions.high_value_threshold` is set.
5. **Scale.** Nothing is hard-coded to the sample (15 SKUs, 4 distributors). The case describes 400 SKUs and 1,200 distributors.
   Calendar rows are needed for the run month and the four forecast months, otherwise the run stops.

**Zoho import:** the column names are in `config.yaml` (`po.zoho_columns`). They are a best guess and **must be checked against
Zoho Inventory's actual import screen** before first use.

## Operating model

- **Schedule:** twice a week (Monday and Thursday) after the SAP export lands.
- **Owners:** IT owns the SAP export into `data/raw/`. Raghav owns review and exceptions. Procurement owns PO release in Zoho.
  Sourcing receives `sourcing_handoff.md`.
- **Measurement (90-day pilot):** every `run_log.json` records flag counts, exception counts, override count and override rate.
  Track stockout incidents and overstock value against the same period last year outside this tool.
- **Kill-criterion signal:** if Raghav's override rate stays above 30% across runs, the rules do not match reality. Read it from
  `override_rate` in each run's `run_log.json`. For a quick look across runs:

  ```bash
  python -c "import json,glob;[print(f, json.load(open(f)).get('override_rate')) for f in sorted(glob.glob('outputs/*/run_log.json'))]"
  ```

## Optional AI summary layer

Off by default (`ai_summary.enabled: false`). When enabled, with `anthropic` installed (`pip install -e ".[ai]"`) and
`ANTHROPIC_API_KEY` set, it rewrites the run-summary text in `sourcing_handoff.md` from `planning_table.csv` and `review_log.csv`.
It cannot change a flag, quantity or approval: the PO tables are always built from the data, and any failure or missing key falls
back to the template summary. The prompt and model name are in `config.yaml`.

## Layout

```
config.yaml   data/raw/   outputs/<run_date>/
src/planner/  load clean organise rules forecast exceptions pipeline review po handoff outputs cli
app/review_app.py   tests/
```

Each stage takes DataFrames and the config and returns DataFrames plus a list of issues; there is no hidden state, and the same inputs and
config give the same outputs.
