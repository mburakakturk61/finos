from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from itertools import permutations
from uuid import UUID

import pytest

from app.engines.multi_period_trend import (
    TREND_ACCOUNTING_POLICY_V1,
    TREND_CADENCE_POLICIES_V1,
    TREND_NUMERIC_POLICY_V1,
    TREND_PERCENTAGE_SIGN_POLICY_V1,
    TREND_THRESHOLD_POLICY_V1,
    TrendCagrEligibility,
    TrendCanonicalError,
    TrendComputationStatus,
    TrendCoverageKind,
    TrendEvidenceLevel,
    TrendMeasurementBasis,
    TrendNegativeBaseDirection,
    TrendObservation,
    TrendOneOffStatus,
    TrendPercentageBaseCase,
    TrendPercentageDecision,
    TrendPeriodFamily,
    TrendPolicyError,
    TrendRestatementProfile,
    TrendSourceEngineType,
    canonical_trend_bytes,
    canonical_trend_digest,
    canonical_trend_reference,
    normalize_decimal,
    validate_sha256,
    validate_trend_reference,
)


COMPANY = UUID("11111111-1111-4111-8111-111111111111")


def _observation(amount: Decimal = Decimal("100.00"), evidence: TrendEvidenceLevel = TrendEvidenceLevel.EXACT) -> TrendObservation:
    return TrendObservation(
        ordinal=0,
        segment_ordinal=0,
        company_id=COMPANY,
        period_id=UUID("00000000-0000-4000-8000-000000000001"),
        period_start_date=date(2024, 1, 1),
        period_end_date=date(2024, 12, 31),
        period_family=TrendPeriodFamily.ANNUAL,
        coverage_kind=TrendCoverageKind.CUMULATIVE,
        measurement_basis=TrendMeasurementBasis.STOCK_AS_OF,
        value=amount,
        currency="TRY",
        monetary_unit_multiplier=Decimal("1"),
        scale=2,
        evidence=evidence,
        source_result_id=UUID("10000000-0000-4000-8000-000000000001"),
        source_engine_type=TrendSourceEngineType.BALANCE_SHEET,
        source_schema_version=None,
        source_model_version="1.0.0",
        canonical_source_digest="a" * 64,
        restatement_profile=TrendRestatementProfile.ORIGINAL,
        restatement_revision=0,
        one_off_status=TrendOneOffStatus.UNKNOWN,
    )


def test_minimum_observation_thresholds_and_cadence_matrix_are_exact() -> None:
    assert (
        TREND_THRESHOLD_POLICY_V1.pairwise_minimum_observations,
        TREND_THRESHOLD_POLICY_V1.direction_minimum_observations,
        TREND_THRESHOLD_POLICY_V1.volatility_minimum_observations,
        TREND_THRESHOLD_POLICY_V1.break_minimum_observations,
        TREND_THRESHOLD_POLICY_V1.cagr_minimum_endpoints,
    ) == (2, 3, 4, 5, 2)
    assert tuple(policy.period_family for policy in TREND_CADENCE_POLICIES_V1) == tuple(TrendPeriodFamily)
    assert TREND_ACCOUNTING_POLICY_V1.maximum_observations == 60


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("2.345"), Decimal("2.34")),
        (Decimal("2.355"), Decimal("2.36")),
        (Decimal("-2.345"), Decimal("-2.34")),
        (Decimal("-0.004"), Decimal("0")),
    ],
)
def test_half_even_rounding_and_negative_zero(value: Decimal, expected: Decimal) -> None:
    result = TREND_NUMERIC_POLICY_V1.quantize(value, 2)
    assert result == expected
    if result == 0:
        assert not result.is_signed()


def test_normalize_decimal_rejects_float_and_nonfinite() -> None:
    assert normalize_decimal(Decimal("-0")) == Decimal(0)
    with pytest.raises(TrendCanonicalError):
        normalize_decimal(1.0)  # type: ignore[arg-type]
    with pytest.raises(TrendCanonicalError):
        normalize_decimal(Decimal("NaN"))


