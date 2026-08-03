"""Anti-corruption mapping between Application v2 and Orchestrator V3."""

from __future__ import annotations

import hashlib
import json

from app.analysis_application.mapping import _canonical_node, _facts
from app.analysis_application.contracts import FinancialStatementKind
from app.engines.analysis_orchestrator.registry import ENGINE_DEPENDENCY_REGISTRY as LEGACY_REGISTRY
from app.engines.analysis_orchestrator_v3.registry import ENGINE_DEPENDENCY_REGISTRY_V3
from app.engines.analysis_orchestrator_v3.types import (
    EngineRawInputsV3,
    OrchestrationEngineCodeV3,
    OrchestrationJsonObjectV3,
    OrchestrationRunOptionsV3,
    OrchestrationRunRequestV3,
    PreviousExecutionSnapshotV3,
)
from app.engines.cash_flow.contracts import CashFlowPreResolvedContext
from app.engines.common.dashboard_types import DashboardType
from app.engines.common.render_contract_types import RenderContract, RenderMedium
from app.engines.common.report_types import ReportBlockType, ReportCompanyMetadata, ReportSectionCode, ReportType

from .contracts import (
    ApplicationEngineCodeV2,
    FinancialSourceIntentDTOV2,
    ResumeAnalysisCommandV2,
    RetryAnalysisCommandV2,
    StartAnalysisCommandV2,
)

ExecutionCommandV2 = StartAnalysisCommandV2 | ResumeAnalysisCommandV2 | RetryAnalysisCommandV2


