"""
Milestone 4.4 -- Dashboard Snapshot katmanı: `generate_dashboard_snapshot()`.
Dashboard Pipeline -- KESİN 9 adım (tasarım dokümanı Bölüm 17.2 / kullanıcının
implementasyon-onay mesajı madde 16).

`DASHBOARD_PRESENTATION_ONLY`: upstream motor ÇAĞRILMAZ, narrative rapor
ÜRETİLMEZ (section/uzun-form block YOK), yeni metric/score HESAPLANMAZ.
"""

import copy
from dataclasses import dataclass
from typing import Any

from app.engines.common.credit_score_types import CreditScoreResult
from app.engines.common.dashboard_registry import (
    DASHBOARD_INPUT_COMPATIBILITY,
    DASHBOARD_TYPE_LEGAL_PROFILES,
    DASHBOARD_WIDGET_REGISTRY,
)
from app.engines.common.dashboard_types import (
    DASHBOARD_MODEL_VERSION,
    DASHBOARD_SCHEMA_VERSION,
    DashboardAlertReference,
    DashboardMetricReference,
    DashboardSnapshot,
    DashboardType,
    DashboardWidget,
)
from app.engines.common.health_score_types import HealthScoreResult
from app.engines.common.recommendation_types import RecommendationPriority, RecommendationResult
from app.engines.common.report_types import (
    ReportBlockType,
    ReportCompanyMetadata,
    ReportDisclaimerBlock,
    SourceConfidenceEntry,
    SourceCoverageEntry,
)


@dataclass(frozen=True)
class _DashboardBuildContext:
    health_score_result: HealthScoreResult
    credit_score_result: CreditScoreResult
    recommendation_result: RecommendationResult
    benchmark_result_json: "dict[str, Any] | None"
    company_metadata: ReportCompanyMetadata


def _widget_health_score_headline(ctx: _DashboardBuildContext, widget_code: str):
    hs = ctx.health_score_result
    metric = DashboardMetricReference("health_score", "Finansal Sağlık Skoru", f"{hs.final_score} ({hs.letter_rating})", None)
    return DashboardWidget(widget_code, ReportBlockType.KPI_CARD, metric, None, "health_score_result.final_score")


def _widget_credit_score_headline(ctx: _DashboardBuildContext, widget_code: str):
    cs = ctx.credit_score_result
    metric = DashboardMetricReference("credit_score", "Kredi Skoru", f"{cs.final_score} ({cs.risk_tier})", None)
    return DashboardWidget(widget_code, ReportBlockType.KPI_CARD, metric, None, "credit_score_result.final_score")


def _widget_top_recommendations(ctx: _DashboardBuildContext, widget_code: str):
    items = list(ctx.recommendation_result.recommendations)[:5]
    codes = ", ".join(i.recommendation_code for i in items) or "yok"
    metric = DashboardMetricReference("recommendation", "En Öncelikli Öneriler", codes, None)
    return DashboardWidget(widget_code, ReportBlockType.CHART_DATA, metric, None, "recommendation_result.recommendations")


def _widget_data_quality_badge(ctx: _DashboardBuildContext, widget_code: str):
    low_conf = bool(ctx.health_score_result.low_confidence_warning or ctx.credit_score_result.low_confidence_warning)
    alert = DashboardAlertReference("health_score" if ctx.health_score_result.low_confidence_warning else "credit_score", "warning" if low_conf else "ok", "Düşük Güvenilirlik Uyarısı" if low_conf else "Veri Kalitesi Normal", None)
    return DashboardWidget(widget_code, ReportBlockType.BADGE, None, alert, "health_score_result.low_confidence_warning / credit_score_result.low_confidence_warning")


def _widget_benchmark_position_summary(ctx: _DashboardBuildContext, widget_code: str):
    if not ctx.benchmark_result_json:
        metric = DashboardMetricReference("benchmarks", "Sektör Konumu", "mevcut değil", None)
    else:
        categories = ctx.benchmark_result_json.get("categories") or {}
        count = sum(len((c or {}).get("ratios") or {}) for c in categories.values())
        metric = DashboardMetricReference("benchmarks", "Sektör Konumu", f"{count} oran değerlendirildi", None)
    return DashboardWidget(widget_code, ReportBlockType.CHART_DATA, metric, None, "benchmark_result_json.categories")


