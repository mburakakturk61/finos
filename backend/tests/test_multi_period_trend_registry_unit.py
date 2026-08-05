from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from app.engines.multi_period_trend import (
    TREND_METRIC_DEFINITIONS_V1,
    TREND_METRIC_REGISTRY_V1,
    TREND_METRIC_REGISTRY_VERSION,
    TrendMeasurementBasis,
    TrendMetricRegistry,
    TrendMetricRegistryError,
    TrendMetricTombstone,
    TrendMetricUnit,
    TrendPeriodFamily,
    TrendSourceCompatibilityStatus,
    TrendSourceEngineType,
    TrendSourceVersion,
    UnknownTrendMetricCode,
    registry_with_version,
)


EXPECTED_CODES = (
    "bs.current_assets", "bs.non_current_assets", "bs.total_assets",
    "bs.short_term_liabilities", "bs.long_term_liabilities", "bs.equity",
    "bs.total_liabilities_and_equity", "bs.cash_and_equivalents", "bs.inventory",
    "bs.trade_receivables", "bs.trade_payables",
    "is.net_sales", "is.cost_of_sales", "is.gross_profit", "is.operating_expenses",
    "is.operating_profit", "is.depreciation_and_amortization", "is.ebit", "is.ebitda",
    "is.financing_expenses", "is.profit_before_tax", "is.net_profit",
    "cf.opening_cash_and_cash_equivalents", "cf.closing_cash_and_cash_equivalents",
    "cf.operating_cash_flow", "cf.investing_cash_flow", "cf.financing_cash_flow",
    "cf.calculated_net_cash_change", "cf.free_cash_flow",
    "ratio.current_ratio", "ratio.quick_ratio", "ratio.cash_ratio", "ratio.debt_ratio",
    "ratio.debt_to_equity", "ratio.gross_profit_margin",
    "ratio.operating_profit_margin", "ratio.net_profit_margin", "ratio.return_on_assets",
    "ratio.return_on_equity", "ratio.asset_turnover", "ratio.cash_conversion_cycle",
    "ratio.operating_cash_flow_margin", "ratio.free_cash_flow_margin",
    "ratio.cash_flow_to_debt", "ratio.cash_interest_coverage",
)


EXPECTED_SOURCE_PATHS = {
    code: (("facts", code.split(".", 1)[1]) if code.startswith(("bs.", "is."))
           else (code.split(".", 1)[1],) if code.startswith("cf.")
           else definition.source_field_path)
    for code, definition in zip(EXPECTED_CODES, TREND_METRIC_DEFINITIONS_V1, strict=True)
}


def _registry(definitions):
    return TrendMetricRegistry(TREND_METRIC_REGISTRY_VERSION, tuple(definitions))


def test_exact_registry_count_distribution_and_metric_code_snapshot():
    assert len(TREND_METRIC_REGISTRY_V1.definitions) == 45
    assert TREND_METRIC_REGISTRY_V1.metric_codes == EXPECTED_CODES
    assert {
        engine: sum(item.source_engine_type is engine for item in TREND_METRIC_DEFINITIONS_V1)
        for engine in TrendSourceEngineType
    } == {
        TrendSourceEngineType.BALANCE_SHEET: 11,
        TrendSourceEngineType.INCOME_STATEMENT: 11,
        TrendSourceEngineType.CASH_FLOW: 7,
        TrendSourceEngineType.FINANCIAL_RATIOS: 16,
    }


@pytest.mark.parametrize("definition", TREND_METRIC_DEFINITIONS_V1, ids=lambda item: item.metric_code)
def test_every_metric_has_exact_authoritative_path_and_single_lookup(definition):
    assert definition.source_field_path == EXPECTED_SOURCE_PATHS[definition.metric_code]
    assert TREND_METRIC_REGISTRY_V1.get(definition.metric_code) is definition
    assert sum(
        item.authoritative_source_key == definition.authoritative_source_key
        for item in TREND_METRIC_DEFINITIONS_V1
    ) == 1


