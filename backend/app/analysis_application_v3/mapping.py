"""Application-v3 to V4 orchestration mapping."""

from app.engines.analysis_orchestrator_v3.types import OrchestrationJsonObjectV3
from app.engines.analysis_orchestrator_v4.types import (
    EngineRawInputsV4, OrchestrationEngineCodeV4, OrchestrationRunOptionsV4,
    OrchestrationRunRequestV4, PreviousExecutionSnapshotV4, TrendPreResolvedContextV1,
)

from .contracts import StartAnalysisCommandV3, ResumeAnalysisCommandV3, RetryAnalysisCommandV3


def _object(value):
    if value is None or type(value) is OrchestrationJsonObjectV3:
        return value
    if type(value) is not dict:
        raise TypeError("trial-balance application payload must be a mapping")
    return OrchestrationJsonObjectV3(tuple(
        (key, _object(item) if type(item) is dict else tuple(_object(child) if type(child) is dict else child for child in item) if type(item) is tuple else item)
        for key, item in sorted(value.items())
    ))


def to_orchestration_request_v4(
    command: StartAnalysisCommandV3 | ResumeAnalysisCommandV3 | RetryAnalysisCommandV3,
    *, trend_context: TrendPreResolvedContextV1 | None,
    cash_flow_context=None,
    previous_snapshot: PreviousExecutionSnapshotV4 | None = None,
) -> OrchestrationRunRequestV4:
    inputs, options = command.inputs, command.run_options
    return OrchestrationRunRequestV4(
        command.run_id, command.correlation_id, command.generated_at.isoformat(),
        tuple(OrchestrationEngineCodeV4(item.value) for item in command.requested_outputs),
        EngineRawInputsV4(
            balance_sheet_content=inputs.balance_sheet_content,
            balance_sheet_filename=inputs.balance_sheet_filename,
            income_statement_content=inputs.income_statement_content,
            income_statement_filename=inputs.income_statement_filename,
            trial_balance_result=_object(inputs.trial_balance_result),
            period_start_date=inputs.period_start_date,
            period_end_date=inputs.period_end_date,
            period_months_covered=inputs.period_months_covered,
            cash_flow_pre_resolved_context=cash_flow_context,
            trend_pre_resolved_context=trend_context,
        ),
        OrchestrationRunOptionsV4(
            industry_code=options.industry_code,
            company_size_bucket=options.company_size_bucket,
            tenant_id=options.engine_segmentation_tenant_id,
            report_type=command.report_request.report_type if command.report_request else None,
            dashboard_type=command.dashboard_request.dashboard_type if command.dashboard_request else None,
            company_metadata=command.company_metadata,
            reporting_period_label_tr=options.reporting_period_label_tr,
            optional_sections=options.optional_report_sections,
            currency_display_policy=options.currency_display_policy,
            locale=options.locale,
            render_contract=command.render_contract_request,
        ),
        previous_snapshot,
    )
