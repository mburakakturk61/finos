"""
Milestone 4.4 (Executive Report Engine) -- Dashboard Snapshot katmanı
veri modeli. Tasarım dokümanı Bölüm 2 -- narrative Report Engine'den
TAMAMEN AYRI bir contract (Madde 11/12, KİLİTLİ).

`DashboardSnapshot`, `ExecutiveReportResult`'ın (report_types.py) ALT
TİPİ DEĞİLDİR ve HİÇBİR alanını PAYLAŞMAZ (yalnızca küçük, ORTAK value
object'ler -- `ReportCompanyMetadata`/`ReportDisclaimerBlock`/`Legal
ReviewStatus`/`ConfidentialityLevel`/`ReportBlockType` -- report_types.py'dan
İTHAL EDİLİR, bu KOD TEKRARINI ÖNLEMEK içindir, kavramsal karışma DEĞİLDİR).
"""

from dataclasses import dataclass
import enum
from typing import Any

from app.engines.common.report_types import (
    ConfidentialityLevel,
    LegalReviewStatus,
    ReportBlockType,
    ReportCompanyMetadata,
    ReportDisclaimerBlock,
    SourceConfidenceEntry,
    SourceCoverageEntry,
)


DASHBOARD_SCHEMA_VERSION = "1.0.0"
DASHBOARD_MODEL_VERSION = "1.0.0"

# Bölüm 2.5 -- Dashboard widget'ları YALNIZCA bu 3 tipten OLABİLİR (uzun-form
# içerik türleri -- table/paragraph/bullet_list -- Dashboard'da YASAKTIR).
ALLOWED_DASHBOARD_WIDGET_TYPES: "frozenset[ReportBlockType]" = frozenset(
    {ReportBlockType.KPI_CARD, ReportBlockType.BADGE, ReportBlockType.CHART_DATA}
)


class DashboardType(str, enum.Enum):
    """Bölüm 1.1 (2. tur Bölüm 6) -- KAPALI, 2 değerli, `ReportType`'tan AYRI."""

    EXECUTIVE_DASHBOARD = "executive_dashboard"
    RISK_DASHBOARD = "risk_dashboard"


@dataclass(frozen=True)
class DashboardMetricReference:
    source_engine: str
    metric_label_tr: str
    value_display: str
    reliability_label_tr: "str | None"


@dataclass(frozen=True)
class DashboardAlertReference:
    source_engine: str
    severity_level: str
    label_tr: str
    recommendation_code: "str | None"


@dataclass(frozen=True)
class DashboardWidget:
    widget_code: str
    widget_type: ReportBlockType
    metric_reference: "DashboardMetricReference | None"
    alert_reference: "DashboardAlertReference | None"
    source_field_path: str


@dataclass(frozen=True)
class DashboardSnapshot:
    dashboard_type: DashboardType
    widgets: "tuple[DashboardWidget, ...]"
    company_metadata: ReportCompanyMetadata
    source_confidence_inventory: "tuple[SourceConfidenceEntry, ...]"
    source_coverage_inventory: "tuple[SourceCoverageEntry, ...]"
    engines_used: "tuple[str, ...]"
    disclaimer_blocks: "tuple[ReportDisclaimerBlock, ...]"
    warnings: "tuple[dict[str, Any], ...]"
    decision_support_only: bool
    legal_review_status: LegalReviewStatus
    confidentiality_level: ConfidentialityLevel
    external_distribution_allowed: bool
    report_id: "str | None"
    generated_at: "str | None"
    dashboard_schema_version: str
    dashboard_model_version: str
    health_score_schema_version: str
    credit_score_schema_version: str
    recommendation_schema_version: str
