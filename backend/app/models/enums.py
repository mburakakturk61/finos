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


class PeriodCoverageKind(str, enum.Enum):
    """Authoritative Cash Flow period coverage semantics (Milestone 4.5C)."""

    DISCRETE = "discrete"
    CUMULATIVE = "cumulative"


class DocumentType(str, enum.Enum):
    """
    Milestone 2'de yalnızca mizan (trial_balance) işlenebiliyordu; diğer kaba
    kategoriler (tax_declaration/financial_statement/other) şema seviyesinde
    yer tutucuydu.

    Milestone 4.1 (Analysis Foundation): balance_sheet/income_statement/
    cash_flow_statement/corporate_tax_return/temporary_tax_return eklendi --
    bu, DetectedDocumentType'ın (sınıflandırma motorunun tahmin edebildiği
    türler) zaten sahip olduğu ayrıntı seviyesiyle DocumentType'ı (kalıcı
    belge türü) hizalar. ÖNEMLİ: bu değerleri henüz HİÇBİR motor üretmiyor --
    yalnızca şema hazırlığı. Gerçek üretim Milestone 4.2 (balance_sheet/
    income_statement), 4.4 (cash_flow_statement) ve 4.5'te (corporate/
    temporary_tax_return) eklenecek. Eski tax_declaration/financial_statement
    değerleri geriye dönük uyumluluk için SİLİNMEDİ, yalnızca artık yeni
    yazımlarda kullanılmaları beklenmiyor.
    """

    TRIAL_BALANCE = "trial_balance"
    TAX_DECLARATION = "tax_declaration"
    FINANCIAL_STATEMENT = "financial_statement"
    OTHER = "other"
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW_STATEMENT = "cash_flow_statement"
    CORPORATE_TAX_RETURN = "corporate_tax_return"
    TEMPORARY_TAX_RETURN = "temporary_tax_return"


class ProcessingStatus(str, enum.Enum):
    """FinancialDocument.processing_status için kullanılır."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class BatchStatus(str, enum.Enum):
    """
    BulkUploadBatch.status için kullanılır (Milestone 2 / Adım 3).

    CONFIRMED (Milestone 3 / Adım 1): kullanıcı onayı sonrası tüm accepted
    item'lar production kayıtlarına dönüştürüldü. Terminal ve immutable --
    bu duruma ulaşan bir batch'in item'larına bir daha PATCH uygulanamaz ve
    batch bir daha confirm edilemez.
    """

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CONFIRMED = "confirmed"


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
    # Milestone 4.1: değer eklendi (şema hazırlığı). classify_document_type
    # kural tabloları (app/classification/document_classifier.py) BU ADIMDA
    # GÜNCELLENMEDİ -- gerçek nakit akış tablosu tespiti Milestone 4.4'te
    # eklenecek. Bu değer o zamana kadar hiçbir sınıflandırma çıktısında
    # üretilmeyecek.
    CASH_FLOW_STATEMENT = "cash_flow_statement"
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


class ItemReviewDecision(str, enum.Enum):
    """
    BulkUploadItem.user_decision (Milestone 3 / Adım 1) -- kullanıcının
    staging item'ı için verdiği KARAR. classification_status'tan (motorun
    ürettiği tahmin/sonuç) BİLEREK ayrı ve bağımsız bir alan: biri makine
    çıktısı, diğeri insan kararıdır ve ikisi karıştırılmamalıdır (ör. bir
    item classification_status=needs_review olsa da kullanıcı onu
    accepted yapabilir; classification_status=auto_matched olsa da
    kullanıcı ignored yapabilir).

    Silme (hard delete) YOK -- yalnızca durum geçişi. Bir item asla
    accepted olmadan production tablolarına yazılmaz.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    IGNORED = "ignored"


class AnalysisType(str, enum.Enum):
    """
    Milestone 2'de yalnızca trial_balance destekleniyordu.

    Milestone 4.1 (Analysis Foundation): balance_sheet/income_statement/
    cash_flow/tax_return/financial_ratios değerleri eklendi -- şema
    hazırlığı. Bu değerleri ÜRETECEK motorlar henüz YAZILMADI:
      - balance_sheet, income_statement -> Milestone 4.2
      - financial_ratios -> Milestone 4.3
      - cash_flow -> Milestone 4.4
      - tax_return -> Milestone 4.5
    app/engines/registry.py bu değerlerin hiçbiri için henüz kayıtlı bir
    adaptöre sahip değil (yalnızca trial_balance kayıtlı).
    """

    TRIAL_BALANCE = "trial_balance"
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"
    TAX_RETURN = "tax_return"
    FINANCIAL_RATIOS = "financial_ratios"
    MULTI_PERIOD_TREND = "multi_period_trend"


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