def test_duplicate_code_and_authoritative_source_are_rejected():
    duplicate_code = replace(
        TREND_METRIC_DEFINITIONS_V1[-1],
        metric_code=TREND_METRIC_DEFINITIONS_V1[-2].metric_code,
    )
    with pytest.raises(TrendMetricRegistryError, match="duplicate metric code"):
        _registry(TREND_METRIC_DEFINITIONS_V1[:-1] + (duplicate_code,))

    duplicate_source = replace(
        TREND_METRIC_DEFINITIONS_V1[1],
        source_field_path=TREND_METRIC_DEFINITIONS_V1[0].source_field_path,
    )
    with pytest.raises(TrendMetricRegistryError, match="duplicate authoritative source"):
        _registry((TREND_METRIC_DEFINITIONS_V1[0], duplicate_source) + TREND_METRIC_DEFINITIONS_V1[2:])


def test_registry_and_definitions_are_immutable_and_have_safe_repr():
    with pytest.raises(FrozenInstanceError):
        TREND_METRIC_REGISTRY_V1.registry_version = "changed"
    with pytest.raises(FrozenInstanceError):
        TREND_METRIC_DEFINITIONS_V1[0].metric_code = "changed"
    assert repr(TREND_METRIC_REGISTRY_V1) == "TrendMetricRegistry()"
    assert repr(TREND_METRIC_DEFINITIONS_V1[0]) == "TrendMetricDefinition()"


def test_registry_input_order_does_not_change_order_lookup_or_digest():
    reversed_registry = _registry(tuple(reversed(TREND_METRIC_DEFINITIONS_V1)))
    assert reversed_registry.definitions == TREND_METRIC_REGISTRY_V1.definitions
    assert reversed_registry.metric_codes == EXPECTED_CODES
    assert reversed_registry.digest == TREND_METRIC_REGISTRY_V1.digest
    assert reversed_registry.get("ratio.current_ratio").ratio_code == "current_ratio"


def test_registry_digest_is_exact_version_prefixed_and_version_sensitive():
    assert TREND_METRIC_REGISTRY_V1.digest == "1b2085553cd2009c349cbca45d5f6ebc9f2f8ba07f9b9ee1b2930554bc52d19e"
    assert TREND_METRIC_REGISTRY_V1.reference == (
        "trend-metric-registry:v1:sha256:"
        "1b2085553cd2009c349cbca45d5f6ebc9f2f8ba07f9b9ee1b2930554bc52d19e"
    )
    changed = registry_with_version(TREND_METRIC_REGISTRY_V1, "trend-metric-registry/1.0.1")
    assert changed.digest != TREND_METRIC_REGISTRY_V1.digest


@pytest.mark.parametrize(
    "field_name,new_value",
    (
        ("source_field_path", ("facts", "changed")),
        ("percentage_change_enabled", False),
        ("direction_tolerance", Decimal("0.02")),
        ("volatility_low_maximum", Decimal("0.0600")),
        ("break_score_minimum", Decimal("0.1100")),
        ("accepted_source_versions", (TrendSourceVersion(None, "1.0.1"),)),
    ),
)
def test_semantic_field_changes_registry_digest(field_name, new_value):
    changed_definition = replace(TREND_METRIC_DEFINITIONS_V1[0], **{field_name: new_value})
    changed = _registry((changed_definition,) + TREND_METRIC_DEFINITIONS_V1[1:])
    assert changed.digest != TREND_METRIC_REGISTRY_V1.digest


def test_unknown_metric_fails_closed():
    with pytest.raises(UnknownTrendMetricCode, match="unknown trend metric"):
        TREND_METRIC_REGISTRY_V1.get("bs.not_registered")