@pytest.mark.parametrize(
    ("prior", "current", "basis", "base_case", "decision", "negative_direction"),
    [
        (Decimal("10"), Decimal("12"), TrendMeasurementBasis.STOCK_AS_OF, TrendPercentageBaseCase.POSITIVE_TO_POSITIVE, TrendPercentageDecision.CALCULATE, TrendNegativeBaseDirection.NOT_APPLICABLE),
        (Decimal("0"), Decimal("12"), TrendMeasurementBasis.STOCK_AS_OF, TrendPercentageBaseCase.ZERO_BASE, TrendPercentageDecision.UNAVAILABLE_ZERO_BASE, TrendNegativeBaseDirection.NOT_APPLICABLE),
        (Decimal("-10"), Decimal("-8"), TrendMeasurementBasis.STOCK_AS_OF, TrendPercentageBaseCase.NEGATIVE_TO_NEGATIVE, TrendPercentageDecision.SEMANTIC_ONLY_NEGATIVE_BASE, TrendNegativeBaseDirection.IMPROVING),
        (Decimal("-10"), Decimal("-12"), TrendMeasurementBasis.STOCK_AS_OF, TrendPercentageBaseCase.NEGATIVE_TO_NEGATIVE, TrendPercentageDecision.SEMANTIC_ONLY_NEGATIVE_BASE, TrendNegativeBaseDirection.WORSENING),
        (Decimal("-10"), Decimal("-10"), TrendMeasurementBasis.STOCK_AS_OF, TrendPercentageBaseCase.NEGATIVE_TO_NEGATIVE, TrendPercentageDecision.SEMANTIC_ONLY_NEGATIVE_BASE, TrendNegativeBaseDirection.UNCHANGED),
        (Decimal("-10"), Decimal("2"), TrendMeasurementBasis.STOCK_AS_OF, TrendPercentageBaseCase.SIGN_CHANGE, TrendPercentageDecision.UNAVAILABLE_SIGN_CHANGE, TrendNegativeBaseDirection.NOT_APPLICABLE),
        (None, Decimal("2"), TrendMeasurementBasis.STOCK_AS_OF, TrendPercentageBaseCase.MISSING_INPUT, TrendPercentageDecision.UNAVAILABLE_MISSING_INPUT, TrendNegativeBaseDirection.NOT_APPLICABLE),
        (Decimal("1"), Decimal("2"), TrendMeasurementBasis.RATIO_RATE, TrendPercentageBaseCase.RATIO_RATE_SERIES, TrendPercentageDecision.ABSOLUTE_DELTA_ONLY_RATIO_RATE, TrendNegativeBaseDirection.NOT_APPLICABLE),
    ],
)
def test_percentage_sign_decision_contract(
    prior: Decimal | None,
    current: Decimal | None,
    basis: TrendMeasurementBasis,
    base_case: TrendPercentageBaseCase,
    decision: TrendPercentageDecision,
    negative_direction: TrendNegativeBaseDirection,
) -> None:
    result = TREND_PERCENTAGE_SIGN_POLICY_V1.decide(prior=prior, current=current, measurement_basis=basis)
    assert (result.base_case, result.decision, result.negative_base_direction) == (base_case, decision, negative_direction)


@pytest.mark.parametrize(
    ("family", "basis", "gap_free", "count", "first", "last", "expected"),
    [
        (TrendPeriodFamily.ANNUAL, TrendMeasurementBasis.STOCK_AS_OF, True, 2, Decimal("10"), Decimal("20"), TrendCagrEligibility.ELIGIBLE),
        (TrendPeriodFamily.ANNUAL, TrendMeasurementBasis.RATIO_RATE, True, 2, Decimal("1"), Decimal("2"), TrendCagrEligibility.DISABLED_FOR_MEASUREMENT_BASIS),
        (TrendPeriodFamily.MONTHLY_DISCRETE, TrendMeasurementBasis.DISCRETE_FLOW, True, 2, Decimal("1"), Decimal("2"), TrendCagrEligibility.NON_ANNUAL_SERIES),
        (TrendPeriodFamily.ANNUAL, TrendMeasurementBasis.STOCK_AS_OF, False, 2, Decimal("1"), Decimal("2"), TrendCagrEligibility.GAP_PRESENT),
        (TrendPeriodFamily.ANNUAL, TrendMeasurementBasis.STOCK_AS_OF, True, 1, Decimal("1"), Decimal("2"), TrendCagrEligibility.INSUFFICIENT_ENDPOINTS),
        (TrendPeriodFamily.ANNUAL, TrendMeasurementBasis.STOCK_AS_OF, True, 2, None, Decimal("2"), TrendCagrEligibility.MISSING_ENDPOINT),
        (TrendPeriodFamily.ANNUAL, TrendMeasurementBasis.STOCK_AS_OF, True, 2, Decimal("0"), Decimal("2"), TrendCagrEligibility.NON_POSITIVE_ENDPOINT),
    ],
)
def test_cagr_eligibility_contract(
    family: TrendPeriodFamily,
    basis: TrendMeasurementBasis,
    gap_free: bool,
    count: int,
    first: Decimal | None,
    last: Decimal | None,
    expected: TrendCagrEligibility,
) -> None:
    assert TREND_PERCENTAGE_SIGN_POLICY_V1.cagr_eligibility(
        period_family=family,
        measurement_basis=basis,
        gap_free=gap_free,
        endpoint_count=count,
        first_value=first,
        last_value=last,
    ) is expected


