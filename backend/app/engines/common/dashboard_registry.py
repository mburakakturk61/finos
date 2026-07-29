"""
Milestone 4.4 -- Dashboard widget registry'si. Tasarım dokümanı Bölüm 2.4 --
KAPALI, v1 nihai, 2 `DashboardType` x 5 widget = 10 widget TAM envanteri.
"""

from dataclasses import dataclass

from app.engines.common.dashboard_types import ALLOWED_DASHBOARD_WIDGET_TYPES, DashboardType
from app.engines.common.report_types import ReportBlockType


class InvalidDashboardWidgetTypeError(ValueError):
    pass


@dataclass(frozen=True)
class DashboardWidgetDefinition:
    widget_code: str
    dashboard_type: DashboardType
    widget_type: ReportBlockType
    display_order: int
    source_engine_codes: "tuple[str, ...]"
    builder_strategy: str


DASHBOARD_WIDGET_REGISTRY: "dict[DashboardType, tuple[DashboardWidgetDefinition, ...]]" = {}


def register_dashboard_widget(
    definition: DashboardWidgetDefinition,
    *,
    registry: "dict[DashboardType, tuple[DashboardWidgetDefinition, ...]] | None" = None,
) -> None:
    target = DASHBOARD_WIDGET_REGISTRY if registry is None else registry
    if definition.widget_type not in ALLOWED_DASHBOARD_WIDGET_TYPES:
        raise InvalidDashboardWidgetTypeError(
            f"{definition.widget_code!r}: widget_type {definition.widget_type!r} Dashboard'da İZİN VERİLMEZ "
            f"(yalnızca {sorted(t.value for t in ALLOWED_DASHBOARD_WIDGET_TYPES)})"
        )
    existing = target.get(definition.dashboard_type, ())
    if any(w.widget_code == definition.widget_code for w in existing):
        raise ValueError(f"widget_code zaten kayıtlı: {definition.widget_code!r}")
    if any(w.display_order == definition.display_order for w in existing):
        raise ValueError(f"{definition.dashboard_type!r}: yinelenen display_order {definition.display_order!r}")
    target[definition.dashboard_type] = existing + (definition,)


def _build_registry() -> "dict[DashboardType, tuple[DashboardWidgetDefinition, ...]]":
    reg: "dict[DashboardType, tuple[DashboardWidgetDefinition, ...]]" = {}
    ED, RD = DashboardType.EXECUTIVE_DASHBOARD, DashboardType.RISK_DASHBOARD
    KPI, BADGE, CHART = ReportBlockType.KPI_CARD, ReportBlockType.BADGE, ReportBlockType.CHART_DATA

    register_dashboard_widget(DashboardWidgetDefinition(
        "WGT_HEALTH_SCORE_HEADLINE", ED, KPI, 1, ("health_score",), "health_score_headline"), registry=reg)
    register_dashboard_widget(DashboardWidgetDefinition(
        "WGT_CREDIT_SCORE_HEADLINE", ED, KPI, 2, ("credit_score",), "credit_score_headline"), registry=reg)
    register_dashboard_widget(DashboardWidgetDefinition(
        "WGT_TOP_RECOMMENDATIONS", ED, CHART, 3, ("recommendation",), "top_recommendations"), registry=reg)
    register_dashboard_widget(DashboardWidgetDefinition(
        "WGT_DATA_QUALITY_BADGE", ED, BADGE, 4, ("health_score", "credit_score"), "data_quality_badge"), registry=reg)
    register_dashboard_widget(DashboardWidgetDefinition(
        "WGT_BENCHMARK_POSITION_SUMMARY", ED, CHART, 5, ("benchmarks",), "benchmark_position_summary"), registry=reg)

    register_dashboard_widget(DashboardWidgetDefinition(
        "WGT_HARD_FAIL_ALERTS", RD, CHART, 1, ("health_score", "credit_score"), "hard_fail_alerts"), registry=reg)
    register_dashboard_widget(DashboardWidgetDefinition(
        "WGT_CRITICAL_RECOMMENDATIONS", RD, CHART, 2, ("recommendation",), "critical_recommendations"), registry=reg)
    register_dashboard_widget(DashboardWidgetDefinition(
        "WGT_RISK_TIER_BADGE", RD, BADGE, 3, ("credit_score",), "risk_tier_badge"), registry=reg)
    register_dashboard_widget(DashboardWidgetDefinition(
        "WGT_BANKING_READINESS_ALERT", RD, BADGE, 4, ("recommendation",), "banking_readiness_alert"), registry=reg)
    register_dashboard_widget(DashboardWidgetDefinition(
        "WGT_UNCOVERED_SIGNAL_COUNT", RD, KPI, 5, ("recommendation",), "uncovered_signal_count"), registry=reg)
    return reg


DASHBOARD_WIDGET_REGISTRY.update(_build_registry())


DASHBOARD_INPUT_COMPATIBILITY: "dict[str, tuple[str, ...]]" = {
    "health_score_schema_version": ("1.0.0",),
    "credit_score_schema_version": ("1.0.0",),
    "recommendation_schema_version": ("1.0.0",),
}


class DashboardTypeLegalProfile:
    __slots__ = ("legal_review_status", "confidentiality_level", "external_distribution_allowed")

    def __init__(self, legal_review_status, confidentiality_level, external_distribution_allowed) -> None:
        self.legal_review_status = legal_review_status
        self.confidentiality_level = confidentiality_level
        self.external_distribution_allowed = external_distribution_allowed


def _build_legal_profiles():
    from app.engines.common.report_types import ConfidentialityLevel, LegalReviewStatus

    return {
        DashboardType.EXECUTIVE_DASHBOARD: DashboardTypeLegalProfile(
            LegalReviewStatus.INTERNAL_USE_ONLY, ConfidentialityLevel.INTERNAL, False
        ),
        DashboardType.RISK_DASHBOARD: DashboardTypeLegalProfile(
            LegalReviewStatus.INTERNAL_USE_ONLY, ConfidentialityLevel.INTERNAL, False
        ),
    }


DASHBOARD_TYPE_LEGAL_PROFILES: "dict[DashboardType, DashboardTypeLegalProfile]" = _build_legal_profiles()
