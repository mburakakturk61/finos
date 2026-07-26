"""
Milestone 4.3A (Ratio Calculation Foundation): Financial Ratio Engine'in
adaptör iskeleti -- `AnalysisType.FINANCIAL_RATIOS` için `EngineAdapter`
sözleşmesine uyar VE ilk 9 ortak oranı GERÇEKTEN hesaplar (onaylanan
mimari doküman, Bölüm R.5 madde 8).

KESİN SINIR (onaylanan Milestone 4.3A kararı): bu adaptör Milestone 4.3A
kapsamında HİÇBİR API endpoint'ine, bulk upload confirm akışına ya da
`ratio_recompute`'a BAĞLANMAZ -- yalnızca `app.engines.registry`'de
`get_engine_for_analysis_type(AnalysisType.FINANCIAL_RATIOS)` ile
kayıtlıdır ve doğrudan/izole çağrılarak (birim testleri) kullanılabilir.
Gerçek akışa bağlanması Milestone 4.3B'nin kapsamıdır.
"""

from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.protocol import EngineRunContext, EngineRunResult
from app.models.enums import AnalysisStatus, AnalysisType, SourceMode


class FinancialRatioEngineAdapter:
    analysis_type = AnalysisType.FINANCIAL_RATIOS
    # Ratio Engine hiçbir belge ayrıştırmaz -- yalnızca başka analiz
    # sonuçlarını (context.balance_sheet_result/income_statement_result)
    # okur (mimari doküman Bölüm B.3).
    requires_content = False

    def run(
        self,
        *,
        content: bytes | None,
        filename: str | None,
        context: EngineRunContext,
    ) -> EngineRunResult:
        if context.balance_sheet_result is None and context.income_statement_result is None:
            return EngineRunResult(
                analysis_type=self.analysis_type,
                source_mode=SourceMode.MULTI_SOURCE_DERIVED,
                status=AnalysisStatus.FAILED,
                result_json=None,
                error_message=(
                    "Ne Balance Sheet ne Income Statement analiz sonucu "
                    "sağlanmadı (Financial Ratio Engine hiçbir belge "
                    "ayrıştırmaz, yalnızca başka analiz sonuçlarını okur)."
                ),
            )

        result_json = analyze_financial_ratios(
            balance_sheet_result=context.balance_sheet_result,
            income_statement_result=context.income_statement_result,
        )

        return EngineRunResult(
            analysis_type=self.analysis_type,
            source_mode=SourceMode.MULTI_SOURCE_DERIVED,
            status=AnalysisStatus.COMPLETED,
            result_json=result_json,
            # Milestone 4.3A kapsamında `sources` BİLİNÇLİ OLARAK boş --
            # gerçek source-tracking (financial_analysis_result_sources
            # satırları) BS/IS'in gerçek `analysis_result_id`'lerine ihtiyaç
            # duyar; bu alanlar `EngineRunContext`'e henüz eklenmedi (B.8,
            # Milestone 4.3B'ye bırakıldı -- ratio_recompute'un bağlanmasıyla
            # birlikte).
            sources=[],
        )
