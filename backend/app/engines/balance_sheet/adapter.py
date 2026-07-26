"""
Milestone 4.2: Balance Sheet Engine `EngineAdapter` implementasyonu --
`app.engines.protocol.EngineAdapter` sözleşmesine uyar,
`app.engines.balance_sheet.service.analyze_balance_sheet`'i sarar.
"""

import logging

from app.engines.balance_sheet.service import analyze_balance_sheet
from app.engines.protocol import EngineRunContext, EngineRunResult, EngineSourceRef
from app.models.enums import AnalysisSourceRole, AnalysisStatus, AnalysisType, SourceMode


logger = logging.getLogger(__name__)


class BalanceSheetEngineAdapter:
    analysis_type = AnalysisType.BALANCE_SHEET
    requires_content = True

    def run(
        self,
        *,
        content: bytes | None,
        filename: str | None,
        context: EngineRunContext,
    ) -> EngineRunResult:
        try:
            outcome = analyze_balance_sheet(
                content=content,
                filename=filename,
                trial_balance_result=context.trial_balance_result,
            )
        except Exception:
            logger.exception("Balance Sheet motoru beklenmeyen bir hata verdi.")
            return EngineRunResult(
                analysis_type=self.analysis_type,
                source_mode=SourceMode.DIRECT_DOCUMENT,
                status=AnalysisStatus.FAILED,
                error_message=(
                    "Bilanço analiz edilemedi. Belge bozuk ya da beklenen "
                    "formatta olmayabilir."
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
                # Aynı confirm batch'inde, henüz DB'ye yazılmamış bir
                # trial_balance sonucu kullanıldı -- gerçek analysis_result_id
                # FAZ 3'te (trial_balance flush edildikten SONRA) orkestratör
                # tarafından çözülecek. Burada sahte/uydurma bir kimlik
                # ÜRETİLMEZ (onaylanan Milestone 4.2 kararı #5).
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
