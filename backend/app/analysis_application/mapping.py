"""Explicit anti-corruption mapping between 5.0C DTOs and frozen 5.0A contracts."""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal

from app.analysis_application.contracts import (
    ApplicationJsonValue,
    ApplicationEngineCode,
    ApplicationReportBlockType,
    FinancialStatementKind,
    PriorPeriodFactsDTO,
    StartAnalysisCommand,
    ResumeAnalysisCommand,
    RetryAnalysisCommand,
)
from app.engines.analysis_orchestrator.types import (
    EngineCode,
    EngineRawInputs,
    EngineResultEnvelope,
    OrchestrationRunOptions,
    OrchestrationRunRequest,
    PreviousExecutionSnapshot,
)
from app.engines.analysis_orchestrator.registry import ENGINE_DEPENDENCY_REGISTRY
from app.engines.common.canonical_facts import BalanceSheetFacts, IncomeStatementFacts
from app.engines.common.dashboard_types import DashboardType
from app.engines.common.render_contract_types import RenderContract, RenderMedium
from app.engines.common.report_types import (
    ReportBlockType,
    ReportCompanyMetadata,
    ReportSectionCode,
    ReportType,
)

ExecutionCommand = StartAnalysisCommand | ResumeAnalysisCommand | RetryAnalysisCommand


