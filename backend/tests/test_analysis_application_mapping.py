from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import uuid
import time

from app.analysis_application.contracts import (
    AnalysisInputsDTO,
    AnalysisRunOptionsDTO,
    ApplicationAuditContextDTO,
    ApplicationDashboardType,
    ApplicationEngineCode,
    ApplicationOperationKind,
    ApplicationOriginalOperation,
    ApplicationRenderMedium,
    ApplicationReportBlockType,
    ApplicationReportSectionCode,
    ApplicationReportType,
    ApplicationScopeDTO,
    CompanyMetadataDTO,
    DashboardRequestDTO,
    FinancialStatementKind,
    PriorPeriodFactsDTO,
    PriorPeriodProjectionDTO,
    RenderContractRequestDTO,
    ReportRequestDTO,
    StartAnalysisCommand,
    BALANCE_SHEET_FACT_KEYS,
    FinancialSourceIntentDTO, FinancialSourceMode,
    FinancialSourceReferenceDTO, FinancialSourceRole,
)
from app.analysis_application.mapping import (
    application_command_digest,
    project_engine_result,
    to_orchestration_request,
)
from app.engines.analysis_orchestrator.types import EngineCode, EngineResultEnvelope
from app.engines.common.canonical_facts import BalanceSheetFacts
from app.engines.common.dashboard_types import DashboardType
from app.engines.common.render_contract_types import RenderMedium
from app.engines.common.report_types import ReportBlockType, ReportSectionCode, ReportType


def _command() -> StartAnalysisCommand:
    scope = ApplicationScopeDTO(
        uuid.UUID("00000000-0000-0000-0000-000000000001"),
        uuid.UUID("00000000-0000-0000-0000-000000000002"),
        "tenant-a", ApplicationOperationKind.START, ApplicationOriginalOperation.START,
    )
    prior = PriorPeriodFactsDTO(
        FinancialStatementKind.BALANCE_SHEET,
        {key: (Decimal("10.00") if key == "total_assets" else None) for key in BALANCE_SHEET_FACT_KEYS},
    )
    intents = (
        FinancialSourceIntentDTO(ApplicationEngineCode.FS_BALANCE_SHEET, scope.company_id, scope.financial_period_id, None, (), FinancialSourceMode.MULTI_SOURCE_DERIVED, False, None, {}),
        FinancialSourceIntentDTO(ApplicationEngineCode.FS_INCOME_STATEMENT, scope.company_id, scope.financial_period_id, None, (), FinancialSourceMode.MULTI_SOURCE_DERIVED, False, None, {}),
        FinancialSourceIntentDTO(ApplicationEngineCode.RATIO, scope.company_id, scope.financial_period_id, None, (
            FinancialSourceReferenceDTO(FinancialSourceRole.PRIMARY_ANALYSIS, source_engine_code=ApplicationEngineCode.FS_BALANCE_SHEET),
            FinancialSourceReferenceDTO(FinancialSourceRole.SUPPORTING_ANALYSIS, source_engine_code=ApplicationEngineCode.FS_INCOME_STATEMENT),
        ), FinancialSourceMode.MULTI_SOURCE_DERIVED, False, None, {}),
    )
    return StartAnalysisCommand(
        "run-1", "corr-1", datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        scope, ApplicationAuditContextDTO("actor", "service", "test", "analysis"),
        "auth-ref", (ApplicationEngineCode.EXECUTIVE_REPORT,), AnalysisInputsDTO(),
        AnalysisRunOptionsDTO(locale="tr-TR"), intents, PriorPeriodProjectionDTO(balance_sheet_facts=prior),
        CompanyMetadataDTO("ACME"),
        ReportRequestDTO(ApplicationReportType.CFO_EXECUTIVE_REPORT, (ApplicationReportSectionCode.SEC_COVER_PAGE,)),
        DashboardRequestDTO(ApplicationDashboardType.EXECUTIVE_DASHBOARD),
        RenderContractRequestDTO(ApplicationRenderMedium.PDF, (ApplicationReportBlockType.TABLE,), True, True, False, 8),
    )


def test_5_0a_mapping_is_explicit_and_typed():
    request = to_orchestration_request(_command())
    assert request.requested_outputs == (EngineCode.EXECUTIVE_REPORT,)
    assert isinstance(request.engine_inputs.prior_period_balance_sheet_facts, BalanceSheetFacts)
    assert request.engine_inputs.prior_period_balance_sheet_facts.total_assets == Decimal("10.00")
    assert request.run_options.report_type is ReportType.CFO_EXECUTIVE_REPORT
    assert request.run_options.optional_sections == (ReportSectionCode.SEC_COVER_PAGE,)
    assert request.run_options.dashboard_type is DashboardType.EXECUTIVE_DASHBOARD
    assert request.run_options.render_contract.render_medium is RenderMedium.PDF
    assert request.run_options.render_contract.supported_block_types == (ReportBlockType.TABLE,)


def test_application_command_digest_is_deterministic_and_payload_sensitive():
    first = _command()
    assert application_command_digest(first) == application_command_digest(first)
    changed = dataclass_replace(first, inputs=AnalysisInputsDTO(balance_sheet_content=b"changed"))
    assert application_command_digest(first) != application_command_digest(changed)


@dataclass(frozen=True)
class _EnginePayload:
    amount: Decimal
    labels: list[str]


def test_projection_uses_engine_result_envelope_result_and_never_leaks_dataclass():
    envelope = EngineResultEnvelope(EngineCode.RATIO, "payload", _EnginePayload(Decimal("1.25"), ["a", "b"]))
    projected = project_engine_result(envelope)
    assert projected == {"amount": Decimal("1.25"), "labels": ("a", "b")}
    assert not isinstance(projected, _EnginePayload)


def test_application_validation_mapping_p95_is_below_25_ms():
    command = _command()
    samples = []
    for _ in range(100):
        started = time.perf_counter()
        to_orchestration_request(command)
        application_command_digest(command)
        samples.append((time.perf_counter() - started) * 1000)
    assert sorted(samples)[94] < 25


def dataclass_replace(value, **changes):
    from dataclasses import replace
    return replace(value, **changes)
