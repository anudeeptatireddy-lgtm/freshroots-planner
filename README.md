# Freshroots demand planner

Automates the data work behind Raghav Kulkarni's demand planning and applies his documented rules exactly,
so the forecast can run twice a week instead of once a month. It runs: load, validate and clean, organise,
apply rules, forecast, work out order quantities, human review, purchase orders, sourcing handoff.

It does **not** use machine learning or statistics, and it does **not** make judgment calls. Anything outside
the rules goes to a person as an exception.

## Setup

Python 3.11+.

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev,app]"
# or: python -m venv .venv && .venv/bin/pip install -e ".[dev,app]"
```

## Run

```bash
python -m planner run --data data/raw --run-date 2026-10-19      # stages 1-6, writes outputs/2026-10-19/
streamlit run app/review_app.py                                   # review exceptions, then generate POs
python -m planner run --data data/raw --auto-approve-rules-only   # scheduled/test path: no human, exceptions left out
python -m planner generate-pos --run-dir outputs/2026-10-19       # POs from review_log.csv (the app does this too)
DATABASE_URL=... python -m planner db-seed --data data/raw        # load master data, sales, stock, calendar into Postgres
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

## Database (Neon Postgres)

Runs, decisions and PO files can be stored in Postgres so nothing is lost when a hosted disk is wiped.
It is optional: with no database configured the app works on local files exactly as before.

- **Where:** Neon project `freshroots-planner` (default branch holds real data; branch `tests` is for the test-suite).
- **Turn it on:** set `DATABASE_URL` as an environment variable, or in `.streamlit/secrets.toml` locally
  (gitignored), or in the app's **Secrets** panel on Streamlit Cloud: `DATABASE_URL = "postgresql://..."`.
  Copy the string from the Neon console (Connect). Never commit it.
- **Tables** (created automatically): `runs`, `run_files` (every output file, including PO PDFs), `planning_lines`,
  `data_issues`, `decisions` (append-only; last row per SKU stands), `purchase_order_lines`.
- **How it works:** the pipeline still writes a run folder; `planner.store.Store.save_run` mirrors it into Postgres and
  `materialize` rebuilds folders from Postgres at the start of each page load. Each Approve / Reject tap saves the decision
  immediately. The scheduled CLI run saves to the database too when `DATABASE_URL` is set.
- **Tests:** `tests/test_store.py` runs against the `tests` branch via `TEST_DATABASE_URL` (in `.env.local`, gitignored)
  and is skipped when it is not set. The rest of the suite never touches the database (`FRESHROOTS_DISABLE_DB`).

## Phone / hosted use

The review app is Streamlit. It is deployed on Streamlit Community Cloud (share.streamlit.io; repo `freshroots-planner`,
branch `main`, main file `app/review_app.py`). Vercel cannot run Streamlit.

- **Dependencies:** `requirements.txt` lists libraries only. The app imports the planner from `src/` in the repo, never from an
  installed copy: Cloud caches installs when `requirements.txt` is unchanged, and an old cached copy once crashed the app.
- **Database:** add `DATABASE_URL` in the app's **Secrets** panel so runs and decisions survive restarts (see "Database").
  Without it the app works on local files, and hosted disks are wiped on restart: use "Review log (CSV)" after each review.
- **Running planning:** the "Run planning" button works on the bundled `data/raw` files or on CSVs you upload.
- **Design:** the UI follows the Claude Design handoff in `docs/HANDOFF.md` (card option B).

## Zoho Inventory

- **Today:** the app creates the POs and a Zoho import CSV (`purchase_orders_zoho_import.csv`); procurement imports it by hand.
- **Send to Zoho (Orders tab):** "Preview Zoho drafts (dry run)" shows exactly which draft POs would be created. Nothing is sent
  (`zoho.dry_run_only: true` in `config.yaml`). Suppliers are matched in Zoho by name and products by SKU; anything unmatched is
  reported and its PO skipped, never guessed.
- **Going live:** set `zoho.dry_run_only: false` and add `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN` (and `ZOHO_DC`,
  optionally `ZOHO_ORG_ID`) as secrets. The live path has only been tested against a fake Zoho (no organisation was available), so check
  the first real draft by hand.
- **Status (2026-10-24):** the Zoho client ID/secret are valid (Zoho answers `invalid_code` to a wrong code, not `invalid_client`) and the
  India data centre is right, but Zoho refuses to create an organisation for this account (HTTP 400 on `POST /api/v1/organizations`,
  three tries). Until an organisation exists there is no refresh token and nothing real to send to; the dry run is the only live-tested part.
