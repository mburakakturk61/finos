"""
Milestone 4.4 -- Render Contract (render-neutral) veri modeli. Tasarım
dokümanı Bölüm 3 -- `ReportType`'tan TAMAMEN AYRI (Madde 10, KİLİTLİ).
Gerçek PDF/DOCX/HTML üretimi bu modülün KAPSAMI DIŞINDADIR.
"""

from dataclasses import dataclass
import enum
from typing import Any

from app.engines.common.report_types import ReportBlockType, ReportSectionCode, ReportType


RENDER_CONTRACT_SCHEMA_VERSION = "1.0.0"


class RenderMedium(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"


class TableOverflowRiskLevel(str, enum.Enum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"


class PageBreakPreferenceValue(str, enum.Enum):
    PAGE_BREAK_BEFORE = "page_break_before"
    AVOID_BREAK_INSIDE = "avoid_break_inside"
    NONE = "none"


@dataclass(frozen=True)
class RenderContract:
    render_medium: RenderMedium
    supported_block_types: "tuple[ReportBlockType, ...]"
    supports_landscape: bool
    supports_page_break_hints: bool
    supports_chart_placeholders: bool
    max_table_columns_before_overflow_risk: "int | None"
    render_contract_schema_version: str = RENDER_CONTRACT_SCHEMA_VERSION


@dataclass(frozen=True)
class SectionLayoutCapability:
    section_code: ReportSectionCode
    supports_full_width_table: bool
    supports_multi_column: bool
    notes_tr: "str | None"


@dataclass(frozen=True)
class TableOverflowRiskFlag:
    section_code: ReportSectionCode
    risk_level: TableOverflowRiskLevel
    column_count: "int | None"
    reason_tr: "str | None"


@dataclass(frozen=True)
class PageBreakPreference:
    section_code: ReportSectionCode
    preference: PageBreakPreferenceValue


@dataclass(frozen=True)
class ChartPlaceholderCapability:
    section_code: ReportSectionCode
    chart_placeholder_supported: bool
    placeholder_type: "str | None"


@dataclass(frozen=True)
class RenderMetadata:
    render_contract_schema_version: str
    target_render_medium: RenderMedium
    total_sections: int
    report_type_previewed: ReportType
    generated_at: "str | None"


@dataclass(frozen=True)
class RenderContractPreview:
    section_render_order: "tuple[ReportSectionCode, ...]"
    layout_capability_matrix: "tuple[SectionLayoutCapability, ...]"
    table_overflow_risk_flags: "tuple[TableOverflowRiskFlag, ...]"
    page_break_preferences: "tuple[PageBreakPreference, ...]"
    landscape_required_section_codes: "tuple[ReportSectionCode, ...]"
    chart_placeholder_capability: "tuple[ChartPlaceholderCapability, ...]"
    unsupported_content_warnings: "tuple[dict[str, Any], ...]"
    render_metadata: RenderMetadata
