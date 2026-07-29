"""
Milestone 4.4 -- Render Contract Preview: `preview_render_contract()`.
Render Preview Pipeline -- KESİN 7 adım (tasarım dokümanı Bölüm 17.3 /
kullanıcının implementasyon-onay mesajı madde 16).

`RENDER_CONTRACT_PRESENTATION_ONLY`: finansal içerik ÜRETMEZ, mevcut
`ExecutiveReportResult`'ı YALNIZCA render-edilebilirlik (capability)
metadata'sına dönüştürür -- yeni veri noktası EKLEMEZ.
"""

from app.engines.common.render_contract_types import (
    RENDER_CONTRACT_SCHEMA_VERSION,
    ChartPlaceholderCapability,
    PageBreakPreference,
    PageBreakPreferenceValue,
    RenderContract,
    RenderContractPreview,
    RenderMetadata,
    SectionLayoutCapability,
    TableOverflowRiskFlag,
    TableOverflowRiskLevel,
)
from app.engines.common.report_types import ExecutiveReportResult, ReportBlockType


class InvalidReportResultError(ValueError):
    pass


def _table_column_count(section) -> "int | None":
    max_cols = None
    for block in section.content_blocks:
        if block.block_type == ReportBlockType.TABLE:
            cols = len(block.payload.get("columns") or [])
            max_cols = cols if max_cols is None else max(max_cols, cols)
    return max_cols


def _table_row_count_total(section) -> int:
    total = 0
    for block in section.content_blocks:
        if block.block_type == ReportBlockType.TABLE:
            total += len(block.payload.get("rows") or [])
    return total


def preview_render_contract(
    report_result: ExecutiveReportResult,
    render_contract: RenderContract,
) -> RenderContractPreview:
    # Adım 1: Existing report validation
    if not isinstance(report_result, ExecutiveReportResult):
        raise InvalidReportResultError("report_result bir ExecutiveReportResult OLMALI")

    # Adım 2: Render contract resolution
    if not render_contract.supported_block_types:
        raise InvalidReportResultError("render_contract.supported_block_types BOŞ olamaz")

    sections = report_result.sections

    # Adım 3: Capability metadata
    layout_capabilities = []
    overflow_flags = []
    chart_capabilities = []
    for section in sections:
        has_table = any(b.block_type == ReportBlockType.TABLE for b in section.content_blocks)
        kpi_count = sum(1 for b in section.content_blocks if b.block_type == ReportBlockType.KPI_CARD)
        layout_capabilities.append(SectionLayoutCapability(
            section_code=section.section_code,
            supports_full_width_table=has_table,
            supports_multi_column=kpi_count > 1,
            notes_tr=None,
        ))

        col_count = _table_column_count(section)
        if col_count is None:
            risk_level = TableOverflowRiskLevel.NONE
        elif render_contract.max_table_columns_before_overflow_risk is not None and col_count > render_contract.max_table_columns_before_overflow_risk:
            risk_level = TableOverflowRiskLevel.HIGH
        elif render_contract.max_table_columns_before_overflow_risk is not None and col_count > (render_contract.max_table_columns_before_overflow_risk * 0.7):
            risk_level = TableOverflowRiskLevel.LOW
        else:
            risk_level = TableOverflowRiskLevel.NONE
        overflow_flags.append(TableOverflowRiskFlag(
            section_code=section.section_code, risk_level=risk_level, column_count=col_count,
            reason_tr=(f"{col_count} sütunlu tablo, hedef ortamın önerilen sütun sınırını aşıyor." if risk_level == TableOverflowRiskLevel.HIGH else None),
        ))

        has_chart = any(b.block_type == ReportBlockType.CHART_DATA for b in section.content_blocks)
        chart_capabilities.append(ChartPlaceholderCapability(
            section_code=section.section_code,
            chart_placeholder_supported=bool(has_chart and render_contract.supports_chart_placeholders),
            placeholder_type=("chart_data" if (has_chart and render_contract.supports_chart_placeholders) else None),
        ))

    page_break_preferences = tuple(
        PageBreakPreference(
            section_code=section.section_code,
            preference=(
                PageBreakPreferenceValue.PAGE_BREAK_BEFORE if _table_row_count_total(section) > 10
                else PageBreakPreferenceValue.NONE
            ),
        )
        for section in sections
    )

    landscape_required = tuple(
        section.section_code for section, flag in zip(sections, overflow_flags)
        if flag.risk_level == TableOverflowRiskLevel.HIGH and render_contract.supports_landscape
    )

    # Adım 4: Unsupported-content warnings
    unsupported_warnings = []
    for section in sections:
        for block in section.content_blocks:
            if block.block_type not in render_contract.supported_block_types:
                unsupported_warnings.append({
                    "code": "UNSUPPORTED_BLOCK_TYPE",
                    "section_code": section.section_code.value,
                    "block_type": block.block_type.value,
                })

    # Adım 5: Stable ordering
    section_render_order = tuple(s.section_code for s in sections)

    render_metadata = RenderMetadata(
        render_contract_schema_version=RENDER_CONTRACT_SCHEMA_VERSION,
        target_render_medium=render_contract.render_medium,
        total_sections=len(sections),
        report_type_previewed=report_result.report_type,
        generated_at=None,
    )

    result = RenderContractPreview(
        section_render_order=section_render_order,
        layout_capability_matrix=tuple(layout_capabilities),
        table_overflow_risk_flags=tuple(overflow_flags),
        page_break_preferences=page_break_preferences,
        landscape_required_section_codes=landscape_required,
        chart_placeholder_capability=tuple(chart_capabilities),
        unsupported_content_warnings=tuple(unsupported_warnings),
        render_metadata=render_metadata,
    )

    # Adım 6: Presentation-only invariant kontrolü -- RENDER_CONTRACT_PRESENTATION_ONLY.
    # `report_result` frozen bir dataclass'tır (yapısal olarak immutable); bu fonksiyon
    # HİÇBİR alanına yazma YAPMAZ, yalnızca OKUR -- yeni finansal veri noktası EKLEMEZ,
    # yalnızca VAR OLAN section/block envanterinin render-kapasitesini YANSITIR.

    # Adım 7: RenderContractPreview
    return result
