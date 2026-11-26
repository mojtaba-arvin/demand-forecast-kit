<!-- SPDX-FileCopyrightText: 2026 Mojtaba Arvin -->
<!-- SPDX-License-Identifier: MIT -->

# Retail dataset selection and evidence boundaries

**Assessment date:** 2026-11-26  
**Related issue:** [#75 — Expand retail lead-time calibration evidence](https://github.com/mojtaba-arvin/demand-forecast-kit/issues/75)

## Why this assessment exists

UCI Online Retail and Online Retail II are transaction extracts from the same
retailer. Online Retail II increases SKU/time coverage but is not independent
retailer replication. The M5/Walmart adapter and 28-day holdout runner are
implemented, but M5 contains sales history only; it does not provide observed
on-hand stock, purchase orders, receipts, or supplier lead times. Its current
baseline/high-service comparison therefore uses explicitly synthetic stock
and cost assumptions and must not be described as an empirical replenishment
backtest.

The next dataset should be selected by the evidence it can actually support,
not only by row count.

## Candidate sources

| Source | Published scope | What it can support | Known limits |
| --- | --- | --- | --- |
| [M5 Forecasting Accuracy](https://www.kaggle.com/competitions/m5-forecasting-accuracy) | 30,490 item/store series across 10 stores; daily sales history | Large independent retail demand benchmark; 7/14-day demand calibration and chronological demand holdout | No observed on-hand stock, receipts, purchase orders, or lead times in the competition sales files |
| [Retail Transactions and Stocks Data — Mendeley](https://doi.org/10.17632/27x8mjm8k4.1) | Official record describes daily transaction-level sales and SKU on-hand stock from 40 stores and 2,326 SKUs; CC BY 4.0. Listed CSV sizes are 37.3 MB sales and 95.4 MB inventory | Candidate for stock-aware descriptive validation and daily sales/inventory alignment | Official landing metadata does not establish stock interval semantics, purchase orders, supplier lead times, or lost-sales truth. A public [format-preserving dataset card](https://huggingface.co/datasets/LemeBase/retail-forecasting-hackathon) reports 125,751 sales rows, 284,755 inventory rows, and 2025-06-01–2026-04-24; verify these against the original files before use |
| [Retail Transactions and Stocks Data — Zenodo record](https://doi.org/10.5281/zenodo.19784493) | Original CSV and Parquet files inspected on 2026-11-26: 491,857 rows, 25 columns, 29 stores, 338 products, 842 dates; CC BY 4.0 | Candidate for daily stock-aware demand/availability diagnostics; unique daily store-product key and observed on-hand/cost/receipt-date fields | Retailer identity and collection methodology are not disclosed; no PO, supplier lead-time, in-transit, or lost-sales fields. Stock/return/status semantics need validation before forecasting or policy scoring |
| [VN2 Inventory Planning Challenge](https://doi.org/10.5281/zenodo.23265416) | 599 store/article pairs, weekly data for eight weeks; CC BY 4.0 | Complementary inventory-policy stress test: weekly sales/in-stock flags, starting and ending stock, missed units, and 1-/2-week in-transit quantities | Eight weekly periods are insufficient for robust seasonal forecasting or calibration claims; confirm challenge-specific semantics before scoring policies |

The Mendeley and Zenodo source summaries above are based on their source
records and a public [retail dataset catalogue](https://huggingface.co/datasets/LemeBase/retail-forecasting-hackathon).
The catalogue identifies Jimmy Smith as the source author for both similarly
titled releases and describes the Zenodo file as a direct Parquet copy, while
the Mendeley files are format-preserving conversions. Their relationship and
possible source overlap are not established. **Do not count them as two
independent retailers or independent data-generating processes** until original
metadata and row-level provenance establish that they are distinct. The
catalogue is not a substitute for validating the original source files.


## Verified Zenodo source inspection (2026-11-26)

The original files for [Zenodo record 19784493](https://zenodo.org/records/19784493)
were downloaded in a temporary GitHub Actions workspace. Both published MD5
checksums verified; only the JSON schema/provenance report was uploaded as an
artifact. The raw files were not committed.

| File | Size | Source MD5 | SHA-256 |
| --- | ---: | --- | --- |
| `sales_txn.csv` | 104,838,674 bytes | `2b9202fe0c7659be042db9f3abbbdfe9` | `5fc93422c7bb65a3abb59312028b21e587eeacd3b1a689e8de506cde49d74599` |
| `sales_txn.parquet` | 8,040,154 bytes | `dcf18a0112798694be9263c78cad6cdd` | `bed632b98325d8c5f9c16a489cc2d5841d1e3e31a6977401662133b778f9e22e` |

Both representations contain 491,857 rows and 25 columns. The Parquet file is
the preferred analysis input because it preserves null values in receipt/sale
date fields; the CSV encodes those missing values as empty strings.

Verified structure and data-quality observations:

- `TXN_DT` spans 2023-12-31 through 2026-04-20 (842 calendar days); there are
  29 distinct `STORE` values and 338 distinct `PRODUCT_NO` values.
- `(TXN_DT, STORE, PRODUCT_NO)` is unique across all 491,857 rows. The data
  includes 462,568 zero-`QTY_SOLD` rows (94.05%), 28,574 positive rows (5.81%),
  and 715 negative rows (0.15%). Do not silently interpret missing dates as
  zero demand; zero quantities are explicit observations.
- `QTY_ON_HAND` is zero on 18,129 rows (3.69%) and ranges from 0 to 10,885.
  `LATEST_OH_QTY` is negative on 8,261 rows (1.68%); do not use it as a
  reliable inventory position without resolving its meaning.
- `IS_AUDIT_ANOMALY` is true on 10,049 rows (2.04%) and `IS_PHASING_OUT` is
  true on 114,957 rows (23.37%).
- `LAST_RCPT_DT` is null on 81,067 rows (16.48%) and `LAST_SOLD_DT` is null
  on 5,314 rows (1.08%). Negative sales/COGS and return-coded rows require
  separate treatment.
- `IS_RETURN` has values -1/0/1 and `STOCK_STATUS` has values R/C. The source
  record does not define these codes. Do not coerce them to booleans or assign
  meanings without evidence.

The source description is generic and does not identify the retailer/operator
or collection methodology. This is a verified stock-aware retail dataset, but
it is **not yet evidence of independent-retailer replication**. It has no
purchase-order history, supplier lead-time, in-transit quantity, or observed
lost-sales field. `QTY_ON_HAND` timestamp semantics and the return/status
codes must be established before treating it as uncensored demand or scoring
inventory policies. It supports a next-stage stock-aware diagnostic, not an
empirical lead-time replenishment cost/service backtest.

The initial inspection run is recorded at
[GitHub Actions run 45750274825](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45750274825).
The reproducible inspector is being added in PR #89.

## Product decision

1. **Keep M5 as the large demand-only benchmark.** Its runner is useful for
   independent demand coverage and chronological demand-holdout diagnostics.
   Do not use its synthetic inventory/cost comparison as actual policy evidence.
2. **Inspect the Zenodo apparel release first for stock-aware daily evidence.**
   It has the longest published daily history among the stock-aware candidates
   and exposes inventory/cost/receipt-date fields. It may support observed
   stock-availability and inventory-state diagnostics after validation.
3. **Use VN2 only as a complementary inventory-policy stress test.** Its
   in-transit and missed-unit fields are valuable, but eight weeks cannot
   establish robust forecast calibration.
4. **Treat Mendeley and Zenodo as one unverified provenance family for now.**
   Both releases have the same title and are attributed to Jimmy Smith in the
   public catalogue. Their overlap/relationship must be established before
   either is counted as independent-retailer evidence. Mendeley’s store/SKU
   breadth is attractive, but inventory interval semantics must be resolved
   from the original files before joining stock to daily sales.
5. **Do not enable global calibration correction.** Independent demand
   coverage, per-series dispersion, interval width, bias, and uncertainty must
   improve on a predeclared chronological holdout. Inventory cost/service
   claims additionally require observed stock and defensible receipt/lead-time
   semantics.

## Mandatory source-validation gate

Before writing a new adapter or publishing any benchmark result, acquire the
authorized original files locally and record their SHA-256 hashes. Do not commit
raw source data or place credentials in the repository. Verify and document:

- Exact file schema, source version, licence, row counts, and date coverage.
- Row grain and stable join key (at minimum store, SKU, and date or interval).
- Whether missing sales rows mean zero demand, unobserved demand, or no
  assortment; never silently fill all missing pairs with zero.
- Return/cancellation treatment and whether sales units can be negative.
- Whether inventory is an end-of-day snapshot, a start/end interval, or an
  event; determine how it aligns with sales timestamps.
- Whether on-hand values are observed, carried forward, audited, or flagged as
  anomalous; do not treat inventory-derived fields as demand predictors.
- Whether lost sales, stockout hours, receipts, in-transit quantities, and
  supplier lead times are observed or merely inferred.
- Whether unit cost and price are transaction-level or catalogue-level values.

If the source lacks lost demand, purchase-order events, or supplier lead times,
report only the metrics supported by the available observations. Do not invent
these fields from stock snapshots or use synthetic assumptions in a result
labelled empirical.

## Evaluation protocol

- Freeze SKU/store cohort membership using training history only.
- Build demand targets from observed sales with explicit return and missingness
  semantics; separately flag periods where sales may be censored by stockouts.
- Estimate calibration only from strictly earlier residual paths.
- Reserve a final chronological holdout and do not tune on its outcomes.
- Report cohort and per-series coverage, interval width, bias, origin counts,
  and uncertainty; do not report macro coverage alone.
- Evaluate inventory service/cost only where the source provides enough
  observed inventory/receipt/lead-time evidence. Separate demand-only simulation
  from empirical replenishment evaluation in both filenames and report labels.

## Current state

- M5 local-file adapter and prequential 7/14-day calibration/28-day demand
  holdout runner are merged; no M5 real-data result is claimed.
- Zenodo original files have been inspected; Mendeley original files have not.
- Mendeley and Zenodo share a title and attributed author in the public catalogue;
  independence/overlap is unproven, so they count as one provenance family until resolved.
- Global calibration correction remains disabled.
- Issue #75 stays open until independent source validation and empirical
  chronological evidence meet the acceptance criteria.
