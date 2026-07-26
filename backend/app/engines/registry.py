"""
Milestone 4.1 (Analysis Foundation): motor adaptörlerinin merkezi kaydı.

İKİ ayrı sınıflandırma dünyasından erişilebilir olacak şekilde tasarlandı
(onaylanan Milestone 4.1 kararı #5):
  - DetectedDocumentType: bulk upload sınıflandırma akışının (app.classification)
    ürettiği tahmin türü.
  - DocumentType: genel/doğrudan belge yükleme akışının (Milestone 4.2'de
    eklenecek `POST /periods/{period_id}/documents`) kullanacağı kalıcı
    belge türü.

Bir adaptörün KENDİ kimliği bu iki enum dünyasından BAĞIMSIZ, `AnalysisType`
değeridir -- `_ENGINE_BY_ANALYSIS_TYPE` TEK doğruluk kaynağıdır.
`get_engine_for_detected_type`/`get_engine_for_document_type` yalnızca
kendi enum dünyalarından bu tek kayda YÖNLENDİRME yapar; aynı adaptöre iki
yerde dağınık hardcoded if/elif bloklarıyla ayrı ayrı bağlanma YOK.

ÖNEMLİ KAPSAM SINIRI (onaylanan Milestone 4.1 kararı #1): bu registry HENÜZ
hiçbir gerçek dispatch akışına (app.services.bulk_upload,
app.services.trial_balance_upload) BAĞLANMADI. `TrialBalanceEngineAdapter`
yalnızca registry sözleşmesinin gerçek kodla (mock değil) çalıştığını ve
geriye dönük uyumluluğu izole testlerde doğrulamak için var. Mevcut 93/93
geçen üretim akışının davranışı bu adımda DEĞİŞMEDİ. Registry'nin gerçek
dispatch'e bağlanması Milestone 4.2'de, ilk yeni motor (Balance Sheet/Income
Statement) eklendiğinde yapılacak.
"""

from __future__ import annotations

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


# analysis_type -> adaptör. TEK doğruluk kaynağı.
_ENGINE_BY_ANALYSIS_TYPE: dict[AnalysisType, EngineAdapter] = {
    AnalysisType.TRIAL_BALANCE: TrialBalanceEngineAdapter(),
}

# DetectedDocumentType -> analysis_type. Milestone 4.1'de yalnızca
# trial_balance eşlemesi aktif; balance_sheet/income_statement/
# cash_flow_statement/corporate_tax_return/temporary_tax_return Milestone
# 4.2/4.4/4.5'te eklenecek.
_DETECTED_TYPE_TO_ANALYSIS_TYPE: dict[DetectedDocumentType, AnalysisType] = {
    DetectedDocumentType.TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
}

# DocumentType -> analysis_type. Aynı gerekçeyle yalnızca trial_balance.
_DOCUMENT_TYPE_TO_ANALYSIS_TYPE: dict[DocumentType, AnalysisType] = {
    DocumentType.TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
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