class SourceMode(str, enum.Enum):
    """
    FinancialAnalysisResult.source_mode (Milestone 4.1) -- bir analiz
    sonucunun ESAS OLARAK hangi veri kaynağından üretildiğini açıkça
    kaydeder. app/engines/** motorlarının hepsi bu üç değerden birini
    üretmek ZORUNDADIR (bkz. app/engines/protocol.py::EngineRunResult).

    DIRECT_DOCUMENT: Analiz, doğrudan yüklenmiş TEK bir belgeye dayanır
    (ör. gerçek bir bilanço/gelir tablosu dosyası, ya da bugünkü
    trial_balance analizi). DB seviyesinde zorlanan kural: bu değer
    seçiliyse financial_analysis_results.document_id NULL OLAMAZ (bkz.
    ck_financial_analysis_results_direct_requires_document).

    TRIAL_BALANCE_DERIVED: Analiz, doğrudan bir belge yerine o dönemin
    KAYITLI trial_balance analiz sonucunun (result_json) fallback olarak
    kullanılmasıyla türetildi (Milestone 4 mimari kararı B.2/Alternatif 3).
    document_id bu durumda NULL olabilir (belge yoktur) VEYA dolu olabilir
    (bazı motorlar hem kendi belgesine hem trial_balance sonucuna referans
    tutabilir) -- kaynak izlenebilirliği HER ZAMAN
    financial_analysis_result_sources'ta ayrıca kayıtlıdır.

    MULTI_SOURCE_DERIVED: Analiz, BİRDEN FAZLA belge ve/veya analiz
    sonucundan türetildi (ör. Financial Ratio Engine -- Milestone 4.3; Cash
    Flow Engine'in dolaylı/derived modu -- Milestone 4.4, iki ardışık
    dönemin bilançosu + gelir tablosu). document_id NULL olabilir (tek bir
    "asıl" belge yoktur); katkı sağlayan TÜM kaynaklar
    financial_analysis_result_sources'ta ayrı ayrı satırlar olarak durur.
    """

    DIRECT_DOCUMENT = "direct_document"
    TRIAL_BALANCE_DERIVED = "trial_balance_derived"
    MULTI_SOURCE_DERIVED = "multi_source_derived"


class AnalysisSourceRole(str, enum.Enum):
    """
    FinancialAnalysisResultSource.role (Milestone 4.1) -- bir kaynak
    satırının üst analiz sonucuna NEDEN katkı sağladığını belirtir. Yalnızca
    "hangi belge/analiz" değil "hangi rolde" sorusuna da DB seviyesinde
    cevap verir. Rol ile kaynak türü arasındaki eşleşme
    ck_financial_analysis_result_sources_role_source_match CHECK
    constraint'iyle zorlanır:

      - PRIMARY_DOCUMENT, SUPPORTING_DOCUMENT -> yalnızca source_document_id
        doluyken kullanılabilir.
      - PRIMARY_ANALYSIS, SUPPORTING_ANALYSIS, TRIAL_BALANCE_FALLBACK ->
        yalnızca source_analysis_result_id doluyken kullanılabilir.
      - PRIOR_PERIOD_REFERENCE -> her iki kaynak türüyle de kullanılabilir
        (ör. Cash Flow Engine'in önceki dönemin bilanço BELGESİNE ya da
        önceki dönemin bilanço ANALİZ SONUCUNA referans vermesi, hangisi
        mevcutsa).
    """

    PRIMARY_DOCUMENT = "primary_document"
    PRIMARY_ANALYSIS = "primary_analysis"
    TRIAL_BALANCE_FALLBACK = "trial_balance_fallback"
    PRIOR_PERIOD_REFERENCE = "prior_period_reference"
    SUPPORTING_DOCUMENT = "supporting_document"
    SUPPORTING_ANALYSIS = "supporting_analysis"
