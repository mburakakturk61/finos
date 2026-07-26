"""
Milestone 4.1 (Analysis Foundation) / Milestone 4.2 (Balance Sheet + Income
Statement Engine): motor adaptörlerinin merkezi kaydı.

İKİ ayrı sınıflandırma dünyasından erişilebilir olacak şekilde tasarlandı
(onaylanan Milestone 4.1 kararı #5):
  - DetectedDocumentType: bulk upload sınıflandırma akışının (app.classification)
    ürettiği tahmin türü.
  - DocumentType: genel/doğrudan belge yükleme akışının (henüz eklenmedi --
    Milestone 4.2'de bilerek ERTELENDİ, bkz. onaylanan Milestone 4.2 kararı
    #4) kullanacağı kalıcı belge türü.

Bir adaptörün KENDİ kimliği bu iki enum dünyasından BAĞIMSIZ, `AnalysisType`
değeridir -- `_ENGINE_BY_ANALYSIS_TYPE` TEK doğruluk kaynağıdır.
`get_engine_for_detected_type`/`get_engine_for_document_type` yalnızca
kendi enum dünyalarından bu tek kayda YÖNLENDİRME yapar; aynı adaptöre iki
yerde dağınık hardcoded if/elif bloklarıyla ayrı ayrı bağlanma YOK.

MİLESTONE 4.2 DEĞİŞİKLİĞİ (onaylanan karar #7/#8): `BalanceSheetEngineAdapter`
ve `IncomeStatementEngineAdapter` eklendi. Bu registry artık
`app.services.bulk_upload`'ın GERÇEK confirm dispatch akışına BAĞLI (Milestone
4.1'deki "henüz bağlanmadı" kısıtı bu milestone'da kaldırıldı) --
`TrialBalanceEngineAdapter` de dahil olmak üzere ÜÇ adaptör de artık
`_run_confirm_analyses`/`_write_confirmed_records` tarafından gerçekten
çağrılıyor. trial_balance'ın davranışının BİREBİR AYNI kaldığı regresyon
testleriyle kanıtlanmıştır (bkz. tests/README.md).
"""

from __future__ import annotations

from app.engines.balance_sheet.adapter import BalanceSheetEngineAdapter
from app.engines.income_statement.adapter import IncomeStatementEngineAdapter
from app.engines.protocol import EngineAdapter, EngineRunContext, EngineRunResult
from app.models.enums import (
    AnalysisStatus,
    AnalysisType,
    DetectedDocumentType,
    DocumentType,
    SourceMode,
)
from app.trial_balance.service import analyze_trial_balance


class TrialBalanceEngineAdapter:
    """
    app.trial_balance.service.analyze_trial_balance'ı EngineAdapter
    sözleşmesine saran ince bir katman. app/trial_balance/**'e YENİ bir
    bağımlılık DEĞİL -- app/services/bulk_upload.py ve
    app/services/trial_balance_upload.py'nin bugün zaten yaptığı, aynı
    PUBLIC fonksiyon çağrısının bir başka çağıranı; trial_balance/**'in
    kendisi bu adımda HİÇ değiştirilmedi.

    Modül docstring'inde belirtildiği gibi Milestone 4.1'de gerçek dispatch
    akışına bağlı DEĞİLDİR -- yalnızca izole testlerde çağrılır.
    """

    analysis_type = AnalysisType.TRIAL_BALANCE
    requires_content = True

    def run(
        self,
        *,
        content: bytes | None,
        filename: str | None,
        context: EngineRunContext,
    ) -> EngineRunResult:
        if content is None:
            raise ValueError(
                "TrialBalanceEngineAdapter icerik (content) olmadan calisamaz "
                "(requires_content=True)."
            )

        try:
            result = analyze_trial_balance(content=content, filename=filename or "")
        except Exception as error:
            return EngineRunResult(
                analysis_type=self.analysis_type,
                source_mode=SourceMode.DIRECT_DOCUMENT,
                status=AnalysisStatus.FAILED,
                result_json=None,
                error_message=str(error),
            )

        return EngineRunResult(
            analysis_type=self.analysis_type,
            source_mode=SourceMode.DIRECT_DOCUMENT,
            status=AnalysisStatus.COMPLETED,
            result_json=result,
        )


# analysis_type -> adaptör. TEK doğruluk kaynağı. Milestone 4.2: Balance
# Sheet/Income Statement eklendi (cash_flow/tax_return/financial_ratios
# Milestone 4.3/4.4/4.5'i bekliyor, hâlâ kayıtlı DEĞİL).
_ENGINE_BY_ANALYSIS_TYPE: dict[AnalysisType, EngineAdapter] = {
    AnalysisType.TRIAL_BALANCE: TrialBalanceEngineAdapter(),
    AnalysisType.BALANCE_SHEET: BalanceSheetEngineAdapter(),
    AnalysisType.INCOME_STATEMENT: IncomeStatementEngineAdapter(),
}

# DetectedDocumentType -> analysis_type. Milestone 4.2: balance_sheet/
# income_statement eklendi; cash_flow_statement/corporate_tax_return/
# temporary_tax_return Milestone 4.4/4.5'i bekliyor.
_DETECTED_TYPE_TO_ANALYSIS_TYPE: dict[DetectedDocumentType, AnalysisType] = {
    DetectedDocumentType.TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
    DetectedDocumentType.BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    DetectedDocumentType.INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
}

# DocumentType -> analysis_type. Aynı gerekçeyle balance_sheet/income_statement.
_DOCUMENT_TYPE_TO_ANALYSIS_TYPE: dict[DocumentType, AnalysisType] = {
    DocumentType.TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
    DocumentType.BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    DocumentType.INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
}


def get_engine_for_analysis_type(analysis_type: AnalysisType) -> EngineAdapter | None:
    """Adaptörü doğrudan kendi kimliğiyle (AnalysisType) arar."""

    return _ENGINE_BY_ANALYSIS_TYPE.get(analysis_type)


def get_engine_for_detected_type(
    detected_type: DetectedDocumentType,
) -> EngineAdapter | None:
    """Bulk upload sınıflandırma akışından (DetectedDocumentType) adaptör
    arar. Kayıtlı olmayan türler için güvenle None döner."""

    analysis_type = _DETECTED_TYPE_TO_ANALYSIS_TYPE.get(detected_type)
    if analysis_type is None:
        return None
    return _ENGINE_BY_ANALYSIS_TYPE.get(analysis_type)


def get_engine_for_document_type(document_type: DocumentType) -> EngineAdapter | None:
    """Genel/doğrudan belge yükleme akışından (DocumentType) adaptör arar.
    Kayıtlı olmayan türler için güvenle None döner."""

    analysis_type = _DOCUMENT_TYPE_TO_ANALYSIS_TYPE.get(document_type)
    if analysis_type is None:
        return None
    return _ENGINE_BY_ANALYSIS_TYPE.get(analysis_type)