def test_canonical_golden_vector_and_semantic_decimal_normalization() -> None:
    value = (UUID("00000000-0000-4000-8000-000000000001"), date(2024, 1, 2), Decimal("1.00"), None)
    expected = b'{"$tuple":[{"$uuid":"00000000-0000-4000-8000-000000000001"},{"$date":"2024-01-02"},{"$decimal":"1"},{"$none":true}]}'
    assert canonical_trend_bytes(value) == expected
    assert canonical_trend_bytes((value[0], value[1], Decimal("1"), None)) == expected


def test_canonical_digest_changes_for_amount_evidence_status_and_version() -> None:
    original = _observation()
    digest = canonical_trend_digest(original)
    variants = (
        replace(original, value=Decimal("100.01")),
        replace(original, evidence=TrendEvidenceLevel.DERIVED),
        replace(original, source_model_version="1.0.1"),
    )
    assert all(canonical_trend_digest(item) != digest for item in variants)
    assert canonical_trend_digest((TrendComputationStatus.COMPLETE,)) != canonical_trend_digest((TrendComputationStatus.PARTIAL,))


def test_canonical_reference_and_digest_validation() -> None:
    reference = canonical_trend_reference(_observation())
    assert validate_trend_reference(reference) == reference
    assert validate_sha256(reference.rsplit(":", 1)[1]) == reference.rsplit(":", 1)[1]
    for malformed in ("", "trend:v2:sha256:" + "a" * 64, "trend:v1:sha256:" + "A" * 64, "a" * 63):
        with pytest.raises(TrendCanonicalError):
            validate_trend_reference(malformed)


@pytest.mark.parametrize("value", [1.0, [1], {"x": 1}, datetime(2024, 1, 1)])
def test_canonical_serializer_rejects_float_mutable_and_naive_datetime(value: object) -> None:
    with pytest.raises(TrendCanonicalError):
        canonical_trend_bytes(value)


def test_canonical_datetime_is_utc_microsecond_exact() -> None:
    value = datetime(2024, 1, 1, 12, 30, 1, 123456, tzinfo=timezone.utc)
    assert b"2024-01-01T12:30:01.123456+00:00" in canonical_trend_bytes(value)


def test_canonical_tuple_order_is_significant_but_contract_sorting_is_not() -> None:
    values = (_observation(), replace(_observation(), ordinal=1, period_id=UUID("00000000-0000-4000-8000-000000000002")))
    assert canonical_trend_digest(values) != canonical_trend_digest(tuple(reversed(values)))
    assert len({canonical_trend_digest(tuple(order)) for order in permutations(values)}) == 2


def test_policy_values_are_safe_and_reject_mutation() -> None:
    assert repr(TREND_ACCOUNTING_POLICY_V1) == "TrendAccountingPolicy()"
    with pytest.raises(Exception):
        TREND_ACCOUNTING_POLICY_V1.maximum_observations = 61  # type: ignore[misc]
    with pytest.raises(TrendPolicyError):
        replace(TREND_THRESHOLD_POLICY_V1, direction_minimum_observations=2)
