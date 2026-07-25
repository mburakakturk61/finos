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


class BatchStatus(str, enum.Enum):
    """BulkUploadBatch.status için kullanılır (Milestone 2 / Adım 3)."""

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DetectedDocumentType(str, enum.Enum):
    """
    DocumentClassifier'ın üretebileceği türler. Bilinçli olarak
    DocumentType'tan (FinancialDocument) AYRI bir enum -- bu, henüz
    onaylanmamış bir TAHMİN kümesidir, DocumentType ise onaylanmış/kalıcı
    bir belgenin gerçek türüdür. UNKNOWN yalnızca burada anlamlıdır.
    """

    TRIAL_BALANCE = "trial_balance"
    CORPORATE_TAX_RETURN = "corporate_tax_return"
    TEMPORARY_TAX_RETURN = "temporary_tax_return"
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    UNKNOWN = "unknown"


class ClassificationStatus(str, enum.Enum):
    """
    BulkUploadItem.classification_status. Beş değer de birbirinden
    AYRI ve karşılıklı dışlayıcıdır (bir item yalnızca birinde yer alır);
    ek bağlam warnings_json'dadır.
    """

    AUTO_MATCHED = "auto_matched"
    NEEDS_REVIEW = "needs_review"
    DUPLICATE = "duplicate"
    POSSIBLE_DUPLICATE = "possible_duplicate"
    UNRECOGNIZED = "unrecognized"


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
