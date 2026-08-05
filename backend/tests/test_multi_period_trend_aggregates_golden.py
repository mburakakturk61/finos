from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.engines.multi_period_trend import TrendEvidenceLevel, analyze_trend_aggregates

from test_multi_period_trend_pairwise_unit import resolved_series


FIXTURE = Path(__file__).parent / "fixtures" / "multi_period_trend_aggregates_v1.json"


def test_versioned_aggregate_golden_vectors():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["fixture_version"] == "multi-period-trend-aggregates/1.0.0"
    assert len(payload["cases"]) == 9
    for case in payload["cases"]:
        values = tuple(Decimal(value) for value in case["values"])
        segments = tuple(case.get("segments", [0] * len(values)))
        years = tuple(case.get("years", [2020 + index for index in range(len(values))]))
        evidence = tuple(TrendEvidenceLevel(item) for item in case.get("evidence", ["exact"] * len(values)))
        result = analyze_trend_aggregates(resolved_series(
            values, segments=segments, years=years, evidence=evidence
        ))
        if "cagr_status" in case:
            assert result.cagr_result.status.value == case["cagr_status"], case["name"]
        if "stability" in case:
            assert result.stability_result.stable is case["stability"], case["name"]
        if "volatility_category" in case:
            assert result.volatility_result.category.value == case["volatility_category"], case["name"]
        if "break_detected" in case:
            assert result.break_result.detected is case["break_detected"], case["name"]
        if "aggregate_evidence" in case:
            assert result.volatility_result.evidence.value == case["aggregate_evidence"], case["name"]
