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
    """

    company_id: uuid.UUID
    period_id: uuid.UUID
    # O dönemin en güncel COMPLETED trial_balance analiz sonucunun
    # result_json'u (varsa) -- salt-okunur, motorun "doğrudan belge yoksa
    # trial_balance'tan türet" (source_mode=trial_balance_derived) yolunu
    # besler. Bu VERİ-seviyeli bir bağımlılıktır, app/trial_balance/**'e
    # KOD bağımlılığı değildir.
    trial_balance_result: dict | None = None
    trial_balance_analysis_result_id: uuid.UUID | None = None


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