def application_command_digest_v2(command: ExecutionCommandV2) -> str:
    if type(command) not in {StartAnalysisCommandV2, ResumeAnalysisCommandV2, RetryAnalysisCommandV2}:
        raise TypeError("v2 digest accepts exact v2 execution commands")
    payload = json.dumps(
        _canonical_node(command), sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(b"application/command/v2\0" + payload).hexdigest()


def _object(value) -> OrchestrationJsonObjectV3 | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise TypeError("V3 JSON input must be a dict")
    items = []
    for key in sorted(value):
        item = value[key]
        if type(item) is dict:
            item = _object(item)
        elif type(item) in {list, tuple}:
            item = tuple(_object(x) if type(x) is dict else x for x in item)
        items.append((key, item))
    return OrchestrationJsonObjectV3(tuple(items))


def _required(requested: tuple[OrchestrationEngineCodeV3, ...]) -> set[OrchestrationEngineCodeV3]:
    result = set(requested)
    changed = True
    while changed:
        changed = False
        for code in tuple(result):
            dependency = ENGINE_DEPENDENCY_REGISTRY_V3[code].dependency
            for item in dependency.all_of + dependency.any_of:
                if item not in result:
                    result.add(item)
                    changed = True
    return result


def validate_financial_intent_coverage_v2(
    requested: tuple[OrchestrationEngineCodeV3, ...],
    intents: tuple[FinancialSourceIntentDTOV2, ...],
) -> None:
    financial = {
        ApplicationEngineCodeV2.FS_BALANCE_SHEET,
        ApplicationEngineCodeV2.FS_INCOME_STATEMENT,
        ApplicationEngineCodeV2.RATIO,
    }
    expected = {ApplicationEngineCodeV2(code.value) for code in _required(requested)} & financial
    supplied = {item.engine_code for item in intents}
    if len(supplied) != len(intents) or supplied != expected:
        raise ValueError("V3 dependency closure requires exact financial source intents")
    if OrchestrationEngineCodeV3.CASH_FLOW in requested:
        if any(binding.source_engine_code is not None for intent in intents for binding in intent.source_bindings if intent.engine_code in {
            ApplicationEngineCodeV2.FS_BALANCE_SHEET, ApplicationEngineCodeV2.FS_INCOME_STATEMENT,
        }):
            raise ValueError("Cash Flow preflight requires authoritative pre-resolvable BS/IS sources")
    if any(
        binding.source_engine_code is ApplicationEngineCodeV2.CASH_FLOW
        for intent in intents for binding in intent.source_bindings
    ):
        raise ValueError("4.5G callers cannot assemble Cash Flow lineage into another engine")


def to_orchestration_request_v3(
    command: ExecutionCommandV2,
    *,
    cash_flow_pre_resolved_context: CashFlowPreResolvedContext | None,
    previous_execution_snapshot: PreviousExecutionSnapshotV3 | None = None,
) -> OrchestrationRunRequestV3:
    if type(command) not in {StartAnalysisCommandV2, ResumeAnalysisCommandV2, RetryAnalysisCommandV2}:
        raise TypeError("V3 mapping accepts exact Application-v2 commands")
    requested = tuple(OrchestrationEngineCodeV3(item.value) for item in command.requested_outputs)
    wants_cf = OrchestrationEngineCodeV3.CASH_FLOW in requested
    if wants_cf != (cash_flow_pre_resolved_context is not None):
        raise ValueError("trusted Cash Flow context must match requested outputs")
    validate_financial_intent_coverage_v2(requested, command.source_intents)
    prior = command.prior_period_projection
    balance_facts = _facts(prior.balance_sheet_facts) if prior else None
    income_facts = _facts(prior.income_statement_facts) if prior else None
    if prior and prior.balance_sheet_facts and prior.balance_sheet_facts.statement_kind is not FinancialStatementKind.BALANCE_SHEET:
        raise ValueError("prior balance-sheet fact kind mismatch")
    if prior and prior.income_statement_facts and prior.income_statement_facts.statement_kind is not FinancialStatementKind.INCOME_STATEMENT:
        raise ValueError("prior income-statement fact kind mismatch")
    company, report, dashboard, render = (
        command.company_metadata, command.report_request, command.dashboard_request, command.render_contract_request,
    )
    options = OrchestrationRunOptionsV3(
        industry_code=command.run_options.industry_code,
        company_size_bucket=command.run_options.company_size_bucket,
        tenant_id=command.run_options.engine_segmentation_tenant_id,
        report_type=ReportType(report.report_type.value) if report else None,
        dashboard_type=DashboardType(dashboard.dashboard_type.value) if dashboard else None,
        company_metadata=ReportCompanyMetadata(
            company_name=company.company_name,
            industry_label_tr=company.industry_label_tr,
            company_size_label_tr=company.company_size_label_tr,
            fiscal_year_label_tr=company.fiscal_year_label_tr,
            tax_id_masked=company.tax_id_masked,
        ) if company else None,
        reporting_period_label_tr=report.reporting_period_label_tr if report else command.run_options.reporting_period_label_tr,
        optional_sections=tuple(ReportSectionCode(item.value) for item in report.optional_section_codes) if report and report.optional_section_codes is not None else None,
        currency_display_policy=command.run_options.currency_display_policy,
        locale=command.run_options.locale,
        render_contract=RenderContract(
            render_medium=RenderMedium(render.render_medium.value),
            supported_block_types=tuple(ReportBlockType(item.value) for item in render.supported_block_types),
            supports_landscape=render.supports_landscape,
            supports_page_break_hints=render.supports_page_break_hints,
            supports_chart_placeholders=render.supports_chart_placeholders,
            max_table_columns_before_overflow_risk=render.max_table_columns_before_overflow_risk,
        ) if render else None,
    )
    return OrchestrationRunRequestV3(
        run_id=command.run_id,
        correlation_id=command.correlation_id,
        generated_at=command.generated_at.isoformat(),
        requested_outputs=requested,
        engine_inputs=EngineRawInputsV3(
            balance_sheet_content=command.inputs.balance_sheet_content,
            balance_sheet_filename=command.inputs.balance_sheet_filename,
            income_statement_content=command.inputs.income_statement_content,
            income_statement_filename=command.inputs.income_statement_filename,
            trial_balance_result=_object(command.inputs.trial_balance_result),
            prior_period_balance_sheet_facts=balance_facts,
            prior_period_income_statement_facts=income_facts,
            prior_period_balance_sheet_result=_object(prior.balance_sheet_result if prior else None),
            prior_period_income_statement_result=_object(prior.income_statement_result if prior else None),
            period_start_date=command.inputs.period_start_date,
            period_end_date=command.inputs.period_end_date,
            period_months_covered=command.inputs.period_months_covered,
            cash_flow_pre_resolved_context=cash_flow_pre_resolved_context,
        ),
        run_options=options,
        previous_execution_snapshot=previous_execution_snapshot,
    )


def assert_legacy_graph_unchanged() -> None:
    """Import-time regression guard: V3 construction never mutates V2 registry."""
    if len(LEGACY_REGISTRY) != 10 or any(code.value == "cash_flow" for code in LEGACY_REGISTRY):
        raise RuntimeError("legacy orchestrator graph changed")


assert_legacy_graph_unchanged()
