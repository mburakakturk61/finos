from __future__ import annotations

import ast
from dataclasses import fields
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from app.analysis_application.contracts import ApplicationEngineCode, PayloadOwnerType
from app.analysis_application_v2.contracts import (
    APPLICATION_CASH_FLOW_ACCOUNT_ROLE_MEMBER_PAIRS_V2,
    APPLICATION_CASH_FLOW_DERIVATION_CODE_MEMBER_PAIRS_V2,
    APPLICATION_CASH_FLOW_ERROR_CODE_MEMBER_PAIRS_V2,
    APPLICATION_CASH_FLOW_LINE_CODE_MEMBER_PAIRS_V2,
    APPLICATION_CASH_FLOW_SOURCE_ROLE_MEMBER_PAIRS_V2,
    APPLICATION_CASH_FLOW_WARNING_CODE_MEMBER_PAIRS_V2,
    AnalysisErrorDTOV2,
    ApplicationCashFlowAccountRoleV2,
    ApplicationCashFlowDerivationCodeV2,
    ApplicationCashFlowErrorCodeV2,
    ApplicationCashFlowLineCodeV2,
    ApplicationCashFlowSourceRoleV2,
    ApplicationCashFlowWarningCodeV2,
    ApplicationEngineCodeV2,
    ApplicationOutcomeV2,
    ApplicationPayloadKindV2,
    ApplicationPayloadReferenceDTOV2,
    CashFlowProjectionDTOV2,
    CashFlowRequestDTOV2,
    ApplicationCashFlowMethodV2,
    ApplicationCashFlowPresentationProfileV2,
    CancelAnalysisCommandV2,
    GetAnalysisResultQueryV2,
    GetAnalysisStatusQueryV2,
    GetExecutionDetailQueryV2,
    ListAnalysisHistoryQueryV2,
    ResumeAnalysisCommandV2,
    RetryAnalysisCommandV2,
    StartAnalysisCommandV2,
    FinancialSourceIntentDTOV2,
    FinancialSourceReferenceDTOV2,
    ApplicationFinancialSourceModeV2,
    ApplicationFinancialSourceRoleV2,
)
from app.analysis_application_v2.mapping import validate_financial_intent_coverage_v2
from app.analysis_application_v2.projection import project_cash_flow_result_v2
from app.analysis_application_v2.ports import (
    ComparablePeriodResolution,
    ComparablePeriodResolutionStatus,
    ResolvedCashFlowPreRunSources,
    VerifiedTenantScopeV3,
)
from app.analysis_application_v2.resolution import resolve_cash_flow_pre_run_context_v2
from app.engines.cash_flow.types import (
    CashFlowAccountRole,
    CashFlowDerivationCode,
    CashFlowErrorCode,
    CashFlowLineCode,
    CashFlowSourceRole,
    CashFlowWarningCode,
)
from app.orchestration_persistence_v3.types import (
    RESULT_OWNERSHIP_REGISTRY_V3,
    ResultOwnerV3,
)
from app.engines.analysis_orchestrator_v3.types import OrchestrationEngineCodeV3

from test_cash_flow_contracts_unit import COMPANY_ID, CURRENT_ID, PRIOR_ID, TENANT_ID, OWNER_ID, _descriptor, _result


def _pairs(enum_type):
    return tuple((item.name, item.value) for item in enum_type)


@pytest.mark.parametrize(("application_pairs", "application_enum", "engine_enum"), (
    (APPLICATION_CASH_FLOW_LINE_CODE_MEMBER_PAIRS_V2, ApplicationCashFlowLineCodeV2, CashFlowLineCode),
    (APPLICATION_CASH_FLOW_WARNING_CODE_MEMBER_PAIRS_V2, ApplicationCashFlowWarningCodeV2, CashFlowWarningCode),
    (APPLICATION_CASH_FLOW_ERROR_CODE_MEMBER_PAIRS_V2, ApplicationCashFlowErrorCodeV2, CashFlowErrorCode),
    (APPLICATION_CASH_FLOW_ACCOUNT_ROLE_MEMBER_PAIRS_V2, ApplicationCashFlowAccountRoleV2, CashFlowAccountRole),
    (APPLICATION_CASH_FLOW_SOURCE_ROLE_MEMBER_PAIRS_V2, ApplicationCashFlowSourceRoleV2, CashFlowSourceRole),
    (APPLICATION_CASH_FLOW_DERIVATION_CODE_MEMBER_PAIRS_V2, ApplicationCashFlowDerivationCodeV2, CashFlowDerivationCode),
))
def test_application_cash_flow_enum_manifests_are_literal_exact_and_type_isolated(application_pairs, application_enum, engine_enum):
    assert application_pairs == _pairs(engine_enum)
    assert _pairs(application_enum) == _pairs(engine_enum)
    assert application_enum is not engine_enum


