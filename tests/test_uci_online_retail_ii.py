# SPDX-FileCopyrightText: 2026 Mojtaba Arvin
# SPDX-License-Identifier: MIT
"""Tests for UCI Online Retail II lead-time calibration summaries."""

from evals.run_uci_online_retail_ii_benchmark import _summarize_lead_time_calibration


def test_lead_time_summary_reports_macro_coverage_and_sku_dispersion() -> None:
    results = [
        {
            "cohort": "dense",
            "series_id": "SKU-A",
            "model_id": "croston-sba",
            "lead_time": 7,
            "origin_count": 60,
            "quantile_coverage": {"0.1": 0.2, "0.5": 0.5, "0.9": 0.9},
            "interval_coverage": {"0.8": 0.6},
        },
        {
            "cohort": "dense",
            "series_id": "SKU-B",
            "model_id": "croston-sba",
            "lead_time": 7,
            "origin_count": 50,
            "quantile_coverage": {"0.1": 0.1, "0.5": 0.6, "0.9": 0.95},
            "interval_coverage": {"0.8": 0.9},
        },
        {
            "cohort": "intermittent",
            "series_id": "SKU-C",
            "model_id": "croston-sba",
            "lead_time": 14,
            "origin_count": 40,
            "quantile_coverage": {"0.1": 0.15, "0.5": 0.55, "0.9": 0.9},
            "interval_coverage": {"0.8": 0.8},
        },
    ]

    summaries = _summarize_lead_time_calibration(results)

    assert summaries == [
        {
            "cohort": "dense",
            "model_id": "croston-sba",
            "lead_time": 7,
            "series_count": 2,
            "mean_origin_count": 55.0,
            "macro_quantile_coverage": {
                "0.1": 0.15000000000000002,
                "0.5": 0.55,
                "0.9": 0.925,
            },
            "macro_p80_interval_coverage": 0.75,
            "min_series_p80_coverage": 0.6,
            "max_series_p80_coverage": 0.9,
            "series_below_nominal_p80": 1,
        },
        {
            "cohort": "intermittent",
            "model_id": "croston-sba",
            "lead_time": 14,
            "series_count": 1,
            "mean_origin_count": 40.0,
            "macro_quantile_coverage": {
                "0.1": 0.15,
                "0.5": 0.55,
                "0.9": 0.9,
            },
            "macro_p80_interval_coverage": 0.8,
            "min_series_p80_coverage": 0.8,
            "max_series_p80_coverage": 0.8,
            "series_below_nominal_p80": 0,
        },
    ]


def test_lead_time_summary_accepts_no_evaluated_series() -> None:
    assert _summarize_lead_time_calibration([]) == []
