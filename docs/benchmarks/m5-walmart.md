# M5 / Walmart retail dataset adapter

## Provenance and data rights

- Dataset: M5 Forecasting - Accuracy (Walmart)
- Official source: https://www.kaggle.com/competitions/m5-forecasting-accuracy/data
- Data: daily unit sales for 3,049 products across 10 stores (30,490 item/store
  series), with a daily calendar and weekly sell prices.
- Historical file: sales_train_evaluation.csv, daily columns d_1 through d_1941.
- License: subject to Kaggle competition rules; this is not a blanket
  redistribution license.

Do not commit raw M5 files, derived row-level sales, or credentials. The
adapter reads an authorized local copy only. CI uses a tiny synthetic fixture
and never downloads competition data. Record the official source file hashes
in benchmark output.

## Preprocessing contract

The local adapter in demand_forecast_kit.retail_benchmark reads
sales_train_evaluation.csv and calendar.csv. It requires a contiguous d_1..d_N
column range, a one-to-one calendar mapping, consecutive dates, unique
item/store identities, and finite non-negative daily sales for selected series.

Cohorts are frozen using only the first 180 calendar days:

- Dense: at least 50% active days.
- Intermittent: 5% to less than 50% active days.
- Very intermittent: less than 5% active days, with at least 8 active days.

The adapter selects up to 20 series per cohort using a deterministic SHA-256
ranking, converts the selected wide rows to positive daily-demand rows, and
returns SHA-256 hashes for both input files. Zero-sales dates are omitted from
this sparse input; build_cohort_panel reconstructs the complete calendar and
fills those dates with explicit zero demand. The series key is
item_id::store_id; item identity is not collapsed across stores.

## Holdout and interpretation boundary

The M5 evaluation file contains a final 28-day labeled validation tail. The
planned inventory-policy evaluation must reserve those final 28 days as an
untouched chronological holdout. Cohort assignment, model selection, residual
calibration, and any policy choice must use only observations strictly before
that tail. The 7- and 14-day lead-time calibration report and inventory policy
outcomes must be reported separately.

The public data contains sales, calendar, and weekly prices, but does not
provide observed inventory positions, supplier lead times, or replenishment
receipts. Any inventory position, lead-time, underage, or overage cost used in
a policy experiment is an explicit scenario assumption, not a measured Walmart
operational fact.

## Current status

The deterministic local-file adapter and synthetic tests are implemented.
No M5 real-data benchmark result is claimed until an authorized copy of the
official files is available and the untouched 28-day policy holdout has been
run. Keep global lead-time calibration correction disabled in the meantime.