def test_application_and_orchestrator_v3_engine_manifests_match_without_mutating_legacy():
    assert _pairs(ApplicationEngineCodeV2) == _pairs(OrchestrationEngineCodeV3)
    assert "cash_flow" not in {item.value for item in ApplicationEngineCode}


def test_v2_command_and_query_contracts_have_independent_exact_field_lists():
    common_execution = (
        "run_id", "correlation_id", "generated_at", "scope", "audit_context",
        "authorization_context_reference", "requested_outputs", "inputs", "run_options",
        "source_intents", "cash_flow_request", "prior_period_projection", "company_metadata",
        "report_request", "dashboard_request", "render_contract_request", "application_contract_version",
    )
    assert tuple(x.name for x in fields(StartAnalysisCommandV2)) == common_execution
    assert tuple(x.name for x in fields(ResumeAnalysisCommandV2)) == common_execution
    assert tuple(x.name for x in fields(RetryAnalysisCommandV2)) == common_execution
    assert tuple(x.name for x in fields(CancelAnalysisCommandV2)) == (
        "run_id", "correlation_id", "generated_at", "scope", "audit_context",
        "authorization_context_reference", "application_contract_version",
    )
    assert tuple(x.name for x in fields(GetAnalysisStatusQueryV2)) == tuple(x.name for x in fields(CancelAnalysisCommandV2))
    assert "include_payloads" in {x.name for x in fields(GetAnalysisResultQueryV2)}
    assert {"engine_code", "include_payload"} <= {x.name for x in fields(GetExecutionDetailQueryV2)}
    assert tuple(x.name for x in fields(ListAnalysisHistoryQueryV2)) == (
        "correlation_id", "generated_at", "scope", "audit_context",
        "authorization_context_reference", "cursor", "limit", "application_contract_version",
    )


def test_cash_flow_projection_is_field_by_field_and_preserves_decimal_evidence_and_lineage():
    source = _result()
    projection = project_cash_flow_result_v2(source, same_run_owner=lambda _: OWNER_ID)
    assert type(projection) is CashFlowProjectionDTOV2
    assert projection.opening_cash_and_cash_equivalents == source.opening_cash_and_cash_equivalents
    assert type(projection.opening_cash_and_cash_equivalents) is type(source.opening_cash_and_cash_equivalents)
    assert tuple(x.line_code.value for x in projection.line_items) == tuple(x.line_code.value for x in source.line_items)
    assert projection.evidence[0].financial_analysis_result_id == OWNER_ID
    assert projection.source_lineage_references[0].canonical_digest == source.source_lineage_references[0].canonical_digest
    assert projection.errors == ()


def test_financial_cash_flow_payload_reference_has_no_artifact_serializer_version():
    reference = ApplicationPayloadReferenceDTOV2(
        owner_type=PayloadOwnerType.FINANCIAL_ANALYSIS_RESULT,
        result_kind="CashFlowResult",
        canonical_digest="a" * 64,
        financial_analysis_result_id=OWNER_ID,
        artifact_id=None,
        artifact_serializer_schema_version=None,
    )
    assert reference.artifact_serializer_schema_version is None
    with pytest.raises(ValueError):
        ApplicationPayloadReferenceDTOV2(
            PayloadOwnerType.FINANCIAL_ANALYSIS_RESULT, "CashFlowResult", "a" * 64,
            OWNER_ID, None, "1.0.0",
        )


def test_v3_owner_registry_is_exact_four_financial_seven_artifact_in_declaration_order():
    assert tuple(RESULT_OWNERSHIP_REGISTRY_V3) == tuple(OrchestrationEngineCodeV3)
    assert sum(x.owner is ResultOwnerV3.FINANCIAL_ANALYSIS_RESULT for x in RESULT_OWNERSHIP_REGISTRY_V3.values()) == 4
    assert sum(x.owner is ResultOwnerV3.ORCHESTRATION_ARTIFACT for x in RESULT_OWNERSHIP_REGISTRY_V3.values()) == 7
    assert RESULT_OWNERSHIP_REGISTRY_V3[OrchestrationEngineCodeV3.CASH_FLOW].analysis_type.value == "cash_flow"


def test_application_outcome_v2_is_discriminated():
    with pytest.raises(ValueError):
        ApplicationOutcomeV2(True, None, None, (), "corr")
    with pytest.raises(ValueError):
        ApplicationOutcomeV2(False, object(), None, (), "corr")


