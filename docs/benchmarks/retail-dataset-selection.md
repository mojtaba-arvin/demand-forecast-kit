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
| [Retail Transactions and Stocks Data — Zenodo apparel record](https://doi.org/10.5281/zenodo.19784493) | Public dataset metadata reports 29 stores, 338 SKUs, 491,857 daily rows, 2023-12-31–2026-04-20; CC BY 4.0 | Strong candidate for daily stock-aware diagnostics: the published schema includes units, on-hand, unit cost/price, returns, last receipt date, and data-quality flags | Receipt dates are not a supplier lead-time distribution or purchase-order history. The published metadata is a discovery aid; inspect the original release and verify the exact schema and grain |
| [VN2 Inventory Planning Challenge](https://doi.org/10.5281/zenodo.23265416) | 599 store/article pairs, weekly data for eight weeks; CC BY 4.0 | Complementary inventory-policy stress test: weekly sales/in-stock flags, starting and ending stock, missed units, and 1-/2-week in-transit quantities | Eight weekly periods are insufficient for robust seasonal forecasting or calibration claims; confirm challenge-specific semantics before scoring policies |

The Mendeley and Zenodo source summaries above are based on their source
records and a public [retail dataset catalogue](https://huggingface.co/datasets/LemeBase/hackathon-retail-sets).
The catalogue states that its Parquet files are format conversions of the
source data, not new observations. It is not a substitute for validating the
original source files.

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
4. **Keep Mendeley footwear as a secondary candidate.** Its store/SKU breadth is
   attractive, but inventory interval semantics must be resolved from the
   original files before joining stock to daily sales.
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
- Mendeley and Zenodo source files have not yet been validated locally.
- Global calibration correction remains disabled.
- Issue #75 stays open until independent source validation and empirical
  chronological evidence meet the acceptance criteria.
