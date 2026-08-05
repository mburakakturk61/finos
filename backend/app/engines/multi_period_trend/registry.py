"""Closed, immutable Milestone 4.6B trend metric registry.

The registry is metadata only.  It performs no source resolution and no
trend calculation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from typing import Final

from .canonical import canonical_trend_digest
from .compatibility import (
    TrendSourceCompatibilityDecision,
    TrendSourceVersion,
    decide_source_compatibility,
)
from .types import (
    TREND_METRIC_REGISTRY_VERSION_REFERENCE_V1,
    TrendMeasurementBasis,
    TrendPeriodFamily,
    TrendSourceEngineType,
)


TREND_METRIC_REGISTRY_VERSION: Final = TREND_METRIC_REGISTRY_VERSION_REFERENCE_V1
TREND_METRIC_REGISTRY_REFERENCE_PREFIX_V1: Final = "trend-metric-registry:v1:sha256:"


class TrendMetricRegistryError(ValueError):
    __slots__ = ()


class UnknownTrendMetricCode(TrendMetricRegistryError):
    __slots__ = ()


class TrendSourceAnalysisType(str, Enum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    FINANCIAL_RATIOS = "financial_ratios"


class TrendMetricUnit(str, Enum):
    TRY = "TRY"
    RATIO = "ratio"
    PERCENT = "percent"
    DAYS = "days"


class TrendCurrencyBehavior(str, Enum):
    SAME_TRY_REQUIRED = "same_try_required"
    NOT_APPLICABLE = "not_applicable"


class TrendMetricSignPolicy(str, Enum):
    NEUTRAL = "neutral"
    SIGNED_PERFORMANCE = "signed_performance"
    INVERSE_CONTEXT = "inverse_context"
    CONTEXT_DEPENDENT = "context_dependent"


class TrendMetricRoundingSemantics(str, Enum):
    HALF_EVEN_FIXED_SCALE = "half_even_fixed_scale"


class TrendEvidenceMappingProfile(str, Enum):
    BALANCE_SHEET_SOURCE_MODE = "balance_sheet_source_mode"
    INCOME_STATEMENT_SOURCE_MODE = "income_statement_source_mode"
    CASH_FLOW_PASSTHROUGH = "cash_flow_passthrough"
    RATIO_RELIABILITY = "ratio_reliability"


class _SafeRegistryValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    __str__ = __repr__


def _text(value: object, name: str, maximum: int = 160) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        raise TrendMetricRegistryError(f"{name} must be bounded non-empty text")
    return value


def _threshold(value: object, name: str) -> Decimal:
    if type(value) is not Decimal or not value.is_finite() or value < 0:
        raise TrendMetricRegistryError(f"{name} must be non-negative finite Decimal")
    return value


_FAMILY_ORDER: Final = tuple(TrendPeriodFamily)
_ALL_FAMILIES: Final = _FAMILY_ORDER
_FLOW_BASIS: Final = tuple(
    (family, TrendMeasurementBasis.CUMULATIVE_FLOW)
    if family in {
        TrendPeriodFamily.QUARTERLY_CUMULATIVE_YOY,
        TrendPeriodFamily.TEMPORARY_TAX_CUMULATIVE_YOY,
    }
    else (family, TrendMeasurementBasis.DISCRETE_FLOW)
    for family in _ALL_FAMILIES
)
_STOCK_BASIS: Final = tuple(
    (family, TrendMeasurementBasis.STOCK_AS_OF) for family in _ALL_FAMILIES
)
_RATIO_BASIS: Final = tuple(
    (family, TrendMeasurementBasis.RATIO_RATE) for family in _ALL_FAMILIES
)


@dataclass(frozen=True, repr=False)
class TrendMetricDefinition(_SafeRegistryValue):
    metric_code: str
    source_engine_type: TrendSourceEngineType
    source_analysis_type: TrendSourceAnalysisType
    source_field_path: tuple[str, ...]
    ratio_code: str | None
    measurement_basis_by_period_family: tuple[
        tuple[TrendPeriodFamily, TrendMeasurementBasis], ...
    ]
    unit: TrendMetricUnit
    currency_behavior: TrendCurrencyBehavior
    monetary_unit_multiplier: Decimal | None
    scale: int
    rounding_semantics: TrendMetricRoundingSemantics
    sign_policy: TrendMetricSignPolicy
    eligible_period_families: tuple[TrendPeriodFamily, ...]
    percentage_change_enabled: bool
    cagr_enabled: bool
    direction_enabled: bool
    direction_tolerance: Decimal
    normalized_direction_tolerance: Decimal
    volatility_enabled: bool
    volatility_low_maximum: Decimal
    volatility_medium_maximum: Decimal
    break_enabled: bool
    break_score_minimum: Decimal
    accepted_source_versions: tuple[TrendSourceVersion, ...]
    evidence_mapping: TrendEvidenceMappingProfile
    registry_version: str
    deprecated: bool
    replacement_metric_code: str | None
    display_order_index: int

    def __post_init__(self) -> None:
        code = _text(self.metric_code, "metric_code", 80)
        parts = code.split(".")
        if len(parts) != 2 or any(not part.replace("_", "").isalnum() for part in parts):
            raise TrendMetricRegistryError("metric_code must be a two-part stable code")
        if type(self.source_engine_type) is not TrendSourceEngineType:
            raise TrendMetricRegistryError("source_engine_type must be exact enum")
        if type(self.source_analysis_type) is not TrendSourceAnalysisType:
            raise TrendMetricRegistryError("source_analysis_type must be exact enum")
        expected_analysis = TrendSourceAnalysisType(self.source_engine_type.value)
        if self.source_analysis_type is not expected_analysis:
            raise TrendMetricRegistryError("source engine and analysis type disagree")
        if type(self.source_field_path) is not tuple or not self.source_field_path:
            raise TrendMetricRegistryError("source_field_path must be a non-empty tuple")
        if any(
            type(part) is not str
            or not part
            or len(part) > 80
            or not part.replace("_", "").isalnum()
            for part in self.source_field_path
        ):
            raise TrendMetricRegistryError("source_field_path contains an invalid exact segment")
        if self.source_engine_type is TrendSourceEngineType.FINANCIAL_RATIOS:
            if type(self.ratio_code) is not str or not self.ratio_code:
                raise TrendMetricRegistryError("ratio metric requires ratio_code")
            if self.source_field_path[-2:] != (self.ratio_code, "value"):
                raise TrendMetricRegistryError("ratio path and ratio_code disagree")
        elif self.ratio_code is not None:
            raise TrendMetricRegistryError("non-ratio metric cannot carry ratio_code")
        if type(self.measurement_basis_by_period_family) is not tuple:
            raise TrendMetricRegistryError("basis manifest must be tuple")
        basis_families = tuple(item[0] for item in self.measurement_basis_by_period_family)
        if basis_families != self.eligible_period_families:
            raise TrendMetricRegistryError("basis manifest must exactly match eligible families")
        if len(set(basis_families)) != len(basis_families):
            raise TrendMetricRegistryError("period family cannot have multiple measurement bases")
        if any(
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not TrendPeriodFamily
            or type(item[1]) is not TrendMeasurementBasis
            for item in self.measurement_basis_by_period_family
        ):
            raise TrendMetricRegistryError("basis manifest contains an invalid entry")
        if self.eligible_period_families != tuple(
            family for family in _FAMILY_ORDER if family in self.eligible_period_families
        ) or len(set(self.eligible_period_families)) != len(self.eligible_period_families):
            raise TrendMetricRegistryError("eligible period families must be unique canonical order")
        if type(self.unit) is not TrendMetricUnit or type(self.currency_behavior) is not TrendCurrencyBehavior:
            raise TrendMetricRegistryError("unit/currency behavior must be exact enums")
        if self.unit is TrendMetricUnit.TRY:
            if self.currency_behavior is not TrendCurrencyBehavior.SAME_TRY_REQUIRED:
                raise TrendMetricRegistryError("TRY metric requires same-currency behavior")
            if self.monetary_unit_multiplier != Decimal("1") or self.scale != 2:
                raise TrendMetricRegistryError("TRY metric requires multiplier 1 and scale 2")
        elif self.currency_behavior is not TrendCurrencyBehavior.NOT_APPLICABLE or self.monetary_unit_multiplier is not None:
            raise TrendMetricRegistryError("non-monetary metric cannot carry currency semantics")
        if type(self.scale) is not int or not 0 <= self.scale <= 12:
            raise TrendMetricRegistryError("scale is outside supported range")
        if self.rounding_semantics is not TrendMetricRoundingSemantics.HALF_EVEN_FIXED_SCALE:
            raise TrendMetricRegistryError("unsupported rounding semantics")
        if type(self.sign_policy) is not TrendMetricSignPolicy:
            raise TrendMetricRegistryError("sign_policy must be exact enum")
        for name in (
            "percentage_change_enabled", "cagr_enabled", "direction_enabled",
            "volatility_enabled", "break_enabled", "deprecated",
        ):
            if type(getattr(self, name)) is not bool:
                raise TrendMetricRegistryError(f"{name} must be bool")
        _threshold(self.direction_tolerance, "direction_tolerance")
        _threshold(self.normalized_direction_tolerance, "normalized_direction_tolerance")
        low = _threshold(self.volatility_low_maximum, "volatility_low_maximum")
        medium = _threshold(self.volatility_medium_maximum, "volatility_medium_maximum")
        _threshold(self.break_score_minimum, "break_score_minimum")
        if low >= medium:
            raise TrendMetricRegistryError("volatility thresholds must be increasing")
        if not self.direction_enabled or not self.volatility_enabled or not self.break_enabled:
            raise TrendMetricRegistryError("v1 manifest enables direction, volatility, and break")
        if self.unit is not TrendMetricUnit.TRY and self.cagr_enabled:
            raise TrendMetricRegistryError("v1 CAGR is monetary-only")
        if self.unit in {TrendMetricUnit.RATIO, TrendMetricUnit.PERCENT, TrendMetricUnit.DAYS} and self.percentage_change_enabled:
            raise TrendMetricRegistryError("ratio-rate percentage change is disabled")
        if type(self.accepted_source_versions) is not tuple or not self.accepted_source_versions:
            raise TrendMetricRegistryError("accepted source versions must be non-empty tuple")
        if any(type(item) is not TrendSourceVersion for item in self.accepted_source_versions):
            raise TrendMetricRegistryError("accepted source versions contain invalid entry")
        canonical_versions = tuple(sorted(
            set(self.accepted_source_versions),
            key=lambda item: (item.schema_version is not None, item.schema_version or "", item.model_version),
        ))
        if canonical_versions != self.accepted_source_versions:
            raise TrendMetricRegistryError("accepted source versions must be unique canonical order")
        if type(self.evidence_mapping) is not TrendEvidenceMappingProfile:
            raise TrendMetricRegistryError("evidence_mapping must be exact enum")
        _text(self.registry_version, "registry_version", 80)
        if self.deprecated != (self.replacement_metric_code is not None):
            raise TrendMetricRegistryError("deprecated metrics require exactly one replacement code")
        if self.replacement_metric_code == self.metric_code:
            raise TrendMetricRegistryError("metric cannot replace itself")
        if self.replacement_metric_code is not None:
            _text(self.replacement_metric_code, "replacement_metric_code", 80)
        if type(self.display_order_index) is not int or self.display_order_index < 0:
            raise TrendMetricRegistryError("display_order_index must be non-negative int")
        prefix = {
            TrendSourceEngineType.BALANCE_SHEET: "bs",
            TrendSourceEngineType.INCOME_STATEMENT: "is",
            TrendSourceEngineType.CASH_FLOW: "cf",
            TrendSourceEngineType.FINANCIAL_RATIOS: "ratio",
        }[self.source_engine_type]
        if parts[0] != prefix:
            raise TrendMetricRegistryError("metric code prefix disagrees with source engine")

    @property
    def accepted_source_schema_versions(self) -> tuple[str | None, ...]:
        return tuple(dict.fromkeys(item.schema_version for item in self.accepted_source_versions))

    @property
    def accepted_source_model_versions(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.model_version for item in self.accepted_source_versions))

    @property
    def authoritative_source_key(self) -> tuple[TrendSourceEngineType, tuple[str, ...]]:
        return self.source_engine_type, self.source_field_path

    def measurement_basis_for(self, family: TrendPeriodFamily) -> TrendMeasurementBasis:
        if type(family) is not TrendPeriodFamily:
            raise TrendMetricRegistryError("family must be exact enum")
        for candidate, basis in self.measurement_basis_by_period_family:
            if candidate is family:
                return basis
        raise TrendMetricRegistryError("period family is not eligible for metric")

    def source_compatibility(
        self, *, schema_version: str | None, model_version: str
    ) -> TrendSourceCompatibilityDecision:
        return decide_source_compatibility(
            self.accepted_source_versions,
            schema_version=schema_version,
            model_version=model_version,
        )

    @property
    def semantic_digest(self) -> str:
        return canonical_trend_digest(
            (
                self.metric_code, self.source_engine_type, self.source_analysis_type,
                self.source_field_path, self.ratio_code,
                self.measurement_basis_by_period_family, self.unit,
                self.currency_behavior, self.monetary_unit_multiplier, self.scale,
                self.rounding_semantics, self.sign_policy, self.eligible_period_families,
                self.percentage_change_enabled, self.cagr_enabled,
                self.direction_enabled, self.direction_tolerance,
                self.normalized_direction_tolerance, self.volatility_enabled,
                self.volatility_low_maximum, self.volatility_medium_maximum,
                self.break_enabled, self.break_score_minimum,
                self.accepted_source_versions, self.evidence_mapping,
            )
        )


@dataclass(frozen=True, repr=False)
class TrendMetricTombstone(_SafeRegistryValue):
    metric_code: str
    semantic_digest: str
    retired_in_registry_version: str

    def __post_init__(self) -> None:
        _text(self.metric_code, "metric_code", 80)
        if type(self.semantic_digest) is not str or len(self.semantic_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.semantic_digest
        ):
            raise TrendMetricRegistryError("semantic_digest must be lowercase SHA-256")
        _text(self.retired_in_registry_version, "retired_in_registry_version", 80)


@dataclass(frozen=True, repr=False)
class _TrendMetricRegistryDigestPayload:
    registry_version: str
    definitions: tuple[TrendMetricDefinition, ...]
    retired_metrics: tuple[TrendMetricTombstone, ...]


@dataclass(frozen=True, repr=False)
class TrendMetricRegistry(_SafeRegistryValue):
    registry_version: str
    definitions: tuple[TrendMetricDefinition, ...]
    retired_metrics: tuple[TrendMetricTombstone, ...] = ()

    def __post_init__(self) -> None:
        _text(self.registry_version, "registry_version", 80)
        if type(self.definitions) is not tuple or not self.definitions:
            raise TrendMetricRegistryError("definitions must be a non-empty tuple")
        if any(type(item) is not TrendMetricDefinition for item in self.definitions):
            raise TrendMetricRegistryError("registry contains invalid definition")
        ordered = tuple(sorted(self.definitions, key=lambda item: item.display_order_index))
        object.__setattr__(self, "definitions", ordered)
        if tuple(item.display_order_index for item in ordered) != tuple(range(len(ordered))):
            raise TrendMetricRegistryError("display order must be unique and contiguous")
        codes = tuple(item.metric_code for item in ordered)
        if len(set(codes)) != len(codes):
            raise TrendMetricRegistryError("duplicate metric code")
        sources = tuple(item.authoritative_source_key for item in ordered)
        if len(set(sources)) != len(sources):
            raise TrendMetricRegistryError("duplicate authoritative source")
        if any(item.registry_version != self.registry_version for item in ordered):
            raise TrendMetricRegistryError("definition registry version mismatch")
        if type(self.retired_metrics) is not tuple or any(
            type(item) is not TrendMetricTombstone for item in self.retired_metrics
        ):
            raise TrendMetricRegistryError("retired_metrics must be exact tuple")
        retired = tuple(sorted(self.retired_metrics, key=lambda item: item.metric_code))
        object.__setattr__(self, "retired_metrics", retired)
        retired_codes = tuple(item.metric_code for item in retired)
        if len(set(retired_codes)) != len(retired_codes):
            raise TrendMetricRegistryError("duplicate retired metric code")
        if set(codes) & set(retired_codes):
            raise TrendMetricRegistryError("retired metric code cannot be reused")
        replacement_by_code = {
            item.metric_code: item.replacement_metric_code
            for item in ordered if item.replacement_metric_code is not None
        }
        for code, replacement_code in replacement_by_code.items():
            if replacement_code not in codes:
                raise TrendMetricRegistryError("replacement metric code is not registered")
            if replacement_by_code.get(replacement_code) is not None:
                raise TrendMetricRegistryError("replacement chains are not allowed")

    def get(self, metric_code: str) -> TrendMetricDefinition:
        _text(metric_code, "metric_code", 80)
        for definition in self.definitions:
            if definition.metric_code == metric_code:
                return definition
        raise UnknownTrendMetricCode("unknown trend metric code")

    @property
    def metric_codes(self) -> tuple[str, ...]:
        return tuple(item.metric_code for item in self.definitions)

    @property
    def digest(self) -> str:
        return canonical_trend_digest(
            _TrendMetricRegistryDigestPayload(
                self.registry_version, self.definitions, self.retired_metrics
            )
        )

    @property
    def reference(self) -> str:
        return TREND_METRIC_REGISTRY_REFERENCE_PREFIX_V1 + self.digest

    def assert_compatible_successor(self, successor: "TrendMetricRegistry") -> None:
        if type(successor) is not TrendMetricRegistry:
            raise TrendMetricRegistryError("successor must be exact registry")
        successor_by_code = {item.metric_code: item for item in successor.definitions}
        tombstones = {item.metric_code: item for item in successor.retired_metrics}
        for definition in self.definitions:
            next_definition = successor_by_code.get(definition.metric_code)
            if next_definition is not None:
                if next_definition.semantic_digest != definition.semantic_digest:
                    raise TrendMetricRegistryError("metric code semantic reuse is forbidden")
                continue
            tombstone = tombstones.get(definition.metric_code)
            if tombstone is None or tombstone.semantic_digest != definition.semantic_digest:
                raise TrendMetricRegistryError("removed metric must preserve a semantic tombstone")


_BS_FIELDS: Final = (
    "current_assets", "non_current_assets", "total_assets",
    "short_term_liabilities", "long_term_liabilities", "equity",
    "total_liabilities_and_equity", "cash_and_equivalents", "inventory",
    "trade_receivables", "trade_payables",
)
_IS_FIELDS: Final = (
    "net_sales", "cost_of_sales", "gross_profit", "operating_expenses",
    "operating_profit", "depreciation_and_amortization", "ebit", "ebitda",
    "financing_expenses", "profit_before_tax", "net_profit",
)
_CF_FIELDS: Final = (
    "opening_cash_and_cash_equivalents", "closing_cash_and_cash_equivalents",
    "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
    "calculated_net_cash_change", "free_cash_flow",
)
_RATIO_FIELDS: Final = (
    ("current_ratio", "liquidity", TrendMetricUnit.RATIO),
    ("quick_ratio", "liquidity", TrendMetricUnit.RATIO),
    ("cash_ratio", "liquidity", TrendMetricUnit.RATIO),
    ("debt_ratio", "leverage", TrendMetricUnit.RATIO),
    ("debt_to_equity", "leverage", TrendMetricUnit.RATIO),
    ("gross_profit_margin", "profitability", TrendMetricUnit.PERCENT),
    ("operating_profit_margin", "profitability", TrendMetricUnit.PERCENT),
    ("net_profit_margin", "profitability", TrendMetricUnit.PERCENT),
    ("return_on_assets", "profitability", TrendMetricUnit.PERCENT),
    ("return_on_equity", "profitability", TrendMetricUnit.PERCENT),
    ("asset_turnover", "activity", TrendMetricUnit.RATIO),
    ("cash_conversion_cycle", "activity", TrendMetricUnit.DAYS),
    ("operating_cash_flow_margin", "cash_flow", TrendMetricUnit.PERCENT),
    ("free_cash_flow_margin", "cash_flow", TrendMetricUnit.PERCENT),
    ("cash_flow_to_debt", "cash_flow", TrendMetricUnit.RATIO),
    ("cash_interest_coverage", "cash_flow", TrendMetricUnit.RATIO),
)
_SIGNED_FIELDS: Final = {
    "gross_profit", "operating_profit", "ebit", "ebitda", "profit_before_tax",
    "net_profit", "operating_cash_flow", "investing_cash_flow",
    "financing_cash_flow", "calculated_net_cash_change", "free_cash_flow",
}


def _definition(
    *,
    index: int,
    prefix: str,
    field: str,
    engine: TrendSourceEngineType,
    analysis_type: TrendSourceAnalysisType,
    source_path: tuple[str, ...],
    basis: tuple[tuple[TrendPeriodFamily, TrendMeasurementBasis], ...],
    unit: TrendMetricUnit,
    source_version: TrendSourceVersion,
    evidence_mapping: TrendEvidenceMappingProfile,
    ratio_code: str | None = None,
) -> TrendMetricDefinition:
    money = unit is TrendMetricUnit.TRY
    direction_tolerance = Decimal("0.01") if unit in {TrendMetricUnit.TRY, TrendMetricUnit.DAYS} else Decimal("0.0001")
    return TrendMetricDefinition(
        metric_code=f"{prefix}.{field}",
        source_engine_type=engine,
        source_analysis_type=analysis_type,
        source_field_path=source_path,
        ratio_code=ratio_code,
        measurement_basis_by_period_family=basis,
        unit=unit,
        currency_behavior=TrendCurrencyBehavior.SAME_TRY_REQUIRED if money else TrendCurrencyBehavior.NOT_APPLICABLE,
        monetary_unit_multiplier=Decimal("1") if money else None,
        scale=2 if unit in {TrendMetricUnit.TRY, TrendMetricUnit.DAYS} else 4,
        rounding_semantics=TrendMetricRoundingSemantics.HALF_EVEN_FIXED_SCALE,
        sign_policy=TrendMetricSignPolicy.SIGNED_PERFORMANCE if field in _SIGNED_FIELDS else TrendMetricSignPolicy.NEUTRAL,
        eligible_period_families=_ALL_FAMILIES,
        percentage_change_enabled=money,
        cagr_enabled=money,
        direction_enabled=True,
        direction_tolerance=direction_tolerance,
        normalized_direction_tolerance=Decimal("0.0001"),
        volatility_enabled=True,
        volatility_low_maximum=Decimal("0.0500"),
        volatility_medium_maximum=Decimal("0.1500"),
        break_enabled=True,
        break_score_minimum=Decimal("0.1000"),
        accepted_source_versions=(source_version,),
        evidence_mapping=evidence_mapping,
        registry_version=TREND_METRIC_REGISTRY_VERSION,
        deprecated=False,
        replacement_metric_code=None,
        display_order_index=index,
    )


def _build_v1_definitions() -> tuple[TrendMetricDefinition, ...]:
    definitions: list[TrendMetricDefinition] = []
    for field in _BS_FIELDS:
        definitions.append(_definition(
            index=len(definitions), prefix="bs", field=field,
            engine=TrendSourceEngineType.BALANCE_SHEET,
            analysis_type=TrendSourceAnalysisType.BALANCE_SHEET,
            source_path=("facts", field), basis=_STOCK_BASIS, unit=TrendMetricUnit.TRY,
            source_version=TrendSourceVersion(None, "1.0.0"),
            evidence_mapping=TrendEvidenceMappingProfile.BALANCE_SHEET_SOURCE_MODE,
        ))
    for field in _IS_FIELDS:
        definitions.append(_definition(
            index=len(definitions), prefix="is", field=field,
            engine=TrendSourceEngineType.INCOME_STATEMENT,
            analysis_type=TrendSourceAnalysisType.INCOME_STATEMENT,
            source_path=("facts", field), basis=_FLOW_BASIS, unit=TrendMetricUnit.TRY,
            source_version=TrendSourceVersion(None, "1.0.0"),
            evidence_mapping=TrendEvidenceMappingProfile.INCOME_STATEMENT_SOURCE_MODE,
        ))
    for field in _CF_FIELDS:
        definitions.append(_definition(
            index=len(definitions), prefix="cf", field=field,
            engine=TrendSourceEngineType.CASH_FLOW,
            analysis_type=TrendSourceAnalysisType.CASH_FLOW,
            source_path=(field,),
            basis=_STOCK_BASIS if field in _CF_FIELDS[:2] else _FLOW_BASIS,
            unit=TrendMetricUnit.TRY,
            source_version=TrendSourceVersion("1.0.0", "1.0.0"),
            evidence_mapping=TrendEvidenceMappingProfile.CASH_FLOW_PASSTHROUGH,
        ))
    for field, category, unit in _RATIO_FIELDS:
        definitions.append(_definition(
            index=len(definitions), prefix="ratio", field=field,
            engine=TrendSourceEngineType.FINANCIAL_RATIOS,
            analysis_type=TrendSourceAnalysisType.FINANCIAL_RATIOS,
            source_path=("categories", category, "ratios", field, "value"),
            basis=_RATIO_BASIS, unit=unit,
            source_version=TrendSourceVersion("1.0", "1.1.0"),
            evidence_mapping=TrendEvidenceMappingProfile.RATIO_RELIABILITY,
            ratio_code=field,
        ))
    return tuple(definitions)


TREND_METRIC_DEFINITIONS_V1: Final = _build_v1_definitions()
TREND_METRIC_REGISTRY_V1: Final = TrendMetricRegistry(
    registry_version=TREND_METRIC_REGISTRY_VERSION,
    definitions=TREND_METRIC_DEFINITIONS_V1,
)

if len(TREND_METRIC_REGISTRY_V1.definitions) != 45:
    raise TrendMetricRegistryError("v1 registry must contain exactly 45 metrics")


def registry_with_version(
    registry: TrendMetricRegistry, registry_version: str
) -> TrendMetricRegistry:
    """Test/upgrade helper that changes only the explicit registry version."""

    _text(registry_version, "registry_version", 80)
    return TrendMetricRegistry(
        registry_version=registry_version,
        definitions=tuple(
            replace(item, registry_version=registry_version)
            for item in registry.definitions
        ),
        retired_metrics=registry.retired_metrics,
    )