def test_deprecated_replacement_must_be_registered_and_terminal():
    deprecated = replace(
        TREND_METRIC_DEFINITIONS_V1[0],
        deprecated=True,
        replacement_metric_code="bs.non_current_assets",
    )
    registry = _registry((deprecated,) + TREND_METRIC_DEFINITIONS_V1[1:])
    assert registry.get("bs.current_assets").replacement_metric_code == "bs.non_current_assets"
    bad = replace(deprecated, replacement_metric_code="bs.unknown")
    with pytest.raises(TrendMetricRegistryError, match="not registered"):
        _registry((bad,) + TREND_METRIC_DEFINITIONS_V1[1:])
    chained = replace(
        TREND_METRIC_DEFINITIONS_V1[1],
        deprecated=True,
        replacement_metric_code="bs.total_assets",
    )
    with pytest.raises(TrendMetricRegistryError, match="replacement chains"):
        _registry((deprecated, chained) + TREND_METRIC_DEFINITIONS_V1[2:])


def test_deleted_metric_code_is_tombstoned_and_cannot_be_reused_or_redefined():
    original = TREND_METRIC_DEFINITIONS_V1[0]
    successor_version = "trend-metric-registry/1.1.0"
    successor_definitions = tuple(
        replace(item, registry_version=successor_version, display_order_index=index)
        for index, item in enumerate(TREND_METRIC_DEFINITIONS_V1[1:])
    )
    tombstone = TrendMetricTombstone(
        original.metric_code, original.semantic_digest, successor_version
    )
    successor = TrendMetricRegistry(successor_version, successor_definitions, (tombstone,))
    TREND_METRIC_REGISTRY_V1.assert_compatible_successor(successor)
    reused = replace(original, registry_version=successor_version, source_field_path=("facts", "different"))
    reuse_definitions = (reused,) + tuple(
        replace(item, display_order_index=index)
        for index, item in enumerate(successor_definitions, start=1)
    )
    with pytest.raises(TrendMetricRegistryError, match="cannot be reused"):
        TrendMetricRegistry(successor_version, reuse_definitions, (tombstone,))
    changed_active = TrendMetricRegistry(
        successor_version,
        reuse_definitions,
    )
    with pytest.raises(TrendMetricRegistryError, match="semantic reuse"):
        TREND_METRIC_REGISTRY_V1.assert_compatible_successor(changed_active)


@pytest.mark.parametrize("definition", TREND_METRIC_DEFINITIONS_V1[:11], ids=lambda item: item.metric_code)
def test_all_balance_sheet_metrics_are_stock_as_of(definition):
    assert {basis for _, basis in definition.measurement_basis_by_period_family} == {
        TrendMeasurementBasis.STOCK_AS_OF
    }


@pytest.mark.parametrize("definition", TREND_METRIC_DEFINITIONS_V1[29:], ids=lambda item: item.metric_code)
def test_all_ratio_metrics_are_ratio_rate_and_cagr_percentage_disabled(definition):
    assert {basis for _, basis in definition.measurement_basis_by_period_family} == {
        TrendMeasurementBasis.RATIO_RATE
    }
    assert definition.percentage_change_enabled is False
    assert definition.cagr_enabled is False


@pytest.mark.parametrize("definition", TREND_METRIC_DEFINITIONS_V1[11:29], ids=lambda item: item.metric_code)
def test_income_statement_and_cash_flow_basis_exact_family_manifest(definition):
    for family, basis in definition.measurement_basis_by_period_family:
        expected = (
            TrendMeasurementBasis.STOCK_AS_OF
            if definition.metric_code in {
                "cf.opening_cash_and_cash_equivalents",
                "cf.closing_cash_and_cash_equivalents",
            }
            else TrendMeasurementBasis.CUMULATIVE_FLOW
            if family in {
                TrendPeriodFamily.QUARTERLY_CUMULATIVE_YOY,
                TrendPeriodFamily.TEMPORARY_TAX_CUMULATIVE_YOY,
            }
            else TrendMeasurementBasis.DISCRETE_FLOW
        )
        assert basis is expected


