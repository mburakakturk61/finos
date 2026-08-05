from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.engines.multi_period_trend import assemble_multi_period_trend_result

from test_multi_period_trend_pairwise_unit import resolved_series
from test_multi_period_trend_quality_unit import _profile


def test_final_result_and_quality_golden_vector_v1():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "multi_period_trend_quality_v1.json").read_text()
    )
    series = resolved_series(
        tuple(Decimal(item) for item in fixture["values"]),
        metric_code=fixture["metric_code"],
    )
    result = assemble_multi_period_trend_result(
        (series,), _profile(), expected_metric_codes=(series.metric_code,)
    )
    completeness = result.data_quality.result_completeness
    assert result.status.value == fixture["status"]
    assert result.canonical_digest == fixture["result_digest"]
    assert result.canonical_reference == fixture["result_reference"]
    assert result.data_quality.canonical_digest == fixture["quality_digest"]
    for field in (
        "expected_period_count",
        "available_observation_count",
        "calculated_transition_count",
        "calculated_cagr_count",
        "calculated_volatility_count",
        "calculated_break_count",
    ):
        assert getattr(completeness, field) == fixture[field]