- **Refresh token:** generate a one-time code in the Zoho API Console (Self Client, Generate Code; scopes
  `ZohoInventory.settings.READ,ZohoInventory.contacts.READ,ZohoInventory.items.READ,ZohoInventory.purchaseorders.CREATE,ZohoInventory.purchaseorders.READ`,
  10 minutes), then run `python -m planner zoho-token --code <code>`. It saves `ZOHO_REFRESH_TOKEN` into `.streamlit/secrets.toml` without
  printing it; add the same line to the Streamlit Cloud Secrets panel.
- **Zoho test org (2026-10-24):** organisation "Freshroots" (id 60093129602, zoho.in) exists under a second Zoho account. The 4 vendors and
  15 items were imported through Zoho's Import screens (vendors 4/4, items 15/15). Zoho rejects opening stock without a positive per-unit cost, so
  items have no stock (counts are in `data/zoho_seed/opening_stock.csv`) and a Selling Price of 0 (a placeholder; Zoho requires the column).
  The client ID/secret in the secrets file belong to the FIRST Zoho account; a new Self Client is needed in the account that owns this organisation.
- **Live test passed (2026-10-24):** with a refresh token for the new Self Client, the live path looked up all 3 suppliers and 5 products in Zoho by name/SKU
  and created one real draft: Zoho PO-00001, reference FR-PO-20261019-03, Meridian Trade Co., 500 units, status DRAFT, amount 0 (no prices in the data).
  Only that one PO was sent.
- **Send button (unlocked 2026-10-24):** `zoho.dry_run_only` is `false`. The button still needs all of: Zoho secrets saved (client ID/secret, refresh token, `ZOHO_DC`,
  `ZOHO_ORG_ID`), the confirmation box ticked, and POs not already sent (`zoho_sent.json` in the run folder). It creates DRAFTS only; a person releases them in Zoho.
  Set `dry_run_only: true` to return to preview-only.
- **Hosted end-to-end test passed (2026-10-24):** on the Streamlit Cloud app, 4 exceptions approved (reviewer "Claude test"), 3 POs generated, and Send to Zoho created
  drafts PO-00002, -00003, -00004 (visible in Zoho). A reload shows them as already sent. PO-00001 is the earlier manual test (a duplicate of the Meridian PO).
- **Seed files:** `python -m planner zoho-files` writes `data/zoho_seed/vendors.csv` and `items.csv` for Zoho's Import screens.

## Keeping the hosted app awake and protected

- Streamlit Community Cloud puts an app to sleep after about 12 hours with no visitor. `.github/workflows/keep-awake.yml` visits the app every 6 hours
  with a real headless browser (`scripts/keepalive.py`) and clicks "get this app back up" if it ever finds it asleep. Run it by hand from the GitHub Actions tab.
- **The app must be protected, because it can send POs to Zoho.** Add an `APP_PASSWORD` secret in Streamlit Secrets. While it is set, visitors see only a
  password page (5 wrong tries locks the page until reload). The keep-alive visit passes only when it sees that password page. If the app is public with no
  password, or private behind Streamlit's own sign-in (a robot cannot visit), the job FAILS and GitHub emails the repo owner.
- Limits: GitHub pauses scheduled workflows in a repo with no activity for 60 days (push anything, or re-enable it in the Actions tab).

## Open items for the team

- Check the Zoho import column names (`po.zoho_columns`) against Zoho Inventory's real import screen.
- Procurement to confirm who actually receives each PO (today: `sku_master.Distributor_ID`; see `po.vendor_overrides`).
- Raghav to confirm the distributor-anomaly threshold (50% is a placeholder) once distributor-level sales exist.
- Prices and open POs are not in the data: PO value is blank until `sku_prices.csv` / `open_purchase_orders.csv` are supplied.

## Layout

```
config.yaml   data/raw/   outputs/<run_date>/   docs/HANDOFF.md   .streamlit/config.toml (theme)
src/planner/  load clean organise rules forecast exceptions pipeline review po handoff outputs store zoho zoho_files cli
app/          review_app.py (page flow)  cards.py (per-line cards)  rows.py (Rows view)  orders_ui.py (Orders + Send to Zoho)
              skus_ui.py (All SKUs)  fr_html.py (HTML pieces + tooltips)  style.css
tests/        pipeline, exceptions, CLI/PO, review app (AppTest), cards, store (Neon test branch)
```

Each stage takes DataFrames and the config and returns DataFrames plus a list of issues; there is no hidden state, and the same inputs and
config give the same outputs.
