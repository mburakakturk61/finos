from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.engines.multi_period_trend import analyze_pairwise_series

from test_multi_period_trend_pairwise_unit import resolved_series


FIXTURE = Path(__file__).parent / "fixtures" / "multi_period_trend_pairwise_v1.json"


def test_versioned_pairwise_golden_vectors():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["fixture_version"] == "multi-period-trend-pairwise/1.0.0"
    assert len(payload["cases"]) == 10
    for case in payload["cases"]:
        values = tuple(Decimal(value) for value in case["values"])
        segments = tuple(case.get("segments", [0] * len(values)))
        years = tuple(case.get("years", [2020 + index for index in range(len(values))]))
        result = analyze_pairwise_series(resolved_series(values, segments=segments, years=years))
        assert [item.transition_kind.value for item in result.series.transitions] == case["kinds"], case["name"]
        assert [item.direction.value for item in result.series.transitions] == case["pair_directions"], case["name"]
        if "negative_directions" in case:
            assert [item.negative_base_direction.value for item in result.series.transitions] == case["negative_directions"], case["name"]
        assert result.direction.value == case["aggregate_direction"], case["name"]
