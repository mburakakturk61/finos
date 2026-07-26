"""
Milestone 4.2: Income Statement Engine `EngineAdapter` implementasyonu --
`app.engines.protocol.EngineAdapter` sözleşmesine uyar,
`app.engines.income_statement.service.analyze_income_statement`'i sarar.
`app.engines.balance_sheet.adapter` ile AYNI desen.
"""

import logging

from app.engines.income_statement.service import analyze_income_statement
from app.engines.protocol import EngineRunContext, EngineRunResult, EngineSourceRef
from app.models.enums import AnalysisSourceRole, AnalysisStatus, AnalysisType, SourceMode


logger = logging.getLogger(__name__)


class IncomeStatementEngineAdapter:
    analysis_type = AnalysisType.INCOME_STATEMENT
    requires_content = True

    def run(
        self,
        *,
        content: bytes | None,
        filename: str | None,
        context: EngineRunContext,
    ) -> EngineRunResult:
        try:
            outcome = analyze_income_statement(
                content=content,
                filename=filename,
                trial_balance_result=context.trial_balance_result,
            )
        except Exception:
            logger.exception("Income Statement motoru beklenmeyen bir hata verdi.")
            return EngineRunResult(
                analysis_type=self.analysis_type,
                source_mode=SourceMode.DIRECT_DOCUMENT,
                status=AnalysisStatus.FAILED,
                error_message=(
                    "Gelir tablosu analiz edilemedi. Belge bozuk ya da "
                    "beklenen formatta olmayabilir."
                ),
            )

        if outcome.status == AnalysisStatus.FAILED:
            return EngineRunResult(
                analysis_type=self.analysis_type,
                source_mode=SourceMode.DIRECT_DOCUMENT,
                status=AnalysisStatus.FAILED,
                error_message=outcome.error_message,
            )

        sources: list[EngineSourceRef] = []
        pending_role: AnalysisSourceRole | None = None

        if outcome.trial_balance_usage is not None:
            role = (
                AnalysisSourceRole.TRIAL_BALANCE_FALLBACK
                if outcome.trial_balance_usage == "fallback_source"
                else AnalysisSourceRole.SUPPORTING_ANALYSIS
            )
            if context.trial_balance_analysis_result_id is not None:
                sources.append(
                    EngineSourceRef(
                        role=role,
                        analysis_result_id=context.trial_balance_analysis_result_id,
                    )
                )
            elif context.trial_balance_pending_in_batch:
                pending_role = role

        return EngineRunResult(
            analysis_type=self.analysis_type,
            source_mode=outcome.source_mode,
            status=AnalysisStatus.COMPLETED,
            result_json=outcome.result_json,
            warnings=(outcome.result_json or {}).get("warnings", []),
            sources=sources,
            pending_trial_balance_source_role=pending_role,
        )