def _canonical_node(value: object) -> object:
    """Return a JSON-encodable, type-tagged representation for command digests."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return {"$application_type": "decimal", "value": format(normalized, "f")}
    if isinstance(value, float):
        if not (float("-inf") < value < float("inf")):
            raise ValueError("Non-finite floats are not allowed.")
        return {"$application_type": "float", "value": value.hex()}
    if isinstance(value, bytes):
        return {
            "$application_type": "bytes_sha256",
            "length": len(value),
            "value": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, enum.Enum):
        return {"$application_type": "enum", "value": value.value}
    if isinstance(value, uuid.UUID):
        return {"$application_type": "uuid", "value": str(value)}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Datetime values must be timezone-aware.")
        return {"$application_type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"$application_type": "date", "value": value.isoformat()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical_node(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, tuple):
        return {"$application_type": "tuple", "value": [_canonical_node(item) for item in value]}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Application map keys must be strings.")
        return {key: _canonical_node(value[key]) for key in sorted(value)}
    raise ValueError(f"Unsupported command digest value type: {type(value).__name__}")


def application_command_digest(command: ExecutionCommand) -> str:
    payload = json.dumps(
        _canonical_node(command), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _facts(dto: PriorPeriodFactsDTO | None) -> BalanceSheetFacts | IncomeStatementFacts | None:
    if dto is None:
        return None
    if dto.statement_kind is FinancialStatementKind.BALANCE_SHEET:
        return BalanceSheetFacts(**dto.values)
    return IncomeStatementFacts(**dto.values)


def to_orchestration_request(
    command: ExecutionCommand,
    previous_execution_snapshot: PreviousExecutionSnapshot | None = None,
) -> OrchestrationRunRequest:
    requested = tuple(EngineCode(item.value) for item in command.requested_outputs)
    required = set(requested)
    changed = True
    while changed:
        changed = False
        for code in tuple(required):
            dependency = ENGINE_DEPENDENCY_REGISTRY[code].dependency
            for dependency_code in dependency.all_of + dependency.any_of:
                if dependency_code not in required:
                    required.add(dependency_code)
                    changed = True
    financial_codes = {
        ApplicationEngineCode.FS_BALANCE_SHEET,
        ApplicationEngineCode.FS_INCOME_STATEMENT,
        ApplicationEngineCode.RATIO,
    }
    expected_intents = {ApplicationEngineCode(code.value) for code in required} & financial_codes
    if {item.engine_code for item in command.source_intents} != expected_intents:
        raise ValueError("Dependency-closure financial executions require exact source intents.")
    prior = command.prior_period_projection
    balance_facts = _facts(prior.balance_sheet_facts) if prior else None
    income_facts = _facts(prior.income_statement_facts) if prior else None
    if balance_facts is not None and not isinstance(balance_facts, BalanceSheetFacts):
        raise ValueError("Balance-sheet prior facts have the wrong statement kind.")
    if income_facts is not None and not isinstance(income_facts, IncomeStatementFacts):
        raise ValueError("Income-statement prior facts have the wrong statement kind.")

    company = command.company_metadata
    report = command.report_request
    dashboard = command.dashboard_request
    render = command.render_contract_request
    options = OrchestrationRunOptions(
        industry_code=command.run_options.industry_code,
        company_size_bucket=command.run_options.company_size_bucket,
        tenant_id=command.run_options.engine_segmentation_tenant_id,
        report_type=ReportType(report.report_type.value) if report else None,
        dashboard_type=DashboardType(dashboard.dashboard_type.value) if dashboard else None,
        company_metadata=(
            ReportCompanyMetadata(
                company_name=company.company_name,
                industry_label_tr=company.industry_label_tr,
                company_size_label_tr=company.company_size_label_tr,
                fiscal_year_label_tr=company.fiscal_year_label_tr,
                tax_id_masked=company.tax_id_masked,
            )
            if company else None
        ),
        reporting_period_label_tr=(report.reporting_period_label_tr if report else command.run_options.reporting_period_label_tr),
        optional_sections=(
            tuple(ReportSectionCode(item.value) for item in report.optional_section_codes)
            if report and report.optional_section_codes is not None
            else None
        ),
        currency_display_policy=command.run_options.currency_display_policy,
        locale=command.run_options.locale,
        render_contract=(
            RenderContract(
                render_medium=RenderMedium(render.render_medium.value),
                supported_block_types=tuple(ReportBlockType(item.value) for item in render.supported_block_types),
                supports_landscape=render.supports_landscape,
                supports_page_break_hints=render.supports_page_break_hints,
                supports_chart_placeholders=render.supports_chart_placeholders,
                max_table_columns_before_overflow_risk=render.max_table_columns_before_overflow_risk,
            )
            if render else None
        ),
    )
    return OrchestrationRunRequest(
        run_id=command.run_id,
        correlation_id=command.correlation_id,
        generated_at=command.generated_at.isoformat(),
        requested_outputs=requested,
        engine_inputs=EngineRawInputs(
            balance_sheet_content=command.inputs.balance_sheet_content,
            balance_sheet_filename=command.inputs.balance_sheet_filename,
            income_statement_content=command.inputs.income_statement_content,
            income_statement_filename=command.inputs.income_statement_filename,
            trial_balance_result=command.inputs.trial_balance_result,
            prior_period_balance_sheet_facts=balance_facts,
            prior_period_income_statement_facts=income_facts,
            prior_period_balance_sheet_result=(prior.balance_sheet_result if prior else None),
            prior_period_income_statement_result=(prior.income_statement_result if prior else None),
            period_start_date=command.inputs.period_start_date,
            period_end_date=command.inputs.period_end_date,
            period_months_covered=command.inputs.period_months_covered,
        ),
        run_options=options,
        previous_execution_snapshot=previous_execution_snapshot,
    )


def project_engine_result(envelope: EngineResultEnvelope) -> ApplicationJsonValue:
    """Project only ``EngineResultEnvelope.result``; never expose engine dataclasses."""
    return _project_value(envelope.result)


def _project_value(value: object) -> ApplicationJsonValue:
    if value is None or isinstance(value, (bool, str, int, Decimal)):
        return value
    if isinstance(value, float):
        if not (float("-inf") < value < float("inf")):
            raise ValueError("Non-finite engine result value.")
        return value
    if isinstance(value, enum.Enum):
        return _project_value(value.value)
    if isinstance(value, (datetime, date)):
        tag = "datetime" if isinstance(value, datetime) else "date"
        return {"$application_type": tag, "value": value.isoformat()}
    if isinstance(value, uuid.UUID):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _project_value(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, (tuple, list)):
        return tuple(_project_value(item) for item in value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Engine result map keys must be strings.")
        return {key: _project_value(value[key]) for key in sorted(value)}
    raise ValueError(f"Unsupported engine result value type: {type(value).__name__}")