def _widget_hard_fail_alerts(ctx: _DashboardBuildContext, widget_code: str):
    total = len(ctx.health_score_result.hard_fails_triggered) + len(ctx.credit_score_result.hard_fails_triggered)
    alert = DashboardAlertReference("health_score+credit_score", "critical" if total else "ok", f"{total} hard-fail tetiklendi", None)
    return DashboardWidget(widget_code, ReportBlockType.CHART_DATA, None, alert, "health_score_result.hard_fails_triggered / credit_score_result.hard_fails_triggered")


def _widget_critical_recommendations(ctx: _DashboardBuildContext, widget_code: str):
    critical = [i for i in ctx.recommendation_result.recommendations if i.priority == RecommendationPriority.CRITICAL]
    metric = DashboardMetricReference("recommendation", "Kritik Öneriler", f"{len(critical)} adet", None)
    return DashboardWidget(widget_code, ReportBlockType.CHART_DATA, metric, None, "recommendation_result.recommendations")


def _widget_risk_tier_badge(ctx: _DashboardBuildContext, widget_code: str):
    cs = ctx.credit_score_result
    alert = DashboardAlertReference("credit_score", str(cs.risk_tier or "n/a"), f"Risk Kademesi: {cs.risk_tier}", None)
    return DashboardWidget(widget_code, ReportBlockType.BADGE, None, alert, "credit_score_result.risk_tier")


def _widget_banking_readiness_alert(ctx: _DashboardBuildContext, widget_code: str):
    count = len(ctx.recommendation_result.banking_readiness_recommendation_codes)
    alert = DashboardAlertReference("recommendation", "warning" if count else "ok", f"{count} bankacılık hazırlığı önerisi", None)
    return DashboardWidget(widget_code, ReportBlockType.BADGE, None, alert, "recommendation_result.banking_readiness_recommendation_codes")


def _widget_uncovered_signal_count(ctx: _DashboardBuildContext, widget_code: str):
    count = len(ctx.recommendation_result.uncovered_signal_codes)
    metric = DashboardMetricReference("recommendation", "Kapsanmayan Sinyal Sayısı", str(count), None)
    return DashboardWidget(widget_code, ReportBlockType.KPI_CARD, metric, None, "recommendation_result.uncovered_signal_codes")


_WIDGET_BUILDERS = {
    "health_score_headline": _widget_health_score_headline,
    "credit_score_headline": _widget_credit_score_headline,
    "top_recommendations": _widget_top_recommendations,
    "data_quality_badge": _widget_data_quality_badge,
    "benchmark_position_summary": _widget_benchmark_position_summary,
    "hard_fail_alerts": _widget_hard_fail_alerts,
    "critical_recommendations": _widget_critical_recommendations,
    "risk_tier_badge": _widget_risk_tier_badge,
    "banking_readiness_alert": _widget_banking_readiness_alert,
    "uncovered_signal_count": _widget_uncovered_signal_count,
}


def _check_dashboard_compatibility(health_score_result, credit_score_result, recommendation_result):
    warnings = []
    values = {
        "health_score_schema_version": health_score_result.health_score_schema_version,
        "credit_score_schema_version": credit_score_result.credit_score_schema_version,
        "recommendation_schema_version": recommendation_result.recommendation_schema_version,
    }
    for key, value in values.items():
        if value not in DASHBOARD_INPUT_COMPATIBILITY[key]:
            warnings.append({"code": "SCHEMA_VERSION_UNSUPPORTED", "field": key, "value": value, "supported": DASHBOARD_INPUT_COMPATIBILITY[key]})
    incompatible = any(w["code"] == "SCHEMA_VERSION_UNSUPPORTED" for w in warnings)
    return (not incompatible), tuple(warnings)