def test_application_v2_core_has_no_fastapi_pydantic_or_sqlalchemy_imports():
    root = Path(__file__).parents[1] / "app" / "analysis_application_v2"
    forbidden = {"fastapi", "pydantic", "sqlalchemy"}
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text())
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not imports & forbidden


def test_trusted_pre_run_resolution_uses_authoritative_period_and_source_ports():
    current = _descriptor(CURRENT_ID, date(2025, 2, 1), date(2025, 2, 28))
    prior = _descriptor(PRIOR_ID, date(2025, 1, 1), date(2025, 1, 31))
    calls = []

    class Periods:
        def resolve_exact_prior_period(self, **kwargs):
            calls.append(("period", kwargs))
            return ComparablePeriodResolution(
                ComparablePeriodResolutionStatus.EXACT_MATCH,
                current, prior, "a" * 64, 1,
            )

    class Sources:
        def resolve_pre_run_sources(self, **kwargs):
            calls.append(("sources", kwargs))
            return ResolvedCashFlowPreRunSources(
                None, None, None, (), (), "b" * 64, "c" * 64, False, False,
            )

    request = CashFlowRequestDTOV2(
        ApplicationCashFlowMethodV2.INDIRECT,
        CURRENT_ID,
        PRIOR_ID,
        ApplicationCashFlowPresentationProfileV2.MANAGEMENT_V1,
        "tr_tdhp_accrual/1.0.0",
        "1.0.0",
        "1.0.0",
        "1.0.0",
    )
    context = resolve_cash_flow_pre_run_context_v2(
        request,
        VerifiedTenantScopeV3("tenant-key", TENANT_ID, COMPANY_ID, "subject"),
        comparable_periods=Periods(),
        cash_flow_sources=Sources(),
    )
    assert context.current_period is current and context.prior_period is prior
    assert [item[0] for item in calls] == ["period", "sources"]
    assert calls[1][1]["prior_period_id"] == PRIOR_ID


def test_prior_period_assertion_mismatch_is_fail_closed_before_source_resolution():
    current = _descriptor(CURRENT_ID, date(2025, 2, 1), date(2025, 2, 28))
    prior = _descriptor(PRIOR_ID, date(2025, 1, 1), date(2025, 1, 31))

    class Periods:
        def resolve_exact_prior_period(self, **kwargs):
            return ComparablePeriodResolution(ComparablePeriodResolutionStatus.EXACT_MATCH, current, prior, "a" * 64, 1)

    class Sources:
        def resolve_pre_run_sources(self, **kwargs):
            raise AssertionError("source resolver must not run")

    request = CashFlowRequestDTOV2(
        ApplicationCashFlowMethodV2.INDIRECT, CURRENT_ID,
        UUID("90000000-0000-0000-0000-000000000001"),
        ApplicationCashFlowPresentationProfileV2.MANAGEMENT_V1,
        "tr_tdhp_accrual/1.0.0", "1.0.0", "1.0.0", "1.0.0",
    )
    with pytest.raises(ValueError):
        resolve_cash_flow_pre_run_context_v2(
            request, VerifiedTenantScopeV3("tenant-key", TENANT_ID, COMPANY_ID, "subject"),
            comparable_periods=Periods(), cash_flow_sources=Sources(),
        )


def test_45g_rejects_caller_assembled_cash_flow_to_ratio_lineage():
    intents = (
        FinancialSourceIntentDTOV2(
            ApplicationEngineCodeV2.FS_BALANCE_SHEET, COMPANY_ID, CURRENT_ID, None, (),
            ApplicationFinancialSourceModeV2.MULTI_SOURCE_DERIVED, False, None, {}, None,
        ),
        FinancialSourceIntentDTOV2(
            ApplicationEngineCodeV2.FS_INCOME_STATEMENT, COMPANY_ID, CURRENT_ID, None, (),
            ApplicationFinancialSourceModeV2.MULTI_SOURCE_DERIVED, False, None, {}, None,
        ),
        FinancialSourceIntentDTOV2(
            ApplicationEngineCodeV2.RATIO, COMPANY_ID, CURRENT_ID, None,
            (FinancialSourceReferenceDTOV2(
                ApplicationFinancialSourceRoleV2.SUPPORTING_ANALYSIS,
                None, None, ApplicationEngineCodeV2.CASH_FLOW,
            ),),
            ApplicationFinancialSourceModeV2.MULTI_SOURCE_DERIVED, False, None, {}, None,
        ),
    )
    with pytest.raises(ValueError):
        validate_financial_intent_coverage_v2(
            (OrchestrationEngineCodeV3.CASH_FLOW, OrchestrationEngineCodeV3.RATIO), intents,
        )
