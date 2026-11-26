# Zenodo retail transactions and stocks source

## Provenance

- Record: [Retail Transactions and Stocks Data](https://zenodo.org/records/19784493)
- DOI: [10.5281/zenodo.19784493](https://doi.org/10.5281/zenodo.19784493)
- License declared by the record: CC BY 4.0
- Publication date in metadata: 2024-03-28
- Record created/updated: 2026-04-26 / 2026-04-29
- Source files: `sales_txn.csv` and `sales_txn.parquet`
- No raw source file is committed. The inspection workflow downloads to a temporary directory, verifies the published MD5 checksums, computes SHA-256, and uploads only a JSON report.

The metadata description is generic and does not identify the retailer/operator or collection methodology. The distinct source record is not enough to assert independent-retailer replication.

## Verified source structure

Workflow: [Zenodo source inspection](https://github.com/mojtaba-arvin/demand-forecast-kit/actions/runs/45750924449), artifact `zenodo-retail-source-inspection` (ID `15085796247`).

| Field | Verified value |
| --- | --- |
| Rows / columns | 491,857 / 25 in each representation |
| Transaction dates | 2023-12-31 through 2026-04-20 |
| Distinct stores / products | 29 / 338 |
| Observed store-product series | 851 |
| Observed transaction dates | 842 |
| Candidate daily key | `TXN_DT + STORE + PRODUCT_NO`, zero duplicates |
| CSV size | 104,838,674 bytes |
| Parquet size | 8,040,154 bytes |
| CSV SHA-256 | `5fc93422c7bb65a3abb59312028b21e587eeacd3b1a689e8de506cde49d74599` |
| Parquet SHA-256 | `bed632b98325d8c5f9c16a489cc2d5841d1e3e31a6977401662133b778f9e22e` |

The schema contains transaction date, store/product identifiers and categories, `QTY_SOLD`, `QTY_ON_HAND`, `LATEST_OH_QTY`, cost/price/discount fields, `LAST_RCPT_DT`, `LAST_SOLD_DT`, days-since fields, `IS_RETURN`, `IS_AUDIT_ANOMALY`, `IS_PHASING_OUT`, `STOCK_STATUS`, and `SALES_TYPE`.

## Data-quality findings

- `QTY_SOLD` is zero in 462,568 rows (94.05%), positive in 28,574 (5.81%), and negative in 715 (0.15%).
- `IS_RETURN` is encoded as -1 / 0 / 1 (462,376 / 28,493 / 988 rows); it must not be coerced to a boolean without source documentation.
- `IS_AUDIT_ANOMALY` is true in 10,049 rows (2.04%); `IS_PHASING_OUT` is true in 114,957 rows (23.37%).
- `LAST_RCPT_DT` is null in 81,067 Parquet rows (16.48%); `LAST_SOLD_DT` is null in 5,314 rows (1.08%). The CSV stores these missing values as empty strings, so Parquet is preferred for analysis.
- `QTY_ON_HAND` is never negative in the inspected source and is zero in 18,129 rows (3.69%).
- `LATEST_OH_QTY` is negative in 8,261 rows (1.68%); do not use it as an inventory position until its semantics are explained.
- `COGS` is negative in 715 rows; `SALES_AMT` is negative in 736 rows. Returns/adjustments require an explicit demand-accounting policy.
- `STOCK_STATUS` values are R/C; their meanings are not documented in the record metadata.

## Interpretation boundary

This is a stock-aware candidate for daily demand and availability diagnostics. It is not yet an empirical replenishment-policy benchmark:

1. The source does not document whether `QTY_ON_HAND` is a start-of-day, end-of-day, transaction-time, or other stock snapshot.
2. The source does not explain `LATEST_OH_QTY`, `STOCK_STATUS`, `IS_RETURN`, or audit-anomaly semantics.
3. Last receipt dates and elapsed days do not provide receipt quantities, purchase orders, supplier lead times, or complete inbound event history.
4. The retailer/operator and collection methodology are not identified, so do not claim independent-retailer replication.
5. Stockout censoring and lost sales cannot be inferred until stock timestamps and sales semantics are validated.

## Next validation gate

Before adding a forecasting/replenishment adapter:

- Reconcile Parquet and CSV after normalizing empty strings to null.
- Verify the daily stock snapshot timing and whether it is consistent across store-product rows.
- Quantify sales/return signs and transaction types; define gross-demand and net-accounting views separately.
- Check whether `DAYS_SINCE_RECEIPT` and `DAYS_SINCE_SALE` agree with their date fields.
- Exclude or separately report audit anomalies and phasing-out products.
- Do not synthesize missing purchase orders, receipt quantities, or lead times and then call the result empirical.

Global lead-time calibration correction remains disabled.