def generate_dashboard_snapshot(
    dashboard_type: DashboardType,
    health_score_result: HealthScoreResult,
    credit_score_result: CreditScoreResult,
    recommendation_result: RecommendationResult,
    *,
    benchmark_result_json: "dict[str, Any] | None" = None,
    company_metadata: ReportCompanyMetadata,
    report_id: "str | None" = None,
    generated_at: "str | None" = None,
) -> DashboardSnapshot:
    # Adım 1: Compatibility
    _bench_before = copy.deepcopy(benchmark_result_json) if benchmark_result_json is not None else None
    is_compatible, compat_warnings = _check_dashboard_compatibility(health_score_result, credit_score_result, recommendation_result)

    legal_profile = DASHBOARD_TYPE_LEGAL_PROFILES[dashboard_type]

    # Adım 2: Immutable input validation (yukarıdaki deep-copy snapshot'ı)

    if not is_compatible:
        result = DashboardSnapshot(
            dashboard_type=dashboard_type, widgets=(), company_metadata=company_metadata,
            source_confidence_inventory=(), source_coverage_inventory=(), engines_used=(),
            disclaimer_blocks=(), warnings=compat_warnings, decision_support_only=True,
            legal_review_status=legal_profile.legal_review_status,
            confidentiality_level=legal_profile.confidentiality_level,
            external_distribution_allowed=legal_profile.external_distribution_allowed,
            report_id=report_id, generated_at=generated_at,
            dashboard_schema_version=DASHBOARD_SCHEMA_VERSION, dashboard_model_version=DASHBOARD_MODEL_VERSION,
            health_score_schema_version=health_score_result.health_score_schema_version,
            credit_score_schema_version=credit_score_result.credit_score_schema_version,
            recommendation_schema_version=recommendation_result.recommendation_schema_version,
        )
        return result

    ctx = _DashboardBuildContext(
        health_score_result=health_score_result, credit_score_result=credit_score_result,
        recommendation_result=recommendation_result, benchmark_result_json=benchmark_result_json,
        company_metadata=company_metadata,
    )

    # Adım 3: Dashboard type resolution
    widget_definitions = DASHBOARD_WIDGET_REGISTRY[dashboard_type]

    # Adım 4: Widget registry resolution + Adım 5: Widget source references build
    widgets = tuple(
        _WIDGET_BUILDERS[wd.builder_strategy](ctx, wd.widget_code)
        for wd in sorted(widget_definitions, key=lambda w: w.display_order)
    )

    # Adım 6: Stable ordering -- yukarıda `display_order` ile ZATEN sağlandı.

    engines_used = tuple(sorted({eng for wd in widget_definitions for eng in wd.source_engine_codes}))

    disclaimer_blocks = (
        ReportDisclaimerBlock("DASH_DISC_01", "Bu pano bir karar-destek özetidir; resmi bir mali tablo veya kredi onayı DEĞİLDİR.", "dashboard_engine"),
    )

    source_confidence_inventory = (
        SourceConfidenceEntry("health_score", True, health_score_result.confidence_score, None, None, None, ()),
        SourceConfidenceEntry("credit_score", True, credit_score_result.confidence_score, None, None, None, ()),
        SourceConfidenceEntry("recommendation", False, None, None, "RECOMMENDATION_CONFIDENCE_IS_PER_ITEM_NOT_ENGINE_LEVEL", "Her öneri KENDİ confidence alanını taşır.", ()),
    )
    source_coverage_inventory = (
        SourceCoverageEntry("health_score", True, health_score_result.data_coverage_ratio, None, None, ()),
        SourceCoverageEntry("credit_score", True, credit_score_result.data_coverage_ratio, None, None, ()),
        SourceCoverageEntry("recommendation", False, None, "RECOMMENDATION_CONFIDENCE_IS_PER_ITEM_NOT_ENGINE_LEVEL", "Her öneri KENDİ coverage alanını taşır.", ()),
    )

    # Adım 7: Legal/confidentiality metadata -- yukarıda `legal_profile`'dan zaten okundu.

    result = DashboardSnapshot(
        dashboard_type=dashboard_type, widgets=widgets, company_metadata=company_metadata,
        source_confidence_inventory=source_confidence_inventory, source_coverage_inventory=source_coverage_inventory,
        engines_used=engines_used, disclaimer_blocks=disclaimer_blocks, warnings=compat_warnings,
        decision_support_only=True, legal_review_status=legal_profile.legal_review_status,
        confidentiality_level=legal_profile.confidentiality_level,
        external_distribution_allowed=legal_profile.external_distribution_allowed,
        report_id=report_id, generated_at=generated_at,
        dashboard_schema_version=DASHBOARD_SCHEMA_VERSION, dashboard_model_version=DASHBOARD_MODEL_VERSION,
        health_score_schema_version=health_score_result.health_score_schema_version,
        credit_score_schema_version=credit_score_result.credit_score_schema_version,
        recommendation_schema_version=recommendation_result.recommendation_schema_version,
    )

    # Adım 8: Presentation-only invariant kontrolü -- DASHBOARD_PRESENTATION_ONLY
    if benchmark_result_json is not None:
        assert benchmark_result_json == _bench_before, "READ-ONLY INVARIANT İHLALİ: benchmark_result_json mutasyona uğradı"

    # Adım 9: DashboardSnapshot
    return result
