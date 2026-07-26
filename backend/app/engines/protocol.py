"""
Milestone 4.1 (Analysis Foundation): yeni motorların (Balance Sheet/Income
Statement/Cash Flow/Tax Return/Financial Ratio -- Milestone 4.2+) ortak
arayüz sözleşmesi.

app/trial_balance/** gibi bu paket de sqlalchemy/fastapi/pydantic'e SIFIR
bağımlıdır -- kısıtlı sandbox'larda bile gerçekten çalıştırılabilir
testlerle doğrulanabilsin diye (bkz. tests/test_engine_registry_unit.py).

Bu dosya YALNIZCA sözleşmeyi tanımlar; gerçek motor implementasyonları
(extractor/analyzer) Milestone 4.2+'da eklenecek.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import ClassVar, Protocol, runtime_checkable

from app.models.enums import AnalysisSourceRole, AnalysisStatus, AnalysisType, SourceMode


@dataclass(frozen=True)
class EngineSourceRef:
    """
    Bir motor çalıştırmasının kullandığı TEK bir kaynağa referans --
    financial_analysis_result_sources tablosundaki bir satırın Python
    tarafındaki karşılığı. `document_id` XOR `analysis_result_id` kuralı
    burada da (DB'deki ck_financial_analysis_result_sources_xor_source ile
    aynı) zorlanır -- motor kodu yanlış şekilli bir kaynak üretirse
    financial_analysis_result_sources'a yazılmadan, Python seviyesinde
    ERKEN hata verir.
    """

    role: AnalysisSourceRole
    document_id: uuid.UUID | None = None
    analysis_result_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        has_document = self.document_id is not None
        has_analysis = self.analysis_result_id is not None
        if has_document == has_analysis:
            raise ValueError(
                "EngineSourceRef tam olarak bir kaynak belirtmeli: "
                "document_id XOR analysis_result_id "
                "(ck_financial_analysis_result_sources_xor_source ile aynı kural)."
            )


@dataclass
class EngineRunContext:
    """
    Bir motor çalıştırmasına dışarıdan (çağıran servis katmanı) sağlanan
    bağlam. Milestone 4.1'de yalnızca trial_balance-fallback senaryosunu
    (Milestone 4 mimari kararı B.2/Alternatif 3) kapsayacak alanlar var --
    `prior_period_*` gibi alanlar Cash Flow Engine'in (Milestone 4.4) ihtiyaç
    duyacağı an, GERİYE UYUMLU (additive) şekilde eklenecek; şimdiden
    eklenmedi (YAGNI).

    Milestone 4.2 (onaylanan karar #5) `company_id`/`period_id`'yi OPSİYONEL
    yaptı: app.services.bulk_upload'ın FAZ 2 (bellek-içi, DB transaction'ı
    açık değilken) dependency-aware orkestrasyonunda, firma/dönem için
    `mode="new"` (henüz DB'de yaratılmamış) bir çözüm seçildiyse gerçek bir
    UUID YOKTUR -- FAZ 3'e kadar (find-or-create) hiç var olmayabilir. Sahte
    bir UUID ÜRETİLMEZ; bunun yerine bu alanlar `None` kalır. Şu anki hiçbir
    adaptör (TrialBalance/BalanceSheet/IncomeStatement) bu alanları
    KULLANMIYOR -- yalnızca ileride kimlik bağlamına ihtiyaç duyacak
    motorlar (ör. Milestone 4.3 Financial Ratio Engine, FAZ 3 sonrası/DB
    id'leri kesinleştikten sonra çalışacağı için) için hazır bir alan.
    """

    company_id: uuid.UUID | None = None
    period_id: uuid.UUID | None = None
    # O dönemin en güncel COMPLETED trial_balance analiz sonucunun
    # result_json'u (varsa) -- salt-okunur, motorun "doğrudan belge yoksa
    # trial_balance'tan türet" (source_mode=trial_balance_derived) yolunu
    # besler. Bu VERİ-seviyeli bir bağımlılıktır, app/trial_balance/**'e
    # KOD bağımlılığı değildir.
    trial_balance_result: dict | None = None
    # `trial_balance_result` DB'de ZATEN KAYITLI bir sonuçtan geliyorsa
    # (FAZ 1'de okunmuş) bu alan doludur -- motor `sources`'a doğrudan
    # bir EngineSourceRef ekleyebilir. Milestone 4.2 (onaylanan karar #5):
    # `trial_balance_result` AYNI confirm batch'inde, henüz DB'ye
    # YAZILMAMIŞ bir trial_balance sonucundan geliyorsa bu alan `None`
    # kalır VE `trial_balance_pending_in_batch=True` olur -- motor bu
    # durumda gerçek bir `analysis_result_id` YOKTUR, sahte/uydurma bir
    # kimlik ÜRETMEZ; bunun yerine `EngineRunResult.
    # pending_trial_balance_source_role` alanını doldurur, gerçek kaynak
    # satırı orkestratör (app/services/bulk_upload.py) tarafından FAZ 3'te,
    # trial_balance'ın kendi FinancialAnalysisResult'ı flush edildikten
    # SONRA oluşturulur.
    trial_balance_analysis_result_id: uuid.UUID | None = None
    trial_balance_pending_in_batch: bool = False

    # Milestone 4.3A (Ratio Calculation Foundation, onaylanan mimari doküman
    # Bölüm M.2) -- ADDITIVE, geriye uyumlu. Financial Ratio Engine'in aynı
    # döneme ait Balance Sheet/Income Statement analiz sonuçlarına (ZATEN
    # ÜRETİLMİŞ result_json'lar -- yeniden hesaplama YOK, B.3) erişimi için.
    # Şu anki hiçbir adaptör (TrialBalance/BalanceSheet/IncomeStatement) bu
    # alanları KULLANMIYOR/etkilenmiyor -- yalnızca FinancialRatioEngineAdapter
    # (Milestone 4.3A'da eklendi, HİÇBİR akışa bağlı değil) okur.
    balance_sheet_result: dict | None = None
    income_statement_result: dict | None = None
    # Büyüme oranları ve (Milestone 4.3B'de) ortalama-bakiye oranları için
    # önceki dönemin BS/IS sonuçları -- Milestone 4.3A'nın 9 oranından
    # HİÇBİRİ bunu TÜKETMİYOR, yalnızca ileriye dönük altyapı olarak
    # ekleniyor (additive genişleme deseni, bkz. yukarıdaki trial_balance_*
    # alanlarının aynı gerekçesi).
    prior_period_balance_sheet_result: dict | None = None
    prior_period_income_statement_result: dict | None = None

    # Milestone 4.3B (Core Financial Ratios) -- ADDITIVE, geriye uyumlu.
    # `ratio_derived_facts.compute_days_in_period`'in ihtiyaç duyduğu
    # `FinancialPeriod.start_date`/`end_date`/`months_covered` -- bu alanlar
    # 4.3A'da hiç yoktu (o zaman hiçbir oran gün-bazlı hesaplama
    # yapmıyordu). Şu anki hiçbir adaptör bunu KULLANMIYOR/etkilenmiyor --
    # yalnızca FinancialRatioEngineAdapter (hâlâ HİÇBİR akışa bağlı değil)
    # okur.
    period_start_date: date | None = None
    period_end_date: date | None = None
    period_months_covered: int | None = None


@dataclass
class EngineRunResult:
    """Bir EngineAdapter.run() çağrısının dönüşü. `source_mode` ve
    `sources` alanları, FinancialAnalysisResult + financial_analysis_result_sources
    satırlarının servis katmanınca nasıl yazılacağını belirler (Milestone
    4.1 kapsamında bu yazma HENÜZ implemente edilmedi, bkz. kapsam sınırı)."""

    analysis_type: AnalysisType
    source_mode: SourceMode
    status: AnalysisStatus
    result_json: dict | None = None
    error_message: str | None = None
    warnings: list[dict] = field(default_factory=list)
    sources: list[EngineSourceRef] = field(default_factory=list)
    # Milestone 4.2 (onaylanan karar #5): motor, context.trial_balance_
    # pending_in_batch=True olduğu için gerçek bir analysis_result_id
    # ALAMADIĞI ama trial_balance verisini KULLANDIĞI durumda bu alanı
    # doldurur (`trial_balance_fallback` veya `supporting_analysis`).
    # Orkestratör, trial_balance'ın FinancialAnalysisResult'ı flush
    # edildikten SONRA gerçek id ile bu rolü kullanarak
    # FinancialAnalysisResultSource satırını oluşturur. `None` ise
    # aynı-batch ertelenmiş bir kaynak YOK.
    pending_trial_balance_source_role: AnalysisSourceRole | None = None


@runtime_checkable
class EngineAdapter(Protocol):
    """
    Her motor adaptörünün uyması gereken sözleşme. `analysis_type`, motorun
    app.engines.registry içindeki KENDİ kimliğidir (bkz. registry.py
    docstring'i -- DetectedDocumentType/DocumentType'tan BAĞIMSIZ).
    """

    analysis_type: ClassVar[AnalysisType]
    requires_content: ClassVar[bool]

    def run(
        self,
        *,
        content: bytes | None,
        filename: str | None,
        context: EngineRunContext,
    ) -> EngineRunResult: ...
