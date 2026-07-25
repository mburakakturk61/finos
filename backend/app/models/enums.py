import enum


class PeriodType(str, enum.Enum):
    """docs/FINOS_ARCHITECTURE_V1.md bölüm 4.2'de tanımlanan period_type değerleri."""

    YEAR_END = "year_end"
    QUARTER = "quarter"
    TEMPORARY_TAX = "temporary_tax"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class PeriodStatus(str, enum.Enum):
    """
    Blueprint dokümanında status için örnek değer verilmemiş; Milestone 2
    kapsamında ilk mantıklı küme burada tanımlanıyor, ileride genişletilebilir.
    """

    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class DocumentType(str, enum.Enum):
    """Yalnızca mizan (trial_balance) bu milestone'da işlenebiliyor; diğerleri
    şema seviyesinde yer tutucu olarak tanımlandı."""

    TRIAL_BALANCE = "trial_balance"
    TAX_DECLARATION = "tax_declaration"
    FINANCIAL_STATEMENT = "financial_statement"
    OTHER = "other"


class ProcessingStatus(str, enum.Enum):
    """FinancialDocument.processing_status için kullanılır."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AnalysisType(str, enum.Enum):
    """Yalnızca trial_balance bu milestone'da destekleniyor; diğer analiz
    türleri (ör. tax_reconciliation) ileride eklenebilir."""

    TRIAL_BALANCE = "trial_balance"


class AnalysisStatus(str, enum.Enum):
    """
    FinancialAnalysisResult.status için kullanılır. Bilinçli olarak
    ProcessingStatus'tan AYRI bir enum -- belge işlenmesi ile analiz
    çalışmasının durumu farklı kavramlardır ve bağımsız evrilebilmelidir
    (Milestone 2 / Adım 2 mimari kararı).
    """

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