def test_invalid_mixed_basis_and_unsupported_family_fail_closed():
    definition = TREND_METRIC_DEFINITIONS_V1[0]
    with pytest.raises(TrendMetricRegistryError):
        replace(
            definition,
            measurement_basis_by_period_family=(
                (TrendPeriodFamily.ANNUAL, TrendMeasurementBasis.STOCK_AS_OF),
                (TrendPeriodFamily.ANNUAL, TrendMeasurementBasis.DISCRETE_FLOW),
            ),
            eligible_period_families=(TrendPeriodFamily.ANNUAL, TrendPeriodFamily.ANNUAL),
        )
    annual_only = replace(
        definition,
        measurement_basis_by_period_family=((TrendPeriodFamily.ANNUAL, TrendMeasurementBasis.STOCK_AS_OF),),
        eligible_period_families=(TrendPeriodFamily.ANNUAL,),
    )
    with pytest.raises(TrendMetricRegistryError, match="not eligible"):
        annual_only.measurement_basis_for(TrendPeriodFamily.MONTHLY_DISCRETE)


@pytest.mark.parametrize("definition", TREND_METRIC_DEFINITIONS_V1, ids=lambda item: item.metric_code)
def test_exact_eligibility_tolerance_and_threshold_metadata(definition):
    monetary = definition.unit is TrendMetricUnit.TRY
    assert definition.percentage_change_enabled is monetary
    assert definition.cagr_enabled is monetary
    assert definition.direction_enabled is True
    assert definition.direction_tolerance == (
        Decimal("0.01") if definition.unit in {TrendMetricUnit.TRY, TrendMetricUnit.DAYS}
        else Decimal("0.0001")
    )
    assert definition.normalized_direction_tolerance == Decimal("0.0001")
    assert definition.volatility_enabled is True
    assert definition.volatility_low_maximum == Decimal("0.0500")
    assert definition.volatility_medium_maximum == Decimal("0.1500")
    assert definition.break_enabled is True
    assert definition.break_score_minimum == Decimal("0.1000")


@pytest.mark.parametrize("definition", TREND_METRIC_DEFINITIONS_V1, ids=lambda item: item.metric_code)
def test_source_version_allowlist_is_exact_and_unknown_versions_fail_closed(definition):
    accepted = definition.accepted_source_versions[0]
    assert definition.source_compatibility(
        schema_version=accepted.schema_version, model_version=accepted.model_version
    ).accepted is True
    schema_rejected = definition.source_compatibility(
        schema_version="99.0", model_version=accepted.model_version
    )
    model_rejected = definition.source_compatibility(
        schema_version=accepted.schema_version, model_version="99.0.0"
    )
    assert schema_rejected.status is TrendSourceCompatibilityStatus.SCHEMA_VERSION_UNSUPPORTED
    assert model_rejected.status is TrendSourceCompatibilityStatus.MODEL_VERSION_UNSUPPORTED


def test_explicit_compatibility_manifest_accepts_only_declared_pairs():
    definition = TREND_METRIC_DEFINITIONS_V1[0]
    compatible = replace(
        definition,
        accepted_source_versions=(
            TrendSourceVersion(None, "1.0.0"),
            TrendSourceVersion(None, "1.1.0"),
        ),
    )
    assert compatible.source_compatibility(schema_version=None, model_version="1.1.0").accepted
    assert not compatible.source_compatibility(schema_version=None, model_version="2.0.0").accepted


def test_registry_module_is_metadata_only_and_has_no_global_fallback_profile():
    import app.engines.multi_period_trend.registry as module

    assert not hasattr(module, "calculate_cagr")
    assert not hasattr(module, "resolve_series")
    assert not hasattr(module, "GLOBAL_THRESHOLD_FALLBACK")
    assert all(type(item.direction_tolerance) is Decimal for item in TREND_METRIC_DEFINITIONS_V1)
