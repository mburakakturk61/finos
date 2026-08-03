# Milestone 4.5 — Cash Flow Engine Design

**Türkçe ad:** Nakit Akış Motoru
**Doküman durumu:** FINAL tasarım adayı — bağımsız denetim kapısı bu dokümanın sonunda
**Tasarım sürümü:** 1.0.0
**Hedef milestone:** 4.5
**Runtime readiness:** %0 — bu doküman production implementasyonu değildir
**Bağlayıcı üst kaynak:** `FINOS_ARCHITECTURE_BOOK.md` v1.5.0
**Kod adı politikası:** “FINOS” yalnız dahili geliştirme kod adıdır; hiçbir runtime sembolüne, tablo adına, API alanına veya kullanıcı metnine taşınmaz.

---

## 1. Amaç

Milestone 4.5, tek bir tüzel kişinin iki karşılaştırılabilir dönemine ait doğrulanmış finansal verilerden, yalnız **dolaylı yöntemle** deterministik ve denetlenebilir bir nakit akış sonucu üretir. Motor:

- işletme, yatırım ve finansman nakit akışlarını birbirinden ayırır;
- açılış ve kapanış nakit ve nakit benzerlerini doğrular;
- hesaplanan net nakit değişimini bilanço hareketiyle mutabık kılar;
- kesin, türetilmiş, tahmini ve kullanılamayan kalemleri birbirine karıştırmaz;
- kaynağı olmayan capex, kredi kullanımı/geri ödemesi, temettü, nakden ödenen faiz/vergi veya kur farkı uydurmaz;
- her sonuç satırını kaynak, formül, mapping sürümü ve kanıt sınıfıyla açıklanabilir kılar.

Bu doküman executable architecture sözleşmesidir. Production kodu, test, migration veya API implementasyonu içermez.

## 2. Tarihsel Adlandırma ve Referanslar

Repository'deki eski Milestone 4 tasarımları Cash Flow Engine'i tarihsel olarak “4.4”, Tax Return Engine'i “4.5” diye adlandırır. Güncel yol haritasında gerçek 4.4 Executive Report Engine'dir ve bu çalışma **Milestone 4.5 — Cash Flow Engine** olarak bağlayıcıdır. Eski numaralar yalnız tarihsel bağlamdır; yeni production sembollerine veya doküman adına taşınmaz.

Bağlayıcı yerel referanslar:

- `backend/docs/FINOS_ARCHITECTURE_BOOK.md` v1.5.0
- Milestone 5.0A Analysis Orchestrator public contracts
- Milestone 5.0B Orchestration Persistence & Recovery contracts
- Milestone 5.0C Analysis Application Layer contracts
- mevcut Balance Sheet, Income Statement ve Financial Ratio engine sözleşmeleri
- `FinancialAnalysisResult` ve Storage Ownership Matrix

Muhasebesel doğrulama referansları:

- KGK, **TMS 7 Nakit Akış Tablosu**: https://www.kgk.gov.tr/Portalv2Uploads/files/Duyurular/v2/TMS_TFRS_Setleri/2024/Mavi_Kitap/TMS/TMS7_.pdf
- IFRS Foundation, **IAS 7 Statement of Cash Flows**: https://www.ifrs.org/issued-standards/list-of-standards/ias-7-statement-of-cash-flows.html

Bu referanslar hesaplama motoruna örtük politika gömülmesi için kullanılmaz. Standardın izin verdiği veya zaman içinde değiştirdiği sunum seçenekleri `CashFlowPresentationPolicy` sürümüyle açıkça seçilir.

## 3. Kapsam

V1 kapsamı:

1. Yalnız indirect/dolaylı yöntem.
2. Tek tüzel kişi, standalone dönem.
3. İki karşılaştırılabilir bilanço dönemi ve cari dönem gelir tablosu.
4. Hesap kodu seviyesinde ayrıntılı mizan veya eşdeğer kanonik kanıt.
5. Global, kapalı ve versioned hesap mapping registry'si.
6. Nakit/nakit benzeri allowlist ve eligibility policy'si.
7. Operating, investing ve financing canonical line item'ları.
8. Açılış/kapanış nakit mutabakatı.
9. Evidence, completeness, warning ve structured error modeli.
10. `FinancialAnalysisResult` sahipliğinde immutable sonuç kalıcılığı.
11. Ayrı immutable cross-period lineage tablosu.
12. Versioned 5.0A–5.0C orchestrator/application evolution.
13. Mevcut altı cash-flow ratio formülüne veri akışı.
14. Executive Report'a presentation-only projection.

## 4. Kapsam Dışı

- doğrudan yöntem ve direct cash-flow statement parsing;
- transaction ledger, banka ekstresi veya cashbook entegrasyonu;
- konsolidasyon, eliminasyon ve grup içi nakit akışları — 4.7;
- genel çok-dönem trendi, CAGR, seri analizi ve trend yorumu — 4.6;
- company/tenant-specific account mapping override;
- cash-flow benchmark veya score ağırlığı değişikliği;
- otomatik tahmin, machine learning veya LLM çıkarımı;
- API/router/UI/queue/worker/scheduler/batch runner;
- event sourcing;
- distributed lock veya automatic retry/backoff;
- direct statement ile derived statement arasında authoritative tercih mekanizması.

Repository'de 4.6 ve 4.7 için authoritative kapsam dokümanı bulunmamaktadır. Yukarıdaki iki sınır güncel kullanıcı kararından gelir; bu doküman 4.6/4.7 için başka kapsam uydurmaz.

## 5. Mevcut Sistem Gerçekleri

### 5.1 Hazır altyapı

- `AnalysisType.CASH_FLOW`, `DocumentType.CASH_FLOW_STATEMENT` ve `DetectedDocumentType.CASH_FLOW_STATEMENT` enum değerleri vardır.
- `CashFlowFacts` yalnız yedi özet alanlı hazırlık dataclass'ı olarak vardır; çalışan engine değildir.
- `FinancialAnalysisResult` multi-source sonuç saklayabilir ve canonical digest taşır.
- mizan sonucu leaf account code/name/amount detayını korur.
- direct Balance Sheet sonucu cash, inventory, receivables ve payables alanlarını taşıyabilir.
- Income Statement sonucu net profit ve kanıt varsa depreciation/amortization taşıyabilir.
- altı cash-flow oran formülü kayıtlıdır fakat `engine_dependency="cash_flow"` nedeniyle daima `NOT_CALCULABLE` döner.
- reconciliation helper Decimal tabanlı iki eşik sunar.

### 5.2 Eksikler

- cash-flow engine/adapter/registry/DTO yoktur;
- trial-balance fallback cash, inventory, receivables, payables ve depreciation ayrıntısını kanonik facts'e taşımaz;
- current/prior dönem seçen authoritative port yoktur;
- `FinancialPeriod` üzerinde accounting basis/policy ve containing annual-reporting-period metadata'sı yoktur;
- mevcut lineage FK'leri kaynak ile sonucu aynı period'a zorladığı için prior-period source yazılamaz;
- 5.0A DAG ve 5.0C enum/ownership registry cash-flow düğümünü içermez;
- cash-flow fixture'ları iki karşılaştırılabilir dönem içermez;
- classifier'da cash-flow statement kuralı yoktur; direct mode kapsam dışı olduğu için 4.5 v1 bunu eklemez.

## 6. Değişmez V1 İlkeleri

1. Eksik parasal değer `None`'dır; sıfır değildir.
2. Bütün hesaplamalar `Decimal` ile yapılır; float hesaplama yasaktır.
3. Pozitif değer nakit girişi, negatif değer nakit çıkışıdır.
4. Aynı canonical input + aynı policy/registry/version → bit düzeyinde aynı canonical output.
5. Motor SQLAlchemy, FastAPI veya Pydantic import etmez.
6. Motor finansal kaynak seçmez ve DB sorgulamaz; trusted portların çözümlediği immutable input'u tüketir.
7. Account name tek başına authoritative mapping kaynağı değildir.
8. Reconciliation farkı kur farkı, reclassification veya “other” satırıyla otomatik kapatılamaz.
9. Bir kalem için brüt hareket kanıtı yoksa net bilanço hareketinden brüt giriş/çıkış uydurulmaz.
10. Tek payload sahibi `FinancialAnalysisResult` olarak kalır.
11. Cross-period lineage result payload'a gömülü tek kaynak olamaz; durable FK kayıtları zorunludur.
12. Minimum veri yokluğu teknik engine çökmesi değildir; persisted `INSUFFICIENT_DATA` sonucudur.
13. Integrity, scope veya digest ihlali fail-closed'dur; cash-flow payload owner üretilmez.
14. Cash-flow oranları mevcut score ağırlıklarını otomatik değiştiremez.

## 7. Kapalı Contract Taxonomy'leri

Tüm public engine tipleri `@dataclass(frozen=True)`, koleksiyonları `tuple`, map anahtarları `str` olur.

```python
class CashFlowMethod(str, Enum):
    INDIRECT = "indirect"

class CashFlowActivity(str, Enum):
    OPERATING = "operating"
    INVESTING = "investing"
    FINANCING = "financing"
    CASH_AND_CASH_EQUIVALENTS = "cash_and_cash_equivalents"
    FX_EFFECT = "fx_effect"
    RECLASSIFICATION_EFFECT = "reclassification_effect"
    RECONCILIATION = "reconciliation"
    UNCLASSIFIED = "unclassified"

class CashAvailabilityClassification(str, Enum):
    UNRESTRICTED_INCLUDED = "unrestricted_included"
    RESTRICTED_INCLUDED = "restricted_included"
    RESTRICTED_EXCLUDED = "restricted_excluded"
    ELIGIBILITY_UNRESOLVED = "eligibility_unresolved"

class CashFlowAvailabilityPeriodPosition(str, Enum):
    OPENING = "opening"
    CLOSING = "closing"

class CashFlowLineAggregationRole(str, Enum):
    PRESENTATION_CONTRIBUTOR = "presentation_contributor"
    SUBTOTAL = "subtotal"
    ANALYTIC = "analytic"
    RECONCILIATION = "reconciliation"

class CashFlowEvidenceKind(str, Enum):
    EXACT = "exact"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"

class CashFlowApplicability(str, Enum):
    APPLICABLE = "applicable"
    PROVEN_NOT_APPLICABLE = "proven_not_applicable"
    UNKNOWN = "unknown"

class CashFlowResultStatus(str, Enum):
    COMPLETE_RECONCILED = "complete_reconciled"
    COMPLETE_UNRECONCILED = "complete_unreconciled"
    PARTIAL_RECONCILED = "partial_reconciled"
    PARTIAL_UNRECONCILED = "partial_unreconciled"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID_INPUT = "invalid_input"
    INTEGRITY_FAILURE = "integrity_failure"

CashFlowResultBearingStatus = Literal[
    CashFlowResultStatus.COMPLETE_RECONCILED,
    CashFlowResultStatus.COMPLETE_UNRECONCILED,
    CashFlowResultStatus.PARTIAL_RECONCILED,
    CashFlowResultStatus.PARTIAL_UNRECONCILED,
    CashFlowResultStatus.INSUFFICIENT_DATA,
]

class CashFlowReconciliationStatus(str, Enum):
    RECONCILED = "reconciled"
    ROUNDING_DIFFERENCE = "rounding_difference"
    UNRECONCILED_NON_MATERIAL = "unreconciled_non_material"
    UNRECONCILED_MATERIAL = "unreconciled_material"
    NOT_PERFORMED_INCOMPLETE_COMPONENTS = "not_performed_incomplete_components"
    NOT_PERFORMED_INSUFFICIENT_DATA = "not_performed_insufficient_data"

class CashFlowEndpointReconciliationStatus(str, Enum):
    MATCHED = "matched"
    NOT_PERFORMED_INSUFFICIENT_DATA = "not_performed_insufficient_data"

class CashFlowLineCode(str, Enum):
    OPENING_CASH_AND_CASH_EQUIVALENTS = "opening_cash_and_cash_equivalents"
    NET_PROFIT = "net_profit"
    DEPRECIATION_AND_AMORTIZATION = "depreciation_and_amortization"
    OTHER_PROVEN_NON_CASH_ADJUSTMENTS = "other_proven_non_cash_adjustments"
    NON_CASH_ADJUSTMENT_TOTAL = "non_cash_adjustment_total"
    INVENTORY_MOVEMENT = "inventory_movement"
    TRADE_RECEIVABLES_MOVEMENT = "trade_receivables_movement"
    OTHER_OPERATING_ASSET_MOVEMENT = "other_operating_asset_movement"
    TRADE_PAYABLES_MOVEMENT = "trade_payables_movement"
    OTHER_OPERATING_LIABILITY_MOVEMENT = "other_operating_liability_movement"
    WORKING_CAPITAL_MOVEMENT_TOTAL = "working_capital_movement_total"
    OTHER_PROVEN_OPERATING_ADJUSTMENTS = "other_proven_operating_adjustments"
    INTEREST_EXPENSE_ACCRUAL_REVERSAL = "interest_expense_accrual_reversal"
    INTEREST_INCOME_ACCRUAL_REVERSAL = "interest_income_accrual_reversal"
    DIVIDEND_INCOME_ACCRUAL_REVERSAL = "dividend_income_accrual_reversal"
    CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL = "current_tax_expense_accrual_reversal"
    OPERATING_CASH_FLOW = "operating_cash_flow"
    PROVEN_PPE_ACQUISITIONS = "proven_ppe_acquisitions"
    PROVEN_PPE_DISPOSALS = "proven_ppe_disposals"
    PROVEN_INTANGIBLE_ACQUISITIONS = "proven_intangible_acquisitions"
    PROVEN_INTANGIBLE_DISPOSALS = "proven_intangible_disposals"
    PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS = "proven_financial_investment_movements"
    ESTIMATED_NET_INVESTMENT_MOVEMENT = "estimated_net_investment_movement"
    INVESTING_CASH_FLOW = "investing_cash_flow"
    PROVEN_BORROWING_PROCEEDS = "proven_borrowing_proceeds"
    PROVEN_DEBT_REPAYMENTS = "proven_debt_repayments"
    ESTIMATED_NET_DEBT_MOVEMENT = "estimated_net_debt_movement"
    PROVEN_EQUITY_CONTRIBUTIONS = "proven_equity_contributions"
    PROVEN_DIVIDENDS_PAID = "proven_dividends_paid"
    FINANCING_CASH_FLOW = "financing_cash_flow"
    AUTHORITATIVE_INTEREST_PAID = "authoritative_interest_paid"
    AUTHORITATIVE_INTEREST_RECEIVED = "authoritative_interest_received"
    AUTHORITATIVE_DIVIDENDS_RECEIVED = "authoritative_dividends_received"
    AUTHORITATIVE_INCOME_TAX_PAID = "authoritative_income_tax_paid"
    AUTHORITATIVE_FX_EFFECT = "authoritative_fx_effect"
    AUTHORITATIVE_RECLASSIFICATION_EFFECT = "authoritative_reclassification_effect"
    CALCULATED_NET_CASH_CHANGE = "calculated_net_cash_change"
    CLOSING_CASH_AND_CASH_EQUIVALENTS = "closing_cash_and_cash_equivalents"
    BALANCE_SHEET_NET_CASH_CHANGE = "balance_sheet_net_cash_change"
    RECONCILIATION_DIFFERENCE = "reconciliation_difference"
    FREE_CASH_FLOW = "free_cash_flow"

class CashFlowSourceRole(str, Enum):
    CURRENT_BALANCE_SHEET = "current_balance_sheet"
    PRIOR_BALANCE_SHEET = "prior_balance_sheet"
    CURRENT_INCOME_STATEMENT = "current_income_statement"
    CURRENT_TRIAL_BALANCE = "current_trial_balance"
    PRIOR_TRIAL_BALANCE = "prior_trial_balance"

class CashFlowSourceMode(str, Enum):
    DIRECT_DOCUMENT = "direct_document"
    TRIAL_BALANCE_DERIVED = "trial_balance_derived"
    MULTI_SOURCE_DERIVED = "multi_source_derived"

class CashFlowMappingMatchKind(str, Enum):
    EXACT_ACCOUNT_CODE = "exact_account_code"
    LONGEST_ACCOUNT_CODE_PREFIX = "longest_account_code_prefix"
    EXPLICIT_ACCOUNT_ROLE = "explicit_account_role"
    UNCLASSIFIED = "unclassified"

class CashFlowRoleSelectionRule(str, Enum):
    STATIC = "static"
    BANK_ACCOUNT_BRANCH_V1 = "bank_account_branch_v1"
    CASH_ELIGIBILITY_BRANCH_V1 = "cash_eligibility_branch_v1"
    GROSS_OR_RESIDUAL_INVESTING_V1 = "gross_or_residual_investing_v1"
    GROSS_OR_RESIDUAL_FINANCING_V1 = "gross_or_residual_financing_v1"
    ACTUAL_CASH_EVIDENCE_V1 = "actual_cash_evidence_v1"
    ACCRUAL_CASH_BRIDGE_V1 = "accrual_cash_bridge_v1"
    ACCRUAL_REVERSAL_V1 = "accrual_reversal_v1"
    RESTRICTED_RECLASSIFICATION_V1 = "restricted_reclassification_v1"
    NO_CASH_FLOW_V1 = "no_cash_flow_v1"

class CashFlowAccountRole(str, Enum):
    CASH_ON_HAND = "cash_on_hand"
    BANK_ACCOUNT_CANDIDATE = "bank_account_candidate"
    RESTRICTED_BANK_ASSET = "restricted_bank_asset"
    DEMAND_DEPOSIT = "demand_deposit"
    CASH_EQUIVALENT_INVESTMENT = "cash_equivalent_investment"
    CHECK_RECEIVABLE = "check_receivable"
    ISSUED_CHECK_OR_PAYMENT_ORDER = "issued_check_or_payment_order"
    OTHER_LIQUID_ASSET_CANDIDATE = "other_liquid_asset_candidate"
    POS_RECEIVABLE = "pos_receivable"
    OPERATING_RECEIVABLE = "operating_receivable"
    INVENTORY = "inventory"
    OTHER_OPERATING_ASSET = "other_operating_asset"
    OPERATING_PAYABLE = "operating_payable"
    OTHER_OPERATING_LIABILITY = "other_operating_liability"
    PPE = "ppe"
    INTANGIBLE_ASSET = "intangible_asset"
    FINANCIAL_INVESTMENT = "financial_investment"
    EQUITY_FINANCIAL_INVESTMENT = "equity_financial_investment"
    LONG_TERM_FINANCIAL_INVESTMENT = "long_term_financial_investment"
    NON_CASH_INVESTMENT_COMMITMENT = "non_cash_investment_commitment"
    BORROWING = "borrowing"
    EQUITY = "equity"
    NON_CASH_EQUITY = "non_cash_equity"
    TAX_PAYABLE = "tax_payable"
    TAX_RECEIVABLE = "tax_receivable"
    INTEREST_PAYABLE = "interest_payable"
    INTEREST_RECEIVABLE = "interest_receivable"
    DIVIDEND_PAYABLE = "dividend_payable"
    DIVIDEND_RECEIVABLE = "dividend_receivable"
    INTEREST_EXPENSE_ACCRUAL = "interest_expense_accrual"
    INTEREST_INCOME_ACCRUAL = "interest_income_accrual"
    DIVIDEND_INCOME_ACCRUAL = "dividend_income_accrual"
    CURRENT_TAX_EXPENSE_ACCRUAL = "current_tax_expense_accrual"
    DEFERRED_TAX_ACCRUAL = "deferred_tax_accrual"
    NON_CASH_ADJUSTMENT = "non_cash_adjustment"
    UNCLASSIFIED = "unclassified"

class CashFlowAccountDisposition(str, Enum):
    CASH_OR_CASH_EQUIVALENT = "cash_or_cash_equivalent"
    OPERATING_WORKING_CAPITAL = "operating_working_capital"
    INVESTING_FAMILY = "investing_family"
    FINANCING_FAMILY = "financing_family"
    PNL_CAPTURED_IN_NET_PROFIT = "pnl_captured_in_net_profit"
    PROVEN_NON_CASH = "proven_non_cash"
    PROVEN_NOT_RELEVANT = "proven_not_relevant"
    UNRESOLVED = "unresolved"

class CashFlowAccountFamilyCode(str, Enum):
    PPE_NET = "ppe_net"
    INTANGIBLE_NET = "intangible_net"
    FINANCIAL_INVESTMENT_NET = "financial_investment_net"
    BORROWING_GROSS = "borrowing_gross"

class CashFlowFamilyBalanceBasis(str, Enum):
    NET_CARRYING_ASSET = "net_carrying_asset"
    GROSS_LIABILITY_OBLIGATION = "gross_liability_obligation"

class CashFlowFamilyMemberKind(str, Enum):
    ASSET_GROSS = "asset_gross"
    ASSET_CONTRA = "asset_contra"
    LIABILITY_PRINCIPAL = "liability_principal"
    LIABILITY_CONTRA = "liability_contra"

class CashFlowNormalBalance(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"

class CashFlowWorkingCapitalKind(str, Enum):
    OPERATING_ASSET = "operating_asset"
    OPERATING_LIABILITY = "operating_liability"
    NOT_APPLICABLE = "not_applicable"

class CashEligibilityRule(str, Enum):
    AUTOMATIC_CASH = "automatic_cash"
    REQUIRES_ELIGIBILITY_EVIDENCE = "requires_eligibility_evidence"
    EXCLUDED = "excluded"
    NOT_APPLICABLE = "not_applicable"

class CashFlowStatementBasis(str, Enum):
    AS_OF = "as_of"
    FLOW_INTERVAL = "flow_interval"

class CashFlowAccountingBasisCode(str, Enum):
    TR_TDHP_ACCRUAL = "tr_tdhp_accrual"

class CashFlowBalanceSemantics(str, Enum):
    CLOSING_BALANCE = "closing_balance"
    PERIOD_MOVEMENT = "period_movement"
    UNKNOWN = "unknown"

class CashFlowZeroBalanceOmissionPolicy(str, Enum):
    EXPLICIT_ZERO_ROWS = "explicit_zero_rows"
    COMPLETE_SNAPSHOT_OMITS_ZERO = "complete_snapshot_omits_zero"
    UNKNOWN = "unknown"

class CashFlowDerivationCode(str, Enum):
    SOURCE_VALUE = "source_value"
    BALANCE_DELTA = "balance_delta"
    OPERATING_ASSET_SIGN_INVERSION = "operating_asset_sign_inversion"
    OPERATING_LIABILITY_SIGN_PRESERVED = "operating_liability_sign_preserved"
    NET_PROFIT_ACCRUAL_REVERSAL = "net_profit_accrual_reversal"
    INDIRECT_OPERATING_SUBTOTAL = "indirect_operating_subtotal"
    INVESTING_SUBTOTAL = "investing_subtotal"
    FINANCING_SUBTOTAL = "financing_subtotal"
    PRESENTATION_RECLASSIFICATION = "presentation_reclassification"
    NET_CASH_CHANGE_SUM = "net_cash_change_sum"
    BALANCE_SHEET_CASH_DELTA = "balance_sheet_cash_delta"
    RECONCILIATION_DIFFERENCE = "reconciliation_difference"
    FREE_CASH_FLOW_FROM_PROVEN_CAPEX = "free_cash_flow_from_proven_capex"

class CashFlowNonCashBridgeDomain(str, Enum):
    INVESTING_ASSET = "investing_asset"
    FINANCING_DEBT = "financing_debt"

class CashFlowNonCashBridgeKind(str, Enum):
    DEPRECIATION_OR_AMORTIZATION = "depreciation_or_amortization"
    IMPAIRMENT = "impairment"
    REVALUATION = "revaluation"
    TRANSFER_OR_RECLASSIFICATION = "transfer_or_reclassification"
    DISPOSAL_GAIN_OR_LOSS = "disposal_gain_or_loss"
    FX_OR_TRANSLATION = "fx_or_translation"
    NON_CASH_ACQUISITION_OR_LEASE_RECOGNITION = "non_cash_acquisition_or_lease_recognition"
    LEASE_MODIFICATION = "lease_modification"
    DEBT_TO_EQUITY_CONVERSION = "debt_to_equity_conversion"
    CAPITALIZED_INTEREST = "capitalized_interest"

class DependencyFailureBehavior(str, Enum):
    SKIP = "skip"
    INVOKE_DIAGNOSTIC_ONLY = "invoke_diagnostic_only"

class CashFlowWarningCode(str, Enum):
    MINIMUM_DATA_INCOMPLETE = "minimum_data_incomplete"
    ACCOUNT_UNCLASSIFIED = "account_unclassified"
    CASH_EQUIVALENT_ELIGIBILITY_UNPROVEN = "cash_equivalent_eligibility_unproven"
    NON_CASH_ADJUSTMENT_UNAVAILABLE = "non_cash_adjustment_unavailable"
    GROSS_MOVEMENT_UNAVAILABLE = "gross_movement_unavailable"
    ESTIMATED_NET_MOVEMENT_USED = "estimated_net_movement_used"
    RECONCILIATION_DIFFERENCE = "reconciliation_difference"
    MATERIAL_RECONCILIATION_DIFFERENCE = "material_reconciliation_difference"
    PRESENTATION_EVIDENCE_UNAVAILABLE = "presentation_evidence_unavailable"
    NEGATIVE_CASH_BALANCE = "negative_cash_balance"
    OVERDRAFT_RECLASSIFIED_TO_FINANCING = "overdraft_reclassified_to_financing"

class CashFlowErrorCode(str, Enum):
    INVALID_CONTRACT = "invalid_contract"
    PERIOD_NOT_COMPARABLE = "period_not_comparable"
    PERIOD_SELECTION_AMBIGUOUS = "period_selection_ambiguous"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_SCOPE_MISMATCH = "source_scope_mismatch"
    SOURCE_STATUS_INVALID = "source_status_invalid"
    SOURCE_DIGEST_MISMATCH = "source_digest_mismatch"
    SOURCE_CURRENCY_MISMATCH = "source_currency_mismatch"
    SOURCE_EVIDENCE_CONFLICT = "source_evidence_conflict"
    POLICY_VERSION_UNSUPPORTED = "policy_version_unsupported"
    MAPPING_REGISTRY_VERSION_UNSUPPORTED = "mapping_registry_version_unsupported"
    MAPPING_CONFLICT = "mapping_conflict"
    DECIMAL_NON_FINITE_OR_SCALE_INVALID = "decimal_non_finite_or_scale_invalid"
    PERSISTENCE_INTEGRITY_FAILURE = "persistence_integrity_failure"
    SOURCE_RESOLUTION_UNAVAILABLE = "source_resolution_unavailable"
    PERSISTENCE_UNAVAILABLE = "persistence_unavailable"
```

Taxonomy'ler kapalıdır. Bilinmeyen değer fail-closed contract error'dur.

Saf engine, 5.0C `ApplicationJsonValue` tipini import etmez. Kendi deeply-immutable cebiri şudur:

```python
CashFlowJsonScalar = None | bool | str | int | Decimal
CashFlowJsonValue = CashFlowJsonScalar | tuple["CashFlowJsonValue", ...] | "CashFlowJsonObject"

@dataclass(frozen=True)
class CashFlowJsonObject:
    # key'ler NFC-normalized, benzersiz ve code-point sırasındadır.
    items: tuple[tuple[str, CashFlowJsonValue], ...]

@dataclass(frozen=True)
class CashFlowIssue:
    code: CashFlowWarningCode | CashFlowErrorCode
    safe_metadata: CashFlowJsonObject
```

Float, mutable `dict/list`, non-string map key, duplicate/unsorted key ve raw exception bu cebirde yoktur. Application adapter bu local cebiri 5.0C/5.0C-v2 JSON cebirine tek yönlü projekte eder; engine application katmanına bağımlı olmaz.

## 8. Minimum Data Contract

```python
@dataclass(frozen=True)
class CashFlowPeriodDescriptor:
    period_id: UUID
    company_id: UUID
    tenant_id: UUID
    currency_code: str
    monetary_unit_multiplier: Decimal
    period_type: PeriodType
    start_date: date
    end_date: date
    annual_reporting_period_start_date: date
    annual_reporting_period_end_date: date
    months_covered: int
    status: PeriodStatus
    accounting_basis_code: CashFlowAccountingBasisCode
    accounting_policy_version: str
    ifrs18_early_adopted: bool

@dataclass(frozen=True)
class CashFlowSourceSnapshot:
    source_role: CashFlowSourceRole
    analysis_result_id: UUID | None
    same_run_engine_code: "OrchestrationEngineCodeV3 | None"
    analysis_type: AnalysisType
    source_mode: CashFlowSourceMode
    company_id: UUID
    period_id: UUID
    primary_document_id: UUID | None
    canonical_digest: str
    recomputed_result_payload_digest: str
    source_provenance_digest: str
    engine_schema_version: str | None
    engine_model_version: str
    status: AnalysisStatus
    error_message_is_null: bool
    statement_basis: CashFlowStatementBasis
    coverage_start_date: date | None
    coverage_end_date: date
    currency_code: str
    monetary_unit_multiplier: Decimal
    result_payload: CashFlowJsonObject

@dataclass(frozen=True)
class CashFlowAccountEvidence:
    source_role: CashFlowSourceRole
    source_analysis_result_id: UUID | None
    same_run_engine_code: "OrchestrationEngineCodeV3 | None"
    source_canonical_digest: str
    source_provenance_digest: str
    account_code: str
    canonical_account_role: CashFlowAccountRole | None
    account_disposition: CashFlowAccountDisposition
    disposition_proof_digest: str | None
    account_family_code: CashFlowAccountFamilyCode | None
    account_family_reference_digest: str | None
    family_member_kind: CashFlowFamilyMemberKind | None
    source_balance: Decimal | None
    source_debit_movement: Decimal | None
    source_credit_movement: Decimal | None
    source_currency_code: str
    source_unit_multiplier: Decimal
    functional_currency_code: str
    normalized_functional_currency_balance: Decimal | None
    normalized_functional_currency_debit_movement: Decimal | None
    normalized_functional_currency_credit_movement: Decimal | None
    translation_provenance_digest: str | None
    balance_semantics: CashFlowBalanceSemantics
    as_of_date: date
    complete_snapshot: bool
    zero_balance_omission_policy: CashFlowZeroBalanceOmissionPolicy
    maturity_days_at_acquisition: int | None
    is_restricted: bool | None
    is_repayable_on_demand: bool | None
    readily_convertible_to_known_amount: bool | None
    insignificant_value_change_risk: bool | None
    held_for_short_term_cash_commitments: bool | None
    integral_to_cash_management: bool | None
    restriction_preserves_cash_nature: bool | None

@dataclass(frozen=True)
class CashFlowNonCashBridgeComponent:
    component_reference_digest: str
    economic_event_reference_digest: str
    account_family_reference_digest: str
    account_family_code: CashFlowAccountFamilyCode
    family_balance_basis: CashFlowFamilyBalanceBasis
    domain: CashFlowNonCashBridgeDomain
    bridge_kind: CashFlowNonCashBridgeKind
    source_role: CashFlowSourceRole
    source_analysis_result_id: UUID | None
    same_run_engine_code: "OrchestrationEngineCodeV3 | None"
    source_canonical_digest: str
    source_provenance_digest: str
    statement_basis: CashFlowStatementBasis
    coverage_start_date: date
    coverage_end_date: date
    applicability: CashFlowApplicability
    evidence_kind: CashFlowEvidenceKind
    source_signed_residual_adjustment: Decimal | None
    source_currency_code: str
    source_unit_multiplier: Decimal
    functional_currency_code: str
    signed_residual_adjustment: Decimal | None
    translation_provenance_digest: str | None
    paired_transfer_reference_digest: str | None
    supporting_evidence_reference_digests: tuple[str, ...]

@dataclass(frozen=True)
class IndirectCashFlowInput:
    current_period: CashFlowPeriodDescriptor
    prior_period: CashFlowPeriodDescriptor | None
    current_balance_sheet: CashFlowSourceSnapshot | None
    prior_balance_sheet: CashFlowSourceSnapshot | None
    current_income_statement: CashFlowSourceSnapshot | None
    current_trial_balance: CashFlowSourceSnapshot | None
    prior_trial_balance: CashFlowSourceSnapshot | None
    account_evidence: tuple[CashFlowAccountEvidence, ...]
    noncash_bridge_components: tuple[CashFlowNonCashBridgeComponent, ...]
    account_evidence_bundle_digest: str
    opening_account_coverage_complete: bool
    closing_account_coverage_complete: bool
    mapping_registry_version: str
    accounting_policy_version: str
    presentation_policy: "CashFlowPresentationPolicy"

@dataclass(frozen=True)
class CashFlowPreResolvedContext:
    current_period: CashFlowPeriodDescriptor
    prior_period: CashFlowPeriodDescriptor | None
    prior_balance_sheet: CashFlowSourceSnapshot | None
    current_trial_balance: CashFlowSourceSnapshot | None
    prior_trial_balance: CashFlowSourceSnapshot | None
    account_evidence: tuple[CashFlowAccountEvidence, ...]
    noncash_bridge_components: tuple[CashFlowNonCashBridgeComponent, ...]
    pre_resolved_evidence_bundle_digest: str
    source_candidate_set_digest: str
    opening_account_coverage_complete: bool
    closing_account_coverage_complete: bool
    comparability_proof_digest: str | None
    mapping_registry_version: str
    accounting_policy_version: str
    presentation_policy: "CashFlowPresentationPolicy"

@dataclass(frozen=True)
class CashFlowComputationDraft:
    current_period: CashFlowPeriodDescriptor
    prior_period: CashFlowPeriodDescriptor | None
    line_items: tuple["CashFlowLineItem", ...]
    cash_availability_disclosures: tuple["CashFlowCashAvailabilityDisclosure", ...]
    evidence: tuple["CashFlowEvidenceReference", ...]
    source_lineage_references: tuple["CashFlowSourceLineageReference", ...]
    warnings: tuple[CashFlowIssue, ...]
    policy_version: str
    accounting_policy_version: str
    cash_equivalent_policy_version: str
    presentation_policy_version: str
    reconciliation_policy_version: str
    mapping_registry_version: str
```

`CashFlowComputationDraft` yalnız 4.5D→4.5E internal boundary'sidir; public application DTO, persisted payload veya ikinci source of truth değildir. 4.5D yalnız canonical leaf/contributor draft'ını üretir. 4.5E draft'ı completeness/reconciliation/status kurallarıyla tek `CashFlowResult`'a finalize eder; draft hiçbir store/owner adapter'ına verilemez.

Minimum data:

- current/prior Balance Sheet zorunlu;
- current Income Statement zorunlu;
- current detailed Trial Balance **veya** aynı account-code/balance semantics kapsamını taşıyan authoritative current canonical evidence zorunlu;
- prior detailed Trial Balance **veya** aynı account-code/balance semantics kapsamını taşıyan authoritative prior canonical evidence zorunlu;
- opening ve closing cash/equivalent tutarları aynı registry/policy sürümüyle çözülebilmelidir;
- current/prior Balance Sheet'in frozen result projection'ında `cash_and_equivalents` non-null, TRY-normalized Decimal olarak bulunmalı ve aşağıdaki endpoint parity kapısını geçmelidir.

V1 endpoint authority iki bağımsız kanıtın exact eşleşmesidir; tek kaynak kendi kendisiyle mutabakat yapamaz. `policy_defined_cash_and_equivalents`, selected detailed TB/equivalent account evidence'ın Section 11 allowlist/eligibility kurallarıyla leaf-level toplamıdır. `reported_balance_sheet_cash_and_equivalents`, current/prior `BalanceSheetAnalysisOutcomeV3.result_json.cash_and_equivalents` frozen projection'ından gelir; builder alanı yeniden hesaplamaz. OPENING için prior, CLOSING için current amount aynı TRY scale-2 finalization kuralından sonra exact eşit olmalıdır. Eşitse `CashFlowEndpointReconciliation(status=MATCHED, difference=Decimal("0.00"))`; ikisi de mevcut fakat farklıysa `SOURCE_EVIDENCE_CONFLICT` ve hiçbir Cash Flow result/owner yoktur. Balance Sheet field'i veya policy-defined endpoint eksikse teknik failure değil minimum-data eksikliğidir; `INSUFFICIENT_DATA` payload'ındaki ilgili endpoint record `NOT_PERFORMED_INSUFFICIENT_DATA`, `difference=None` taşır. Caller tolerance, “yakın değer”, latest source veya auto-reclassification fallback'i yoktur.

COMPLETE/PARTIAL payload exact iki endpoint record'unu `(OPENING, CLOSING)` sırasında ve ikisini de `MATCHED` olarak taşır. `INSUFFICIENT_DATA` da exact iki record taşır; doğrulanabilen amount/evidence korunabilir fakat status not-performed ve difference null'dır. Reported BS amount ile policy amount'ın farkı FX, restricted-cash reclassification veya “other” olarak otomatik kapatılamaz. Bu kapı sayesinde `balance_sheet_net_cash_change` yalnız TB-derived iki endpoint'in tautolojik farkı değildir; aynı zamanda iki bağımsız BS endpoint projection'ıyla doğrulanmış farktır.

`CASH_FLOW_SUPPORTED_ACCOUNTING_BASIS_MANIFEST_V1` exact tek row'dur: `(CashFlowAccountingBasisCode.TR_TDHP_ACCRUAL, "tr_tdhp_accrual/1.0.0")`. Bu literal, mevcut global Turkish account-code registry'sinin doğrulayabildiği accrual basis'i tanımlar; TMS/TFRS presentation profile'ı source basis hakkında daha geniş bir statutory-compliance iddiası oluşturmaz. Repository'de 4.5 öncesi authoritative accounting-basis literal/kolonu bulunmadığı için tasarım eski veriyi bu row'a otomatik backfill etmez. Missing metadata minimum-data eksikliğidir; manifest dışı/unknown/inflation-adjusted basis veya version `POLICY_VERSION_UNSUPPORTED` ile fail-closed'dur.

Authoritative period metadata `FinancialPeriod.accounting_basis_code`, `accounting_policy_version`, `annual_reporting_period_start_date`, `annual_reporting_period_end_date`, `ifrs18_early_adopted` alanlarından gelir; caller command veya filename'dan gelmez. Beş alan existing row'larda nullable kalır ve Cash Flow için hep-birlikte dolu olmalıdır. Annual start ≤ period start ≤ period end ≤ annual end zorunludur. Controlled internal data import bu metadata'yı source accounting policy kanıtıyla yazar; 4.5 public API/UI eklemez.

Bu minimum karşılanmıyorsa `INSUFFICIENT_DATA` sonucu üretilir. Eksik kaynak için sıfır veya en yakın dönem fallback'i yoktur.

Optional source alanları yalnız minimum-data diagnostic yolunu temsil eder. Numeric hesaplama başlamadan önce minimum set doğrulanır; eksikse line-level missing inventory taşıyan `INSUFFICIENT_DATA` döner ve hiçbir aritmetik yapılmaz.

`CashFlowPreResolvedContext`, application/integration adapter'ın run başlamadan önce DB'den çözdüğü yalnız prior/TB/evidence/policy bağlamıdır; henüz üretilmemiş current BS/IS içermez. `pre_resolved_evidence_bundle_digest` yalnız bu pre-run tuple'larını bağlar. V3 orchestrator, FS node'ları çağrıldıktan sonra `EngineResultEnvelopeV3.result` değerlerini bu context ile saf `build_indirect_cash_flow_input()` fonksiyonunda birleştirir; current FS'den çıkarılan bridge components ile pre-resolved tuple'ları conflict/dedup kurallarıyla merge edip final `IndirectCashFlowInput.account_evidence_bundle_digest` değerini yeniden üretir. Builder DB sorgulamaz. Böylece same-run source'lar pre-run varmış gibi gösterilmez.

`CashFlowSourceSnapshot` tam olarak bir source locator taşır: persisted kaynak için `analysis_result_id`, aynı terminal run içinde üretilecek current BS/IS için `same_run_engine_code`; ikisi birlikte veya ikisi de boş olamaz. `AS_OF` snapshot'ta `coverage_start_date=None`; `FLOW_INTERVAL` snapshot'ta `coverage_start_date` zorunlu ve `<= coverage_end_date` olur. Current BS/IS same-run envelope'larından gelir, prior kaynaklar authoritative persisted owner'dan yüklenir. Persistence aşaması same-run engine locator'ını staged `FinancialAnalysisResult` owner ID'sine çözer; canonical engine payload rewrite edilmez.

Her source snapshot ayrıca ayrı `source_provenance_digest` taşır. Bu digest yalnız root binding UUID listesi değildir; `CASH_FLOW_PROVENANCE_MAX_DEPTH_V1=16` ile bounded, cycle-rejected recursive same-period analysis-source closure'unun canonical proof'udur. Root, Cash Flow lineage'a bağlanan BS/IS/TB owner'dır; root owner UUID digest'e girmez ki same-run owner stage edilmeden proof üretilebilsin. Depth sayımı exact'tir: root analysis owner depth 0, doğrudan `source_analysis_result_id` descendant'ı depth 1, kabul edilen en uzun path 16 analysis edge/depth 16; depth 17'ye giriş reddedilir. Document edge'leri depth artırmaz. Python resolver/codec ile PostgreSQL recursive CTE aynı depth/cycle semantics'ini uygular. Root'un binding'leri ve `source_analysis_result_id` ile reachable bütün descendant owner/binding/document graph'ı company namespace lock'u altında çözülür. Her depth'te ve boundary'de cycle, depth>16, dangling edge, duplicate semantic edge veya aynı UUID için farklı semantic snapshot `SOURCE_EVIDENCE_CONFLICT`'tir; silent truncation/dedup yoktur.

Canonical closure projection declaration-order bir root record'u ve üç tuple taşır:

1. `root_semantics`: DB-generated root owner UUID'sini/timestamp'larını özellikle omit eden exact `cf.source_root_semantics.v1(company_id, period_id, primary_document_id_or_null, source_mode.value, analysis_type.value, engine_schema_version_or_null, engine_model_version, status.value, stored_canonical_result_digest_or_null, recomputed_result_payload_digest_or_null, error_message_is_null)` record'udur. Usable completed source'ta iki payload digest non-null/eşit ve error flag true'dur. Same-run root için bu alanların tamamı frozen engine outcome + verified owner planından owner stage edilmeden bilinir; persisted root aynı semantic values ile identical record üretir.
2. `root_edges`: yalnız depth-0 root owner'ın doğrudan `financial_analysis_result_sources` binding'leri `(role.value, locator_tag, locator_uuid)`; root parent UUID'si özellikle omit edilir ve canonical `(role.value, locator_tag, locator_uuid)` sırası kullanılır.
3. `analysis_nodes`: yalnız root edge'lerinden `source_analysis_result_id` ile ulaşılan descendant analysis owner'ları, depth 1..16; root owner bu tuple'a girmez. Row `(id, company_id, period_id, document_id-or-null, source_mode.value, analysis_type.value, engine_version, status.value, canonical_result_digest-or-null, recomputed_result_payload_digest-or-null, error_message_is_null, started_at_utc_microseconds, completed_at_utc_microseconds-or-null, created_at_utc_microseconds)` ve UUID sırasıdır. Expected completed source'ta `error_message_is_null=True`; raw message digest'e girmez.
4. `analysis_edges`: yalnız `analysis_nodes` içindeki descendant owner'ların outbound bindings'i `(parent_analysis_result_id, role.value, locator_tag, locator_uuid, company_id, period_id)`; parent UUID/role/tag/locator sırasıdır. Root binding burada tekrar edilmez. `documents`, root_edges ile descendant analysis_edges document locator'ları **ve** root/descendant owner primary `document_id` değerlerinin unique union'ıdır; snapshot row'u `(id, company_id, period_id, document_type.value, processing_status.value, content_sha256, file_size, mime_type, immutable_storage_key_digest)` ve document UUID sırasıdır.

`source_provenance_digest = sha256(b"cash-flow/source-provenance/v1\0" + canonical_bytes(cf.provenance_closure.v1(root_semantics, root_edges, analysis_nodes, analysis_edges, documents)))`. Empty root-edge/descendant set'in de root semantics'e bağlı tek canonical digest'i vardır. Same-run BS/IS için root semantics + edges planned owner/source tuple'ından, descendant closure authoritative persisted graph'tan owner stage edilmeden hesaplanır; aynı semantic graph persisted-root ve same-run-root yollarında identical bytes üretir. Root-edge duplication veya root owner'ın descendant tuple'a eklenmesi fail-closed'dur. Root primary document, source mode, analysis type, engine version/status veya payload digest değişikliği document union/edges aynı kalsa dahi digest'i zorunlu değiştirir. Bu domain legacy `owner_content_digest` veya `source_canonical_digest` değildir ve onları değiştirmez. Snapshot/evidence/bridge/lineage aynı source için bu üç digest'i exact eşleştirir; load/resume/reuse closure'u yeniden yürüyüp rehash eder.

`CashFlowAccountEvidence` caller-supplied bir liste değildir. Trusted source resolver, doğrulanmış source payload'dan üretir ve her satırı source role + locator + canonical digest'e bağlar. Her satırda `source_analysis_result_id XOR same_run_engine_code` zorunludur. Bundle digest, account evidence ile non-cash bridge component canonical satırlarının domain-separated ve sıralı ortak digest'idir. `balance_semantics=UNKNOWN`, incomplete snapshot veya bilinmeyen zero-omission policy minimum coverage sayılmaz.

`CashFlowNonCashBridgeComponent` de yalnız trusted resolver çıktısıdır ve aynı locator XOR/digest doğrulamasına tabidir. Exact domain manifestleri: investing asset için `DEPRECIATION_OR_AMORTIZATION, IMPAIRMENT, REVALUATION, TRANSFER_OR_RECLASSIFICATION, DISPOSAL_GAIN_OR_LOSS, FX_OR_TRANSLATION, NON_CASH_ACQUISITION_OR_LEASE_RECOGNITION, CAPITALIZED_INTEREST`; financing debt için `TRANSFER_OR_RECLASSIFICATION, FX_OR_TRANSLATION, NON_CASH_ACQUISITION_OR_LEASE_RECOGNITION, LEASE_MODIFICATION, DEBT_TO_EQUITY_CONVERSION, CAPITALIZED_INTEREST`. Her account-family/domain/kind üçlüsü exact bir component taşır: `APPLICABLE` ise source amount ile functional-currency `signed_residual_adjustment` ve `EXACT|DERIVED`; `PROVEN_NOT_APPLICABLE` ise iki amount exact `Decimal("0.00")`; `UNKNOWN` ise iki amount `None` ve `UNAVAILABLE`. Buradaki `signed_residual_adjustment` adı geriye dönük bir kısaltmadır ve **daima normalized functional-currency amount** demektir; source amount değildir. Başka kombinasyon constructor error'dur. Tuple canonical `(domain.value, account_family_reference_digest, bridge_kind.value, component_reference_digest)` sırasındadır; aynı domain/key'de duplicate/reference reuse conflict'tir.

Movement component zaman kanıtı kapalıdır: source role yalnız `CURRENT_INCOME_STATEMENT` veya `CURRENT_TRIAL_BALANCE`, `statement_basis=FLOW_INTERVAL`, `coverage_start_date/coverage_end_date` exact current flow window olmalıdır. `PRIOR_*`, `CURRENT_BALANCE_SHEET`, `AS_OF`, gap, overlap veya partial interval component amount'ı current bridge'e giremez ve `SOURCE_EVIDENCE_CONFLICT` üretir. Transfer component'ı karşı family'de aynı paired digest'li ters işaretli eş taşır ve toplamı exact zero'dır. Disposal gain/loss component'ı carrying-amount derecognition ve gain/loss source proof digest'lerini `supporting_evidence_reference_digests` içinde exact ikili olarak taşımadan applicable olamaz.

`economic_event_reference_digest` aynı olayı asset/debt correction domain'lerinde veya OCF accrual/non-cash reversal proof'unda bağlayabilir. Bu kontrollü proof reuse yalnız correction hesabıdır; aynı event exact bir `PRESENTATION_CONTRIBUTOR`'dan fazlasına amount sağlayamaz. Capitalized interest asset component'ı actual signed asset-balance etkisini taşır. Accrued/capitalized ama ödenmemiş faiz eş economic-event digest'li debt component'ıyla iki residualdan çıkarılır ve cash contributor üretmez; gerçekten ödenmiş capitalized interest ise asset correction yanında yalnız authoritative actual-interest-paid line'ında presentation contributor olur. DTO proof'u authorization veya cash-flow amount'ı değildir; engine yalnız kapalı bridge/dedup kurallarında kullanır.

Her account evidence satırı tek bir source snapshot'taki tek bakiyeyi temsil eder. Engine opening ve closing satırlarını `(account_code, canonical_account_role)` anahtarıyla eşler; tek satırın iki dönemi temsil etmesi yasaktır. Resolver source-side ekonomik bakiyeyi mapping'deki normal balance'a göre üretir: debit-normal hesapta `debit_closing-credit_closing`, credit-normal hesapta `credit_closing-debit_closing`. Abnormal bakiye negatif kalır; `abs`, clamp veya sessiz zero yasaktır ve deterministic warning/evidence taşır. `source_debit_movement/source_credit_movement` yalnız source semantics bunların ayrı flow-interval hareketi olduğunu kanıtlıyorsa dolu olabilir; closing balance yerine kullanılamaz.

Parasal otorite V1'de tek ve kapalıdır. Durable functional-currency kaynağı yalnız authoritative `Company.currency` alanıdır; V1 production gate'i bunun exact `"TRY"` olmasını zorunlu kılar. Monetary-unit authority caller, document, period veya BS/IS payload'ı değildir: `CASH_FLOW_MONETARY_UNIT_MULTIPLIER_V1 = Decimal("1")` policy sabitidir. Mevcut BS/IS/TB financial-result codec'lerinin parasal alanları major TRY unit olarak yorumlanır; desteklenen engine model sürümü bu semantiği compatibility manifestinde bağlar. `CashFlowPeriodDescriptor.monetary_unit_multiplier`, `CashFlowSourceSnapshot.monetary_unit_multiplier`, evidence/bridge `source_unit_multiplier` alanları bu authoritative sabitin audit snapshot'ıdır ve exact `Decimal("1")` olmak zorundadır. Payload-declared veya caller-declared multiplier okunmaz.

Parasal arithmetic'in tek authoritative alanları `normalized_functional_currency_balance`, `normalized_functional_currency_debit_movement` ve `normalized_functional_currency_credit_movement`'tır; source-side üçlü hesapta doğrudan kullanılmaz. V1'de `source_currency_code == functional_currency_code == Company.currency == "TRY"`, `source_unit_multiplier == Decimal("1")`, normalized değer karşılık gelen source değere exact eşit ve `translation_provenance_digest=None` olmalıdır. Foreign-currency source, multiplier≠1, translation proof'unun non-null olması, missing source value'ın normalized zero'ya çevrilmesi veya source/normalized mismatch `SOURCE_CURRENCY_MISMATCH` üretir. Döviz çevrimi ve presentation-unit scaling V1 kapsamı dışıdır; sessiz kur, 1.0 fallback veya double scaling yoktur.

Bridge component'ı aynı invariant'ı taşır: `signed_residual_adjustment == source_signed_residual_adjustment`, iki currency exact `"TRY"`, multiplier exact `Decimal("1")` ve translation digest null'dır. `supporting_evidence_reference_digests` lowercase SHA-256, code-point sorted, unique tuple'dır; caller/DB insertion order korunmaz. Engine residual formüllerinde yalnız normalized `signed_residual_adjustment` kullanılır.

Same-run BS/IS field projection'ında her parasal field exact `(field_code, source_amount, source_currency_code="TRY", source_unit_multiplier=Decimal("1"), functional_currency_code="TRY", normalized_amount=source_amount, translation_provenance_digest=None)` biçimindeki `CURRENT_FS_MONETARY_PROJECTION_V1` row'una dönüştürülür. Currency ve multiplier payload'dan okunmaz; trusted builder bunları locked Company snapshot + V1 sabitinden üretir ve frozen source-engine model semantiğini compatibility manifestiyle doğrular. Net profit, depreciation/amortization, actual-cash bridge amount'ları ve diğer bütün authoritative monetary leaf'ler bu projection/bridge invariant'ından geçmeden line item'a veya arithmetic'e giremez.

Her period position için source seçimi kapalıdır: usable detailed Trial Balance varsa account-level evidence yalnız o TB'den materialize edilir; TB yoksa semantic-equivalent canonical evidence fallback kullanılır. Aynı dönem için iki kaynağın satırları merge edilmez. `(period_position, account_code, canonical_account_role)` başına tam bir observation zorunludur; source içindeki exact duplicate dahil her duplicate veya conflicting value `SOURCE_EVIDENCE_CONFLICT` failure olur, dedup yapılmaz. Opening/closing pair yalnız bu seçilmiş unique observation setlerinden kurulur.

Production scope'taki `tenant_id`, caller'ın verdiği UUID değildir. Trusted scope adapter 5.0E `tenant_key` değerini authoritative `security_tenants.id` UUID'sine çözer, `Company.tenant_id` ile exact karşılaştırır ve yalnız bu internal UUID'yi period/source/lineage portlarına verir. Missing, ambiguous, inactive veya mismatch mapping, zero-lineage `INSUFFICIENT_DATA` dahil her yolda fail-closed'dur.

## 9. Comparable-Period Policy

`ComparablePeriodResolverPort`, caller'ın “prior period” seçimini körlemesine kabul etmez. Aşağıdaki kontrollerin tamamı zorunludur:

| Kural | Exact davranış |
|---|---|
| Tenant/company | `tenant_id` ve `company_id` birebir eşit; cross-tenant/cross-company fail-closed |
| Currency | ISO 4217 currency code birebir eşit |
| Accounting basis | `accounting_basis_code` ve `accounting_policy_version` birebir eşit |
| Period status | Her iki dönem de `PeriodStatus.CLOSED`; diğer status'ler karşılaştırılabilir değildir |
| Statement basis | BS kaynakları `AS_OF`; current IS `FLOW_INTERVAL` olmalı |
| Flow window | `flow_start = prior_balance_sheet.coverage_end_date + 1 gün`; `flow_end = current_balance_sheet.coverage_end_date`; current IS coverage bu aralıkla birebir eşit |
| Period type | Aşağıdaki kapalı compatibility manifestinden biri sağlanmalı |
| Chronology | `prior BS as_of < current BS as_of` |
| Overlap | Her türlü overlap kesin ret |
| Gap | Opening BS as-of ile IS flow start ve IS flow end ile closing BS as-of arasında gap olamaz |
| Selection | Scope içinde bütün kuralları sağlayan tam bir aday varsa seçilir |
| Ambiguity | Birden fazla tam aday varsa `PERIOD_SELECTION_AMBIGUOUS`; tie-break veya latest fallback yok |
| Missing | Hiç aday yoksa `INSUFFICIENT_DATA`; teknik failure değil |
| Source status | Financial source `COMPLETED` ve payload dolu olmalı |
| Digest | Her source yüklenirken SHA-256 canonical digest tekrar hesaplanır ve constant-time karşılaştırılır |
| Policy consistency | Current/prior cash hesapları aynı mapping/accounting policy version ile yeniden materialize edilir |

Kapalı period compatibility manifesti:

| Current flow period | Opening BS period | Ek koşul |
|---|---|---|
| `YEAR_END` | `YEAR_END` | current flow tam yıllık aralık |
| `MONTHLY` | `MONTHLY` | tek, kesintisiz aylık aralık **ve** `coverage_start_date > annual_reporting_period_start_date`; ilk fiscal ay bu row'a giremez |
| `QUARTER` discrete | önceki `QUARTER` | current IS yalnız o çeyreğin flow interval'ı **ve** `coverage_start_date > annual_reporting_period_start_date`; ilk fiscal çeyrek bu row'a giremez |
| İlk fiscal `MONTHLY` interval | önceki annual `YEAR_END` | `coverage_start_date == annual_reporting_period_start_date`; opening BS annual start'tan bir gün önce |
| İlk fiscal `QUARTER` discrete | önceki annual `YEAR_END` | `coverage_start_date == annual_reporting_period_start_date`; opening BS annual start'tan bir gün önce; exact ilk fiscal-quarter flow window |
| Fiscal `QUARTER` cumulative/YTD | önceki annual `YEAR_END` | current IS `annual_reporting_period_start_date` → current quarter end |
| `TEMPORARY_TAX` cumulative | önceki annual `YEAR_END` | current IS `annual_reporting_period_start_date` → temporary-tax end |
| `CUSTOM` | `CUSTOM` | explicit coverage metadata ve kesintisiz exact window |

`discrete`/`cumulative` niteliği filename, takvim ayı veya period number'dan tahmin edilmez; trusted source coverage metadata'sında bulunmalıdır. “İlk fiscal ay/çeyrek” yalnız `coverage_start_date == annual_reporting_period_start_date` ile belirlenir ve generic MONTHLY/QUARTER row'larıyla **mutually exclusive**'dir. İlk fiscal interval'da aynı as-of scope'ta bir MONTHLY/QUARTER candidate bulunsa bile o candidate eligibility aşamasında elenir; annual `YEAR_END` exact row tek eligible row'dur ve gereksiz ambiguity üretilmez. İlk-fiscal olmayan interval'da annual row elenir. 1 Ocak/January/Q1 ve 31 Aralık ifadeleri sadece annual start=1 Ocak olan şirketler için örnektir, normatif seçim kuralı değildir. Örneğin 1 Temmuz başlayan mali yılda ilk aylık interval 1–31 Temmuz, ilk çeyrek 1 Temmuz–30 Eylül ve opening annual `YEAR_END` as-of 30 Haziran'dır. Başka kombinasyon `PERIOD_NOT_COMPARABLE` olur. Opening BS'in dönem süresinin current flow süresiyle aynı olması gerekmez; bağlayıcı olan exact as-of/flow-window eşleşmesidir.

`latest available period`, eksik aralığı atlama ve daha eski bir dönemle otomatik karşılaştırma yasaktır.

Period proof canonicalization exact'tir. `CashFlowPeriodDescriptor` declaration-order alanları strict codec'in `cf.period_descriptor.v1` record'u olarak encode edilir; `period_descriptor_digest = sha256(b"cash-flow/period-descriptor/v1\0" + canonical_record_bytes).hexdigest()`. `comparability_proof_digest`, `cash-flow/comparability-proof/v1\0` prefix'inden sonra şu exact ordered object'i hashler: `policy_version="1.0.0"`, current descriptor digest, prior descriptor digest, opening BS coverage end, current flow coverage start/end, closing BS coverage end, current IS source canonical digest, current/prior BS source canonical digest'leri ve selected compatibility-manifest row ID. Missing/extra key, non-canonical digest veya flow-window mismatch fail-closed'dur. Resolver 0 adayda proof üretmez, 1 adayda bu proof'u üretir, >1 adayda hash/tie-break yapmadan `PERIOD_SELECTION_AMBIGUOUS` döndürür.

## 10. CashFlowAccountMappingRegistry

Registry saf Python, global, kapalı ve versioned'dır; SQLAlchemy içermez. Company/tenant override v1'de yoktur.

```python
@dataclass(frozen=True)
class CashFlowAccountMapping:
    mapping_id: str
    match_kind: CashFlowMappingMatchKind
    account_code_or_prefix: str | None
    explicit_account_role: CashFlowAccountRole | None
    resolved_account_role: CashFlowAccountRole
    code_normal_balance: CashFlowNormalBalance | None
    account_family_code: CashFlowAccountFamilyCode | None
    family_member_kind: CashFlowFamilyMemberKind | None
    model_version_introduced: str

@dataclass(frozen=True)
class CashFlowRoleBehavior:
    role: CashFlowAccountRole
    selection_rule: CashFlowRoleSelectionRule
    static_activity: CashFlowActivity | None
    possible_activities: tuple[CashFlowActivity, ...]
    candidate_line_codes: tuple[CashFlowLineCode, ...]
    normal_balance: CashFlowNormalBalance | None
    working_capital_kind: CashFlowWorkingCapitalKind
    cash_eligibility_rule: CashEligibilityRule
    gross_movement_evidence_required: bool
    model_version_introduced: str

@dataclass(frozen=True)
class CashFlowAccountFamilyDefinition:
    family_code: CashFlowAccountFamilyCode
    domain: CashFlowNonCashBridgeDomain
    balance_basis: CashFlowFamilyBalanceBasis
    members: tuple[tuple[str, CashFlowFamilyMemberKind], ...]
    model_version_introduced: str

CASH_FLOW_MAPPING_REGISTRY_VERSION = "1.0.0"
```

Precedence:

1. exact account-code override;
2. longest account-code prefix;
3. explicit canonical account-role mapping;
4. `UNCLASSIFIED`.

Eşit precedence ve eşit uzunlukta iki mapping row `MAPPING_CONFLICT` üretir. Bir account aynı registry version içinde yalnız tek `CashFlowAccountMapping` row'una ve onun resolved role'ü üzerinden exact tek `CashFlowRoleBehavior` row'una atanır. Actual line seçimi behavior'ın kapalı `selection_rule` + `candidate_line_codes` sözleşmesiyle yapılır. Duplicate mapping/behavior import anında reddedilir. Account-name yalnız audit/evidence olarak taşınabilir; karar veremez.

V1 compiled registry iki literal manifestin deterministic birleşimidir. `PFX` normalized ASCII-digit prefix, `ROLE` yalnız trusted canonical source role demektir. Account name hiçbir role üretmez.

Account-code normalization grammar kapalıdır. Raw code exact `^[0-9]+(?:[.\-/ ][0-9]+)*$` regex'ine uyan, 1–64 karakterlik ASCII string olmak zorundadır; leading/trailing whitespace trim edilmez ve reddedilir. Yalnız `.`, `-`, `/` ve tek ASCII space segment separator'ı olabilir; repeated/leading/trailing separator, tab/newline, Unicode whitespace, Unicode digit, sign, harf ve başka punctuation reddedilir. Separator'lar kaldırılır, kalan 1–64 ASCII digit canonical code olur; integer'a çevrilmez ve leading zero korunur. Manifest pattern'ları zaten canonical ASCII digit'tir. Exact-match canonical string equality, prefix-match `canonical_code.startswith(pattern)` ile yapılır; aynı precedence'ta longest pattern kazanır. Malformed raw code `SOURCE_EVIDENCE_CONFLICT`, iki eş uzunluklu winning row `MAPPING_CONFLICT` üretir; silent sanitize/fallback yoktur.

`CASH_FLOW_CODE_ROLE_MANIFEST_V1` exact ordered rows:

| mapping_id | match/pattern | resolved role | normal |
|---|---|---|---|
| `cf100` | PFX `100` | `CASH_ON_HAND` | DEBIT |
| `cf101` | PFX `101` | `CHECK_RECEIVABLE` | DEBIT |
| `cf102` | PFX `102` | `BANK_ACCOUNT_CANDIDATE` | DEBIT |
| `cf103` | PFX `103` | `ISSUED_CHECK_OR_PAYMENT_ORDER` | CREDIT |
| `cf108` | PFX `108` | `OTHER_LIQUID_ASSET_CANDIDATE` | DEBIT |
| `cf110` | PFX `110` | `EQUITY_FINANCIAL_INVESTMENT` | DEBIT |
| `cf111` | PFX `111` | `FINANCIAL_INVESTMENT` | DEBIT |
| `cf112` | PFX `112` | `FINANCIAL_INVESTMENT` | DEBIT |
| `cf118` | PFX `118` | `FINANCIAL_INVESTMENT` | DEBIT |
| `cf119` | PFX `119` | `NON_CASH_ADJUSTMENT` | CREDIT |
| `cf120` | PFX `120` | `OPERATING_RECEIVABLE` | DEBIT |
| `cf121` | PFX `121` | `OPERATING_RECEIVABLE` | DEBIT |
| `cf15` | PFX `15` | `INVENTORY` | DEBIT |
| `cf158` | PFX `158` | `NON_CASH_ADJUSTMENT` | CREDIT |
| `cf159` | PFX `159` | `OTHER_OPERATING_ASSET` | DEBIT |
| `cf180` | PFX `180` | `OTHER_OPERATING_ASSET` | DEBIT |
| `cf190` | PFX `190` | `OTHER_OPERATING_ASSET` | DEBIT |
| `cf191` | PFX `191` | `OTHER_OPERATING_ASSET` | DEBIT |
| `cf192` | PFX `192` | `OTHER_OPERATING_ASSET` | DEBIT |
| `cf240` | PFX `240` | `LONG_TERM_FINANCIAL_INVESTMENT` | DEBIT |
| `cf241` | PFX `241` | `NON_CASH_ADJUSTMENT` | CREDIT |
| `cf242` | PFX `242` | `LONG_TERM_FINANCIAL_INVESTMENT` | DEBIT |
| `cf243` | PFX `243` | `NON_CASH_INVESTMENT_COMMITMENT` | CREDIT |
| `cf244` | PFX `244` | `NON_CASH_ADJUSTMENT` | CREDIT |
| `cf245` | PFX `245` | `LONG_TERM_FINANCIAL_INVESTMENT` | DEBIT |
| `cf246` | PFX `246` | `NON_CASH_INVESTMENT_COMMITMENT` | CREDIT |
| `cf247` | PFX `247` | `NON_CASH_ADJUSTMENT` | CREDIT |
| `cf248` | PFX `248` | `LONG_TERM_FINANCIAL_INVESTMENT` | DEBIT |
| `cf249` | PFX `249` | `NON_CASH_ADJUSTMENT` | CREDIT |
| `cf25` | PFX `25` | `PPE` | DEBIT |
| `cf257` | PFX `257` | `NON_CASH_ADJUSTMENT` | CREDIT |
| `cf26` | PFX `26` | `INTANGIBLE_ASSET` | DEBIT |
| `cf268` | PFX `268` | `NON_CASH_ADJUSTMENT` | CREDIT |
| `cf300` | PFX `300` | `BORROWING` | CREDIT |
| `cf301` | PFX `301` | `BORROWING` | CREDIT |
| `cf303` | PFX `303` | `BORROWING` | CREDIT |
| `cf304` | PFX `304` | `BORROWING` | CREDIT |
| `cf305` | PFX `305` | `BORROWING` | CREDIT |
| `cf306` | PFX `306` | `BORROWING` | CREDIT |
| `cf309` | PFX `309` | `BORROWING` | CREDIT |
| `cf32` | PFX `32` | `OPERATING_PAYABLE` | CREDIT |
| `cf322` | PFX `322` | `NON_CASH_ADJUSTMENT` | DEBIT |
| `cf34` | PFX `34` | `OTHER_OPERATING_LIABILITY` | CREDIT |
| `cf361` | PFX `361` | `OTHER_OPERATING_LIABILITY` | CREDIT |
| `cf370` | PFX `370` | `TAX_PAYABLE` | CREDIT |
| `cf371` | PFX `371` | `TAX_RECEIVABLE` | DEBIT |
| `cf400` | PFX `400` | `BORROWING` | CREDIT |
| `cf401` | PFX `401` | `BORROWING` | CREDIT |
| `cf405` | PFX `405` | `BORROWING` | CREDIT |
| `cf407` | PFX `407` | `BORROWING` | CREDIT |
| `cf409` | PFX `409` | `BORROWING` | CREDIT |
| `cf500` | PFX `500` | `EQUITY` | CREDIT |
| `cf520` | PFX `520` | `EQUITY` | CREDIT |
| `cf570` | PFX `570` | `NON_CASH_EQUITY` | CREDIT |
| `cf580` | PFX `580` | `NON_CASH_EQUITY` | DEBIT |
| `cf590` | PFX `590` | `NON_CASH_EQUITY` | CREDIT |
| `cf591` | PFX `591` | `NON_CASH_EQUITY` | DEBIT |
| `cf640` | PFX `640` | `DIVIDEND_INCOME_ACCRUAL` | CREDIT |
| `cf641` | PFX `641` | `DIVIDEND_INCOME_ACCRUAL` | CREDIT |
| `cf642` | PFX `642` | `INTEREST_INCOME_ACCRUAL` | CREDIT |
| `cf691` | PFX `691` | `CURRENT_TAX_EXPENSE_ACCRUAL` | DEBIT |

`CASH_FLOW_ACCOUNT_FAMILY_MANIFEST_V1` de global registry'nin immutable parçasıdır. Aile üyeliği account name'dan veya runtime benzerliğinden türetilmez; yalnız winning `mapping_id` üzerinden gelir. Exact rows:

| family code | domain / balance basis | member mapping IDs |
|---|---|---|
| `PPE_NET` | `INVESTING_ASSET / NET_CARRYING_ASSET` | `ASSET_GROSS=(cf25)`; `ASSET_CONTRA=(cf257)` |
| `INTANGIBLE_NET` | `INVESTING_ASSET / NET_CARRYING_ASSET` | `ASSET_GROSS=(cf26)`; `ASSET_CONTRA=(cf268)` |
| `FINANCIAL_INVESTMENT_NET` | `INVESTING_ASSET / NET_CARRYING_ASSET` | `ASSET_GROSS=(cf110,cf111,cf112,cf118,cf240,cf242,cf245,cf248)`; `ASSET_CONTRA=(cf119,cf241,cf244,cf247,cf249)` |
| `BORROWING_GROSS` | `FINANCING_DEBT / GROSS_LIABILITY_OBLIGATION` | `LIABILITY_PRINCIPAL=(cf300,cf301,cf303,cf304,cf305,cf306,cf309,cf400,cf401,cf405,cf407,cf409)`; `LIABILITY_CONTRA=()` |

Bir mapping ID exact bir aile/member-kind row'unda en fazla bir kez bulunur. Yukarıdaki member row'ları `CashFlowAccountMapping.account_family_code/family_member_kind` alanlarına compile edilir; manifest dışı mapping'lerde iki alan da null'dır. Longest-prefix sonucu `cf257`/`cf268` gibi contra row kazanır, dolayısıyla parent `cf25`/`cf26` gross ailesine ikinci kez girmez. `cf302/cf308/cf402/cf408` V1'de hâlâ authoritative borrowing değildir: non-zero ise `UNRESOLVED` olur, `BORROWING_GROSS` residual'ına alınmaz ve financing estimate/statement completeness'ini kapatır. Bu konservatif ret, contra bakiyeyi principal sayarak cash movement uydurulmasını engeller.

Her family definition için `account_family_reference_digest = sha256(b"cash-flow/account-family/v1\0" + canonical_bytes(cf.account_family.v1(family_code, domain, balance_basis, mapping_registry_version, ordered_members))).hexdigest()` olur. `ordered_members`, yukarıdaki family-row sırası ve her row içinde literal mapping-ID sırasıdır; account balances digest'e girmez. Current/prior `CashFlowAccountEvidence` aynı winning mapping ID için aynı family code/member kind/reference digest'i taşır. Aile dışı disposition'da bu üç alan hep birlikte null'dır. Bridge component'ın family code/basis/reference digest'i bu exact definition ile birebir eşleşmeden residual hesabına giremez.

Family balance hesabı source economic-balance değerlerinden ve yalnız selected current/prior complete observation setinden yapılır:

```text
NET_CARRYING_ASSET family_balance =
    sum(ASSET_GROSS economic balances)
  - sum(ASSET_CONTRA economic balances)

GROSS_LIABILITY_OBLIGATION family_balance =
    sum(LIABILITY_PRINCIPAL economic balances)
  - sum(LIABILITY_CONTRA economic balances)
```

Contra economic balance kendi CREDIT/DEBIT normaline göre önce pozitif magnitude olarak materialize edilir, sonra yalnız yukarıdaki family formula'sında çıkarılır; `abs`, sign inference veya aynı contra'nın non-cash bridge'de ikinci kez balance component'ı olması yasaktır. Bir family member current/prior source'ta eksikse ancak complete-snapshot + exact zero-omission proof ile sıfır sayılabilir. Missing/duplicate member, farklı family digest, unresolved non-zero candidate veya incomplete opening/closing coverage ilgili family residual'ını `UNAVAILABLE` yapar. Pure-depreciation vakasında PPE net-carrying delta `-D`, exact depreciation bridge'i `-D` olduğundan `-(asset_delta - signed_noncash) = 0`; cf25 gross ile cf257 contra iki kez sayılmaz.

`CASH_FLOW_ROLE_BEHAVIOR_MANIFEST_V1` exact rows (`OA/OL/NA` working-capital kind; `A/R/X/NA` cash eligibility automatic/requires evidence/excluded/not-applicable):

Tablo bir okunabilir projection'dır; canonical manifest serbest metni serialize etmez. Code-role tablosundaki `normal` sütunu code-specific ekonomik bakiye yönüdür ve canonical `CashFlowAccountMapping.code_normal_balance` alanına kayıpsız yazılır; discard edilmez. `PFX/EXACT` code row'unda bu alan zorunlu, `ROLE` row'unda null'dır. `CashFlowRoleBehavior.normal_balance` ise role-genel runtime davranışıdır: non-null ise code-specific değerle exact eşleşir; null ise resolver matched code row'un `code_normal_balance` değerini kullanır, ROLE mapping'de ise authoritative source-proven normal-balance evidence zorunlu olur. Böylece `NON_CASH_ADJUSTMENT`, `NON_CASH_EQUITY` ve accrual role'lerinin debit/credit code ayrımı korunur; null hiçbir zaman “normal bilinmiyor ama varsay” anlamına gelmez. Compile kuralları kapalıdır: uppercase tek activity → `STATIC`; `evidence-selected` → `BANK_ACCOUNT_BRANCH_V1`; `INVESTING unless eligible` → `CASH_ELIGIBILITY_BRANCH_V1`; PPE/intangible/financial-investment gross rows → `GROSS_OR_RESIDUAL_INVESTING_V1`; borrowing gross row → `GROSS_OR_RESIDUAL_FINANCING_V1`; equity → `ACTUAL_CASH_EVIDENCE_V1`; `policy-selected` ve tax/dividend payable/receivable bridge → `ACCRUAL_CASH_BRIDGE_V1`; `OPERATING reversal` → `ACCRUAL_REVERSAL_V1`; restricted-bank row → `RESTRICTED_RECLASSIFICATION_V1`; disclosure/known-excluded/none rows → `NO_CASH_FLOW_V1`. Conditional rule'da `static_activity=None`; `possible_activities` declaration-order exact branchesi taşır. `branch-specific` role behavior normal'i null'dır ve matched code-specific DEBIT/CREDIT veya source proof uygulanır; `flow/source-proven` role behavior normal'i de null'dır ve aynı fail-closed kaynak kuralını kullanır. Virgülle gruplanmış role cell'i declaration order'da ayrı row'lara; slash candidate/normal değerleri soldan sağa birebir genişler. Her `CashFlowAccountRole` exact bir canonical behavior row üretmezse manifest construction fail-closed'dur.

`possible_activities` mapping'i de literal ve ordered'dır: `STATIC=(static_activity,)`; bank branch `=(CASH_AND_CASH_EQUIVALENTS, INVESTING, FINANCING, RECLASSIFICATION_EFFECT, UNCLASSIFIED)`; eligibility branch `=(CASH_AND_CASH_EQUIVALENTS, INVESTING)`; gross/residual investing `=(INVESTING,)`; gross/residual financing ve equity actual-cash `=(FINANCING,)`; accrual-cash bridge `=(OPERATING, INVESTING, FINANCING)`; accrual reversal `=(OPERATING,)`; restricted reclassification `=(RECLASSIFICATION_EFFECT, UNCLASSIFIED)`; no-cash-flow `=(UNCLASSIFIED,)`.

Candidate-line compiler serbest metin parse etmez. Readable tablodaki her hücre aşağıdaki exact token'dan birine build-time'da çevrilir; token/value manifestte yoksa construction fail-closed'dur:

```text
NO_LINES = ()
OPENING_CLOSING = (OPENING_CASH_AND_CASH_EQUIVALENTS,
                   CLOSING_CASH_AND_CASH_EQUIVALENTS)
BANK_BRANCH_LINES = (OPENING_CASH_AND_CASH_EQUIVALENTS,
                     CLOSING_CASH_AND_CASH_EQUIVALENTS,
                     PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS,
                     PROVEN_BORROWING_PROCEEDS,
                     PROVEN_DEBT_REPAYMENTS,
                     AUTHORITATIVE_RECLASSIFICATION_EFFECT)
ELIGIBILITY_BRANCH_LINES = (OPENING_CASH_AND_CASH_EQUIVALENTS,
                            CLOSING_CASH_AND_CASH_EQUIVALENTS,
                            PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS)
PPE_GROSS_LINES = (PROVEN_PPE_ACQUISITIONS, PROVEN_PPE_DISPOSALS)
INTANGIBLE_GROSS_LINES = (PROVEN_INTANGIBLE_ACQUISITIONS,
                          PROVEN_INTANGIBLE_DISPOSALS)
BORROWING_GROSS_LINES = (PROVEN_BORROWING_PROCEEDS, PROVEN_DEBT_REPAYMENTS)
TAX_BRIDGE_LINES = (AUTHORITATIVE_INCOME_TAX_PAID,)
INTEREST_PAYABLE_BRIDGE_LINES = (AUTHORITATIVE_INTEREST_PAID,)
INTEREST_RECEIVABLE_BRIDGE_LINES = (AUTHORITATIVE_INTEREST_RECEIVED,)
DIVIDEND_PAYABLE_BRIDGE_LINES = (PROVEN_DIVIDENDS_PAID,)
DIVIDEND_RECEIVABLE_BRIDGE_LINES = (AUTHORITATIVE_DIVIDENDS_RECEIVED,)
```

Tablodaki tek enum literal exact one-element tuple'dır; comma ile yazılmış gross row ilgili named tuple'a, `OPENING/CLOSING` `OPENING_CLOSING`'a, bank/equivalent branch açıklaması ilgili branch tuple'ına, `bridge component` role-specific `*_BRIDGE_LINES` tuple'ına, `none`/`disclosure only` ise `NO_LINES`'a map edilir. Tuple içi sıra Section 7 `CashFlowLineCode` declaration order'ına göre doğrulanır; compiler yeniden yorumlamaz veya runtime string saklamaz.

| role | activity | candidate line code(s) | normal | WC | cash | gross evidence |
|---|---|---|---|---|---|---|
| `CASH_ON_HAND` | CASH_AND_CASH_EQUIVALENTS | OPENING/CLOSING_CASH_AND_CASH_EQUIVALENTS | DEBIT | NA | A | no |
| `BANK_ACCOUNT_CANDIDATE` | evidence-selected | demand/qualifying equivalent: OPENING/CLOSING; term/investment-purpose: PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS; restricted/blocked nature-changed: no automatic cash-flow line; overdraft: borrowing candidates | branch-specific | NA | R | non-cash branch yes |
| `RESTRICTED_BANK_ASSET` | RECLASSIFICATION_EFFECT only with authoritative evidence | AUTHORITATIVE_RECLASSIFICATION_EFFECT | DEBIT | NA | X | yes |
| `DEMAND_DEPOSIT` | CASH_AND_CASH_EQUIVALENTS | OPENING/CLOSING_CASH_AND_CASH_EQUIVALENTS | DEBIT | NA | R | no |
| `CASH_EQUIVALENT_INVESTMENT` | INVESTING unless eligible | eligible: OPENING/CLOSING; excluded: PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS | DEBIT | NA | R | investing path yes |
| `CHECK_RECEIVABLE` | OPERATING | OTHER_OPERATING_ASSET_MOVEMENT | DEBIT | OA | X | no |
| `POS_RECEIVABLE` | OPERATING | OTHER_OPERATING_ASSET_MOVEMENT | DEBIT | OA | X | no |
| `ISSUED_CHECK_OR_PAYMENT_ORDER` | UNCLASSIFIED | none; source-proven disclosure | CREDIT | NA | X | no |
| `OTHER_LIQUID_ASSET_CANDIDATE` | UNCLASSIFIED | none until trusted semantic role | DEBIT | NA | X | no |
| `OPERATING_RECEIVABLE` | OPERATING | TRADE_RECEIVABLES_MOVEMENT | DEBIT | OA | NA | no |
| `INVENTORY` | OPERATING | INVENTORY_MOVEMENT | DEBIT | OA | NA | no |
| `OTHER_OPERATING_ASSET` | OPERATING | OTHER_OPERATING_ASSET_MOVEMENT | DEBIT | OA | NA | no |
| `OPERATING_PAYABLE` | OPERATING | TRADE_PAYABLES_MOVEMENT | CREDIT | OL | NA | no |
| `OTHER_OPERATING_LIABILITY` | OPERATING | OTHER_OPERATING_LIABILITY_MOVEMENT | CREDIT | OL | NA | no |
| `PPE` | INVESTING | PROVEN_PPE_ACQUISITIONS, PROVEN_PPE_DISPOSALS | DEBIT | NA | NA | yes |
| `INTANGIBLE_ASSET` | INVESTING | PROVEN_INTANGIBLE_ACQUISITIONS, PROVEN_INTANGIBLE_DISPOSALS | DEBIT | NA | NA | yes |
| `FINANCIAL_INVESTMENT` | INVESTING unless eligible | eligible: OPENING/CLOSING; excluded: PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS | DEBIT | NA | R | investing path yes |
| `EQUITY_FINANCIAL_INVESTMENT` | INVESTING | PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS | DEBIT | NA | X | yes |
| `LONG_TERM_FINANCIAL_INVESTMENT` | INVESTING | PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS | DEBIT | NA | X | yes |
| `NON_CASH_INVESTMENT_COMMITMENT` | INVESTING disclosure only | none; balance delta is never cash | CREDIT | NA | X | no |
| `BORROWING` | FINANCING | PROVEN_BORROWING_PROCEEDS, PROVEN_DEBT_REPAYMENTS | CREDIT | NA | NA | yes |
| `EQUITY` | FINANCING | PROVEN_EQUITY_CONTRIBUTIONS | CREDIT | NA | NA | yes |
| `NON_CASH_EQUITY` | UNCLASSIFIED | none; known excluded from cash flow | source-proven | NA | NA | no |
| `TAX_PAYABLE`, `TAX_RECEIVABLE` | OPERATING default | AUTHORITATIVE_INCOME_TAX_PAID bridge component | CREDIT / DEBIT | NA | NA | yes |
| `INTEREST_PAYABLE`, `INTEREST_RECEIVABLE` | policy-selected | AUTHORITATIVE_INTEREST_PAID / RECEIVED bridge component | CREDIT / DEBIT | NA | NA | yes |
| `DIVIDEND_PAYABLE`, `DIVIDEND_RECEIVABLE` | policy-selected | PROVEN_DIVIDENDS_PAID / AUTHORITATIVE_DIVIDENDS_RECEIVED bridge component | CREDIT / DEBIT | NA | NA | yes |
| `INTEREST_EXPENSE_ACCRUAL` | OPERATING reversal | INTEREST_EXPENSE_ACCRUAL_REVERSAL | flow | NA | NA | yes |
| `INTEREST_INCOME_ACCRUAL` | OPERATING reversal | INTEREST_INCOME_ACCRUAL_REVERSAL | flow | NA | NA | yes |
| `DIVIDEND_INCOME_ACCRUAL` | OPERATING reversal | DIVIDEND_INCOME_ACCRUAL_REVERSAL | flow | NA | NA | yes |
| `CURRENT_TAX_EXPENSE_ACCRUAL` | OPERATING reversal | CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL | flow | NA | NA | yes |
| `DEFERRED_TAX_ACCRUAL`, `NON_CASH_ADJUSTMENT` | OPERATING | OTHER_PROVEN_NON_CASH_ADJUSTMENTS | flow/source-proven | NA | NA | yes |

`OPENING/CLOSING` kısaltmaları Section 7'deki tam enum adlarıdır; compiled registry tam enum değerlerini saklar. `eligible/excluded` conditional satırlarında cash-equivalent policy önce çalışır ve tam olarak bir branch seçer. `source-proven/flow` normal balance, yalnız authoritative semantic evidence üzerinde geçerlidir; account-code balance'a uygulanmaz. Prefix tablosunda bulunmayan veya role-behavior manifestinde olmayan değer `UNCLASSIFIED` olur. 660/661 gibi aggregate financing-expense hesapları dedicated interest accrual sayılmaz; explicit trusted role olmadan map edilmez.

Explicit-role manifest, role-behavior tablosundaki her role için tam bir `mapping_id="role:" + role.value`, `match_kind=EXPLICIT_ACCOUNT_ROLE` row'u içerir. Bu role yalnız trusted resolver'ın doğrulanmış structured source field'ından gelebilir; caller/account name/subaccount label role üretemez. Code/prefix mapping varsa precedence gereği role fallback kullanılmaz.

`BANK_ACCOUNT_CANDIDATE` branch sırası kapalıdır:

1. authoritative overdraft evidence → `BORROWING`;
2. `is_repayable_on_demand=True` ve `is_restricted=False` → `DEMAND_DEPOSIT` + `UNRESTRICTED_INCLUDED`;
3. `is_repayable_on_demand=True`, `is_restricted=True`, `restriction_preserves_cash_nature=True` → `DEMAND_DEPOSIT` + `RESTRICTED_INCLUDED`;
4. bütün cash-equivalent eligibility predicates ve, restricted ise, `restriction_preserves_cash_nature=True` → `CASH_EQUIVALENT_INVESTMENT` + restricted/unrestricted ilgili included classification;
5. authoritative term/investment-purpose evidence → `FINANCIAL_INVESTMENT`;
6. `is_restricted=True` ve `restriction_preserves_cash_nature=False` → `RESTRICTED_BANK_ASSET`;
7. demand/restriction/eligibility için gereken herhangi bir boolean `None` veya hiçbir branch kanıtlanamıyorsa → `ELIGIBILITY_UNRESOLVED`.

`RESTRICTED_BANK_ASSET` cash değildir ve sırf restriction nedeniyle operating veya investing sayılmaz. V1'de yalnız ayrı authoritative reclassification event amount'ı varsa `AUTHORITATIVE_RECLASSIFICATION_EFFECT` contributor'ı üretir; balance delta bu amount'ı üretemez. Kanıt yoksa reclassification amount `None/UNAVAILABLE` kalır. Aynı movement başka contributor'a tekrar atanamaz. Term/investment branch balance delta'sı cash değildir ve gross evidence yoksa investing subtotal unavailable olur; sessiz omit edilmez. Birden çok branch kanıtı conflict/failure'dır.

Manifestin ordered canonical bytes SHA-256 digest'i release sırasında golden constant olarak kilitlenir; bu tasarım digest değerini kod yazılmadan uydurmaz. Her row field'i, precedence sonucu ve compiled digest test edilir.

`CashFlowAccountDisposition` bütün selected current/prior detailed account observations için exhaustive'dir. Registry mapping + kapalı branch evidence her satıra exact bir disposition üretir: eligible cash branch → `CASH_OR_CASH_EQUIVALENT`; OA/OL behavior → `OPERATING_WORKING_CAPITAL`; family manifest asset/debt üyeleri → `INVESTING_FAMILY`/`FINANCING_FAMILY`; dedicated flow account'ın current net-profit projection'ına exact dahil edildiği source-field/digest proof'u → `PNL_CAPTURED_IN_NET_PROFIT`; closed bridge ile nakit dışı olduğu kanıtlanan row → `PROVEN_NON_CASH`; policy'nin amount-affecting olmadığını exact role + applicability proof'uyla gösteren row → `PROVEN_NOT_RELEVANT`; bunların hiçbiri kanıtlanamıyorsa `UNRESOLVED`. Account name, filename veya balance sign disposition üretemez.

Resolved disposition'da `disposition_proof_digest = sha256(b"cash-flow/account-disposition/v1\0" + canonical_bytes(cf.account_disposition_proof.v1(source locator, account_code, winning_mapping_id_or_null, role, disposition, branch-evidence digests, family reference-or-null, net-profit-inclusion proof-or-null))).hexdigest()` zorunludur; `UNRESOLVED` disposition'da null'dır. `PNL_CAPTURED_IN_NET_PROFIT` yalnız `FLOW_INTERVAL` current source ve net-profit owner canonical digest'ine bağlı field-inclusion proof'uyla mümkündür; bu row ayrıca cash contributor olamaz. `PROVEN_NON_CASH` aynı economic-event digest'li closed bridge'e, `PROVEN_NOT_RELEVANT` exact `PROVEN_NOT_APPLICABLE` policy evidence'ına bağlanır. Duplicate disposition veya bir row'un iki amount-affecting disposition'a girmesi `SOURCE_EVIDENCE_CONFLICT`'tir.

`UNCLASSIFIED` sessizce dışlama anlamına gelmez. Non-zero `UNRESOLVED` cash/bank/liquid candidate opening veya closing cash minimum coverage'ını başarısız yapar ve `INSUFFICIENT_DATA` üretir. Ekonomik sınıfı dahi belirlenemeyen başka herhangi bir non-zero balance/movement için engine operating, investing ve financing subtotal'larının üçünü de `None/UNAVAILABLE`, calculated net change/reconciliation'ı not-performed ve sonucu `PARTIAL_UNRECONCILED` yapar; independent gross total bu global unknown'ı complete'e yükseltemez. Yalnız row'un exact zero olduğu veya complete-snapshot + known zero-omission proof'u bulunduğu durumda unresolved satır amount etkisiz sayılabilir. Böylece hiçbir non-zero row yalnız warning ile `COMPLETE_*` sonuca geçemez. Her non-zero unresolved row `ACCOUNT_UNCLASSIFIED` warning ve evidence inventory'sine girer; completeness testleri bütün source account row'larının exact bir disposition/proof kararına sahip olduğunu doğrular.

## 11. Cash and Cash Equivalents Policy

```python
@dataclass(frozen=True)
class CashEquivalentPolicy:
    policy_version: str
    automatic_cash_prefixes: tuple[str, ...]
    evidence_required_prefixes: tuple[str, ...]
    explicitly_excluded_prefixes: tuple[str, ...]
    maximum_maturity_days_at_acquisition: int
    require_restriction_nature_assessment: bool
    require_ready_convertibility: bool
    require_insignificant_value_change_risk: bool
    require_short_term_cash_commitment_purpose: bool

CASH_EQUIVALENT_POLICY_VERSION = "1.0.0"
```

V1 kararı:

- kasa (`100` prefix) cash olarak kabul edilir;
- banka (`102` ve alt hesapları) önce `BANK_ACCOUNT_CANDIDATE` olur; yalnız authoritative unrestricted demand-deposit branch'i veya bütün kısa-vadeli cash-equivalent predicates'i kanıtlanan branch cash'e dahil edilir;
- alınan/verilen çekler, POS slipleri, diğer hazır değerler, vadeli veya bloke hesaplar yalnız hesap adı/kodu nedeniyle otomatik dahil edilmez;
- kısa vadeli yatırım ancak acquisition anında maturity ≤ 90 gün, bilinen nakit tutarına kolay çevrilebilirlik, önemsiz değer değişim riski ve `held_for_short_term_cash_commitments=True` amacı ayrı authoritative kanıtlarla doğrulanırsa cash equivalent olabilir; yalnız getiri/yatırım amacı taşıyan araç süre kısa olsa da dahil edilmez;
- restriction tek başına hesabı otomatik dışlamaz; ancak restriction'ın demand-deposit/cash niteliğini değiştirmediğini gösteren authoritative `restriction_preserves_cash_nature=True` kanıtı yoksa hesap dahil edilmez. Dahil edilen restricted cash ilgili opening/closing observation'da `RESTRICTED_INCLUDED` disclosure taşır;
- overdraft v1'de daima financing liability'dir ve nakitten netlenmez. Repayable-on-demand/cash-management netting, bu sürümde future hardening'dir;
- equity investment cash equivalent sayılmaz;
- parent/summary hesap ile leaf hesap birlikte mevcutsa yalnız leaf hesaplar toplanır; double count yasaktır.

Bir non-zero `102.*` veya başka cash-equivalent candidate leaf hesabında eligibility evidence yoksa observation `ELIGIBILITY_UNRESOLVED` olur; opening/closing cash exact belirlenemediği için minimum cash ground kesin başarısız ve sonuç `INSUFFICIENT_DATA` olur. Yalnız known zero + complete-snapshot/zero-omission proof bu sonucu tetiklemez. Authoritative olarak excluded olduğu kanıtlanan component `RESTRICTED_EXCLUDED`/ilgili excluded evidence ile cash dışı kalabilir. Her unresolved durumda `CASH_EQUIVALENT_ELIGIBILITY_UNPROVEN` warning'i üretilir.

Cash toplamı leaf bazında yalnız non-negative eligible balance'ları toplar. Negative `CASH_ON_HAND` fiziksel-cash anomaly'sidir; cash'e dahil edilmez, `NEGATIVE_CASH_BALANCE` ile minimum cash ground başarısız ve sonuç `INSUFFICIENT_DATA` olur. Negative `DEMAND_DEPOSIT` ancak authoritative overdraft/liability evidence varsa cash dışına alınır, `BORROWING` olarak financing balance'a reclassify edilir ve `OVERDRAFT_RECLASSIFIED_TO_FINANCING` taşır; balance tek başına gross borrowing/repayment üretmez. Böyle kanıt yoksa `ELIGIBILITY_UNRESOLVED` ve `INSUFFICIENT_DATA` olur. Positive deposit ile negative overdraft asla netlenmez.

## 12. CashFlowPresentationPolicy

Canonical line item ile activity presentation birbirinden ayrıdır. Engine canonical olayı bir kez üretir; profile yalnız activity projection'ını belirler.

```python
class CashFlowPresentationProfile(str, Enum):
    TMS_TFRS_2024_INDIRECT_V1 = "tms_tfrs_2024_indirect_v1"
    BANK_CREDIT_V1 = "bank_credit_v1"
    MANAGEMENT_V1 = "management_v1"

class CashFlowPresentationRule(str, Enum):
    OPERATING = "operating"
    INVESTING = "investing"
    FINANCING = "financing"
    ATTRIBUTION_THEN_OPERATING = "attribution_then_operating"
    REQUIRES_EXPLICIT_EVIDENCE = "requires_explicit_evidence"

@dataclass(frozen=True)
class CashFlowPresentationPolicy:
    policy_version: str
    profile: CashFlowPresentationProfile
    interest_paid_rule: CashFlowPresentationRule
    interest_received_rule: CashFlowPresentationRule
    dividends_received_rule: CashFlowPresentationRule
    dividends_paid_rule: CashFlowPresentationRule
    income_tax_paid_rule: CashFlowPresentationRule
    demand_overdraft_rule: CashFlowPresentationRule
    applicable_period_start_before: date | None
    permits_ifrs18_early_adoption: bool
```

V1 profile manifesti:

| Canonical line | TMS/TFRS 2024 indirect v1 | Bank Credit v1 | Management v1 |
|---|---|---|---|
| Interest paid | financing | financing | financing |
| Interest received | investing | investing | investing |
| Dividends received | investing | investing | investing |
| Dividends paid | financing | financing | financing |
| Income tax paid | `ATTRIBUTION_THEN_OPERATING`: yalnız doğrudan investing/financing işlemine bağlanan kanıtlı bölüm ilgili activity'ye, kalan operating | aynı | aynı |
| Demand overdraft | financing; nakitten netlenmez | financing | financing |

`CASH_FLOW_PRESENTATION_POLICY_MANIFEST_V1` üç immutable row'dur; caller'ın aynı profile adıyla rule değiştirmesine izin vermez:

| profile | policy_version | interest paid | interest received | dividends received | dividends paid | income tax paid | demand overdraft | annual start before | early adoption permitted |
|---|---|---|---|---|---|---|---|---|---|
| `TMS_TFRS_2024_INDIRECT_V1` | `tms_tfrs_2024_indirect/1.0.0` | FINANCING | INVESTING | INVESTING | FINANCING | ATTRIBUTION_THEN_OPERATING | FINANCING | `2027-01-01` | false |
| `BANK_CREDIT_V1` | `bank_credit/1.0.0` | FINANCING | INVESTING | INVESTING | FINANCING | ATTRIBUTION_THEN_OPERATING | FINANCING | null | true |
| `MANAGEMENT_V1` | `management/1.0.0` | FINANCING | INVESTING | INVESTING | FINANCING | ATTRIBUTION_THEN_OPERATING | FINANCING | null | true |

`CashFlowPresentationPolicy` constructor'ı verilen bütün alanları seçilen manifest row'uyla exact karşılaştırır. Unknown version, rule mutation, cutoff mutation veya early-adoption flag mutation `POLICY_VERSION_UNSUPPORTED` failure'dır. Engine ayrıca period metadata ile cutoff/early-adoption uygunluğunu doğrular. Bank/Management row'larının null cutoff ve `true` early-adoption değeri bunların statutory-compliance profile olmadığı anlamına gelir; canonical amounts ve classification yine tabloda kilitlidir. Profile adı tek başına serbest policy assembly yetkisi vermez.

Kurallar:

- Gerçek cash-paid kanıtı yoksa expense/accrual tutarı payment sayılmaz; line `UNAVAILABLE` kalır.
- Profile canonical amount'ı değiştiremez, yalnız activity projection'ını belirler.
- Profile değişikliği `policy_version` ve fingerprint'i değiştirir.
- Report türü policy seçimini sessizce değiştiremez; caller versioned profile'ı açıkça sağlar.
- TMS/TFRS, banka ve yönetim çıktıları aynı canonical core'u tüketir.
- üç profile için full-row golden manifest, unknown/missing field ve her tek-field mutation rejection zorunludur.

Üç v1 profile activity sınıflandırması aynıdır; Bank Credit ve Management profilleri yalnız layout/analytical subtotal sunumunu değiştirir. Böylece aynı canonical result'tan farklı OCF/ICF/FCF toplamı yaratılmaz.

`TMS_TFRS_2024_INDIRECT_V1`, net-kâr başlangıçlı ve KGK 2024 TMS 7 policy seçimine pinlenmiş analytic/statutory-support profile'dır; “zamandan bağımsız tam mevzuat uyumu” iddiası taşımaz. Authoritative `annual_reporting_period_start_date >= 2027-01-01` ise veya `ifrs18_early_adopted=True` ise bu profile `POLICY_VERSION_UNSUPPORTED` ile fail-closed olur. Cari interval'in `start_date/end_date` değerleri bu annual reporting period sınırları içinde olmalıdır; aylık/çeyreklik/interim interval başlangıcı cutoff kararı vermez. Böylece 1 Temmuz 2026–30 Haziran 2027 mali yılındaki 2027 interim dönem pre-IFRS18 profile'da kalabilir; 1 Temmuz 2027'de başlayan mali yıl kalamaz. IFRS 18 sonrası operating-profit başlangıçlı profile ayrı, versioned ve ayrıca onaylı future contract'tır. Enflasyon muhasebesi gibi bu v1 line taxonomy'sinde açıkça desteklenmeyen accounting basis de fail-closed'dur.

Bu v1 seçimleri standalone, finansal kuruluş olmayan işletme çekirdeği içindir. Finansal kurum policy'si v1 kapsamı dışındadır.

## 13. Cash-Flow Result Contract

```python
@dataclass(frozen=True)
class CashFlowEvidenceReference:
    evidence_kind: CashFlowEvidenceKind
    source_role: CashFlowSourceRole
    source_analysis_result_id: UUID | None
    same_run_engine_code: "OrchestrationEngineCodeV3 | None"
    source_canonical_digest: str
    source_provenance_digest: str
    account_codes: tuple[str, ...]
    mapping_ids: tuple[str, ...]
    derivation_code: CashFlowDerivationCode

@dataclass(frozen=True)
class CashFlowActivityAllocation:
    activity: CashFlowActivity
    amount: Decimal

@dataclass(frozen=True)
class CashFlowLineItem:
    line_code: CashFlowLineCode
    canonical_amount: Decimal | None
    aggregation_role: CashFlowLineAggregationRole
    presentation_allocations: tuple[CashFlowActivityAllocation, ...]
    applicability: CashFlowApplicability
    evidence_kind: CashFlowEvidenceKind
    evidence: tuple[CashFlowEvidenceReference, ...]
    missing_inputs: tuple[str, ...]
    warning_codes: tuple[CashFlowWarningCode, ...]

@dataclass(frozen=True)
class CashFlowCashAvailabilityObservation:
    period_position: CashFlowAvailabilityPeriodPosition
    classification: CashAvailabilityClassification
    amount: Decimal | None
    restriction_preserves_cash_nature: bool | None
    evidence: tuple[CashFlowEvidenceReference, ...]

@dataclass(frozen=True)
class CashFlowCashAvailabilityDisclosure:
    component_reference_digest: str
    account_role: CashFlowAccountRole
    observations: tuple[CashFlowCashAvailabilityObservation, ...]

@dataclass(frozen=True)
class CashFlowEndpointReconciliation:
    period_position: CashFlowAvailabilityPeriodPosition
    policy_defined_cash_and_equivalents: Decimal | None
    reported_balance_sheet_cash_and_equivalents: Decimal | None
    difference: Decimal | None
    status: CashFlowEndpointReconciliationStatus
    balance_sheet_evidence: tuple[CashFlowEvidenceReference, ...]

@dataclass(frozen=True)
class CashFlowCompleteness:
    manifest_version: str
    required_line_count: int
    exact_count: int
    derived_count: int
    estimated_count: int
    unavailable_count: int
    available_ratio: Decimal
    optional_analytics_available_count: int
    optional_analytics_unavailable_count: int

@dataclass(frozen=True)
class CashFlowSourceLineageReference:
    source_role: CashFlowSourceRole
    source_analysis_result_id: UUID | None
    same_run_engine_code: "OrchestrationEngineCodeV3 | None"
    source_period_id: UUID
    canonical_digest: str
    source_provenance_digest: str

@dataclass(frozen=True)
class CashFlowResult:
    opening_cash_and_cash_equivalents: Decimal | None
    closing_cash_and_cash_equivalents: Decimal | None
    operating_cash_flow: Decimal | None
    investing_cash_flow: Decimal | None
    financing_cash_flow: Decimal | None
    authoritative_fx_effect: Decimal | None
    authoritative_reclassification_effect: Decimal | None
    calculated_net_cash_change: Decimal | None
    balance_sheet_net_cash_change: Decimal | None
    reconciliation_difference: Decimal | None
    free_cash_flow: Decimal | None
    status: CashFlowResultBearingStatus
    completeness: CashFlowCompleteness
    reconciliation_status: CashFlowReconciliationStatus
    currency_code: str
    monetary_scale: int
    policy_version: str
    accounting_policy_version: str
    cash_equivalent_policy_version: str
    presentation_policy_version: str
    reconciliation_policy_version: str
    mapping_registry_version: str
    current_period_id: UUID
    prior_period_id: UUID | None
    current_period_descriptor: CashFlowPeriodDescriptor
    prior_period_descriptor: CashFlowPeriodDescriptor | None
    current_period_descriptor_digest: str
    prior_period_descriptor_digest: str | None
    comparability_proof_digest: str | None
    line_items: tuple[CashFlowLineItem, ...]
    cash_availability_disclosures: tuple[CashFlowCashAvailabilityDisclosure, ...]
    endpoint_reconciliations: tuple[CashFlowEndpointReconciliation, ...]
    evidence: tuple[CashFlowEvidenceReference, ...]
    warnings: tuple[CashFlowIssue, ...]
    errors: tuple[CashFlowIssue, ...]
    source_lineage_references: tuple[CashFlowSourceLineageReference, ...]
    cash_flow_schema_version: str
    cash_flow_model_version: str

@final
class CashFlowEngineFailure:
    __slots__ = ("_code",)
    def __init__(self, code: CashFlowErrorCode) -> None: ...
    @property
    def code(self) -> CashFlowErrorCode: ...
    @property
    def safe_message(self) -> str: ...
    @property
    def safe_metadata(self) -> CashFlowJsonObject: ...
    @property
    def retryable(self) -> bool: ...
    def __str__(self) -> str: ...
    def __repr__(self) -> str: ...

@dataclass(frozen=True)
class CashFlowEngineOutcome:
    status: CashFlowResultStatus
    success: bool
    value: CashFlowResult | None
    error: CashFlowEngineFailure | None
```

`CASH_FLOW_RESULT_BEARING_STATUS_MANIFEST` declaration order'daki ilk beş değeri, `CASH_FLOW_FAILURE_STATUS_MANIFEST` son iki değeri içerir. `CashFlowResult` constructor'ı status'un ilk manifestte olmasını zorunlu kılar; `INVALID_INPUT`/`INTEGRITY_FAILURE` taşıyan bir result payload kurulamaz. `CashFlowEngineOutcome` discriminated invariant'ı: success ise value zorunlu/error null ve `outcome.status == value.status`; failure ise value null/error zorunlu ve status yalnız failure manifestinde olabilir. `INVALID_INPUT` grubu contract/period-selection/policy/mapping-registry-version/Decimal input ihlallerini; `INTEGRITY_FAILURE` grubu source scope/status/digest/evidence conflict, mapping conflict ve persistence integrity ihlallerini taşır. Basit source yokluğu veya minimum-data eksikliği integrity failure değildir; result-bearing `INSUFFICIENT_DATA` üretir. Böylece bağlayıcı yedi üyeli tek status taxonomy'si korunurken yalnız ilk beş status persisted payload olabilir. Exception yalnız programmer error/invariant breach içindir ve raw exception public boundary'ye çıkmaz.

V1 result-bearing payload'da `CashFlowResult.errors=()` zorunludur; non-fatal veri kapsamı `warnings` ve line-level missing inventory ile açıklanır. Fatal structured error yalnız `CashFlowEngineFailure` içinde, payload dışında bulunur. Field gelecekteki schema evolution için görünür kalsa da V1'de failure payload uydurmak için kullanılamaz.

Closed failure mapping: `INVALID_CONTRACT`, `PERIOD_NOT_COMPARABLE`, `PERIOD_SELECTION_AMBIGUOUS`, `POLICY_VERSION_UNSUPPORTED`, `MAPPING_REGISTRY_VERSION_UNSUPPORTED`, `DECIMAL_NON_FINITE_OR_SCALE_INVALID` → `INVALID_INPUT`; explicit/claimed source için `SOURCE_NOT_FOUND`, `SOURCE_SCOPE_MISMATCH`, `SOURCE_STATUS_INVALID`, `SOURCE_DIGEST_MISMATCH`, `SOURCE_CURRENCY_MISMATCH`, `SOURCE_EVIDENCE_CONFLICT`, `MAPPING_CONFLICT`, `PERSISTENCE_INTEGRITY_FAILURE`, `SOURCE_RESOLUTION_UNAVAILABLE`, `PERSISTENCE_UNAVAILABLE` → `INTEGRITY_FAILURE`. Bu 16-code manifest exhaustive'dir. Yalnız iki infrastructure code retryable'dır: `SOURCE_RESOLUTION_UNAVAILABLE` ve `PERSISTENCE_UNAVAILABLE`; diğer on dört code için `retryable=False` zorunludur. Caller minimum source bildirmemişse veya resolver exact prior bulamamışsa error code değil `INSUFFICIENT_DATA` missing inventory oluşur; caller belirli bir persisted source ID/digest iddia etmiş ve o source yok/corrupt ise integrity failure olur.

V1 safe-message manifesti exact ve identifier-free'dir: `INVALID_CONTRACT→"Nakit akışı girdi sözleşmesi geçersiz."`, `PERIOD_NOT_COMPARABLE→"Dönemler karşılaştırılabilir değil."`, `PERIOD_SELECTION_AMBIGUOUS→"Karşılaştırma dönemi tekil olarak seçilemedi."`, `SOURCE_NOT_FOUND→"Doğrulanmış finansal kaynak bulunamadı."`, `SOURCE_SCOPE_MISMATCH→"Finansal kaynak kapsamla eşleşmiyor."`, `SOURCE_STATUS_INVALID→"Finansal kaynak kullanılabilir durumda değil."`, `SOURCE_DIGEST_MISMATCH→"Finansal kaynak bütünlük doğrulamasını geçemedi."`, `SOURCE_CURRENCY_MISMATCH→"Parasal kaynak normalizasyonu doğrulanamadı."`, `SOURCE_EVIDENCE_CONFLICT→"Finansal kaynak kanıtları birbiriyle çelişiyor."`, `POLICY_VERSION_UNSUPPORTED→"Nakit akışı politika sürümü desteklenmiyor."`, `MAPPING_REGISTRY_VERSION_UNSUPPORTED→"Hesap eşleştirme sürümü desteklenmiyor."`, `MAPPING_CONFLICT→"Hesap eşleştirme kuralları çakışıyor."`, `DECIMAL_NON_FINITE_OR_SCALE_INVALID→"Parasal değer biçimi desteklenmiyor."`, `PERSISTENCE_INTEGRITY_FAILURE→"Nakit akışı kalıcılık bütünlüğü doğrulanamadı."`, `SOURCE_RESOLUTION_UNAVAILABLE→"Finansal kaynak çözümleme servisi kullanılamıyor."`, `PERSISTENCE_UNAVAILABLE→"Nakit akışı kalıcılık servisi kullanılamıyor."`. V1 failure `safe_metadata` exact empty `CashFlowJsonObject(items=())`'dır; code-specific identifiers/values eklenmez. `CashFlowEngineFailure` constructor'ı yalnız code alır, safe message/empty metadata/retryable manifestten türetilir; subclassing, field assignment, raw cause ve caller override yasaktır. `str/repr` yalnız class adı + code value taşır.

`CashFlowResult` içindeki on bir özet parasal alan, `line_items` içindeki aynı `CashFlowLineCode` satırlarının projection'ıdır; ikinci bir hesaplama kaynağı değildir. Constructor her özet alanın ilgili line item ile birebir eşitliğini doğrular. `policy_version`, accounting/cash-equivalent/presentation/reconciliation/mapping sürümlerinin canonical sıralı bundle SHA-256 referansıdır; ayrı sürüm alanlarının yerine geçmez.

`endpoint_reconciliations` exact iki kayıtlı `(OPENING, CLOSING)` tuple'dır. COMPLETE/PARTIAL status'ta her record `MATCHED`, iki amount non-null/eşit, difference exact `Decimal("0.00")` ve ilgili BS source evidence non-empty olmalıdır; opening/closing özet alanları bu policy-defined amount'larla exact eşleşir. `INSUFFICIENT_DATA` status'ta iki record `NOT_PERFORMED_INSUFFICIENT_DATA`, difference null olur ve mevcut olmayan amount sıfıra çevrilmez. Başka status/amount/evidence kombinasyonu constructor ve strict decoder tarafından reddedilir. Endpoint record payload içindeki bağımsız BS-vs-policy proof projection'ıdır; source owner veya lineage yerine geçmez.

`CASH_FLOW_LINE_ITEM_MANIFEST_V1`, Section 7'deki bütün `CashFlowLineCode` üyelerini declaration order'da exact bir kez içerir. `CashFlowResult.line_items` bu manifest ile aynı uzunluk/sıra/code setine sahip olmalıdır; duplicate, missing, extra veya reorder strict constructor/codec rejection'dır. Kullanılmayan line bile omit edilmez: authoritative not-applicable proof varsa `canonical_amount=0`, `PROVEN_NOT_APPLICABLE`, `EXACT`; aksi halde `canonical_amount=None`, `UNKNOWN`, `UNAVAILABLE` ve non-empty `missing_inputs` taşır. Böylece contributor veya reconciliation satırı gizlenerek roll-up/completeness manipüle edilemez.

`CASH_FLOW_LINE_SIGN_MANIFEST_V1` semantic load guard'ıdır: PPE/intangible acquisitions, debt repayments, dividends paid ve interest paid `<=0`; PPE/intangible disposals, borrowing proceeds, equity contributions, interest received ve dividends received `>=0`; income-tax cash line payment için negatif, refund için pozitif olabilir. Estimated net movements, accrual/non-cash/WC adjustments, FX/reclassification, deltas ve subtotals iki işaretli olabilir. `PROVEN_NOT_APPLICABLE` exact zero her fixed-sign satırda geçerlidir. Wrong sign constructor ve strict decoder tarafından reddedilir; yalnız digest eşitliği semantic doğrulama sayılmaz.

`CashFlowSourceLineageReference` tam olarak bir locator taşır: `source_analysis_result_id XOR same_run_engine_code`. Bu payload alanı provenance intent/projection'dır; authoritative ownership yeni lineage tablosudur. Read adapter, same-run engine locator'ını durable owner ID ile doğrular; payload değiştirerek ikinci source of truth oluşturmaz.

`CashFlowEvidenceReference` aynı locator XOR kuralına tabidir. `source_canonical_digest` yalnız source `FinancialAnalysisResult.canonical_result_digest` alanının digest domain'idir; yani source owner'ın `result_json` değerinin o analysis type'a ait authoritative financial-result codec ile canonical encode edilmesinden doğar. Persisted source yüklemede payload yeniden encode edilip stored digest constant-time karşılaştırılır. Same-run BS/IS source için V3 owner planner, `EngineResultEnvelopeV3.result.result_json` değerini aynı mevcut BS/IS owner codec'iyle encode eder; üretilen digest aynı terminal transaction'da stage edilen source owner'ın `canonical_result_digest` değeriyle exact eşleşmeden lineage kurmaz. Full outcome/status/error/source-mode/trial-balance semantiğini bağlayan `owner_content_digest` ayrı bir domain'dir; `source_canonical_digest` yerine kullanılamaz veya onunla karşılaştırılamaz.

Yalnız `aggregation_role=PRESENTATION_CONTRIBUTOR` ve `canonical_amount` doluyken `presentation_allocations` boş olamaz; `(activity.value, amount)` sırasına göre canonical, activity'ler unique ve allocation toplamı canonical amount'a exact eşittir. `SUBTOTAL`, `ANALYTIC`, `RECONCILIATION` veya amount `None` satırda allocations boş olmak zorundadır. `AUTHORITATIVE_INCOME_TAX_PAID` bir contributor canonical amount'ı operating/investing/financing arasında bölebilir; non-zero allocation'ların her biri canonical amount ile aynı işareti taşır, offsetting split yasaktır. Negatif canonical amount ödeme, pozitif canonical amount authoritative net tax refund'dır. Activity subtotals yalnız contributor allocations'ı toplar; detail + subtotal/FCF/reconciliation tekrar toplanamaz.

Closed aggregation manifest: net-profit, detailed non-cash/WC/other operating adjustments, four accrual reversals, authoritative interest/dividend/tax cash lines, detailed investing lines veya onların mutually-exclusive estimated replacement'ı, detailed financing lines veya mutually-exclusive estimated debt replacement'ı ve authoritative FX/reclassification satırları `PRESENTATION_CONTRIBUTOR`; `NON_CASH_ADJUSTMENT_TOTAL`, `WORKING_CAPITAL_MOVEMENT_TOTAL`, `OPERATING_CASH_FLOW`, `INVESTING_CASH_FLOW`, `FINANCING_CASH_FLOW`, `CALCULATED_NET_CASH_CHANGE`, `BALANCE_SHEET_NET_CASH_CHANGE` `SUBTOTAL`; `FREE_CASH_FLOW` `ANALYTIC`; opening/closing cash ile `RECONCILIATION_DIFFERENCE` `RECONCILIATION`'dır. Estimated replacement ile replaced gross lines aynı sonuçta contributor olamaz. Manifest enum-exhaustive golden testle kilitlenir.

`cash_availability_disclosures` opening/closing cash hesabında değerlendirilen her component için tek satır ve exact iki observation (`OPENING`, sonra `CLOSING`) taşır. Classification, amount, restriction proof ve evidence her tarih için ayrıdır; restriction/eligibility değişimi tek ortak flag ile gizlenemez. `RESTRICTED_INCLUDED` yalnız o observation'da `restriction_preserves_cash_nature=True` ve exact eligibility evidence ile mümkündür; amount ilgili cash toplamına dahil edilir ve report projection'ında aynen korunur. `RESTRICTED_EXCLUDED` ve `ELIGIBILITY_UNRESOLVED` tutarları cash toplamına girmez. `component_reference_digest`, component identity ile iki as-of/source locator digest'inin canonical SHA-256'ıdır; raw banka hesabı veya account name içermez.

`current_period_descriptor.period_id == current_period_id` ve descriptor'ın strict digest'i `current_period_descriptor_digest` ile exact eşleşir. Prior için dört alan (`prior_period_id`, `prior_period_descriptor`, `prior_period_descriptor_digest`, `comparability_proof_digest`) COMPLETE/PARTIAL sonuçta hep birlikte dolu; exact resolver proof'u ile eşleşen immutable snapshot'tır. `prior_period_id=None` yalnız `INSUFFICIENT_DATA` için geçerlidir; bu durumda prior descriptor/digest/proof da null olmak zorundadır. Descriptor snapshot'ları mutable `financial_periods` satırını ikinci source of truth yapmaz: historical payload kendi doğrulanabilir karar kanıtını taşır; resume/reuse ise current database row'unu lock/rehash ederek stored snapshot/proof ile drift olmadığını ayrıca doğrular.

### 13.1 Completeness manifesti

`CASH_FLOW_STATEMENT_COMPLETENESS_MANIFEST_V1` aşağıdaki 13 statement satırından oluşur:

1. opening cash and cash equivalents
2. net profit
3. non-cash adjustment total
4. working-capital movement total
5. operating cash flow
6. investing cash flow
7. financing cash flow
8. authoritative FX effect
9. authoritative reclassification effect
10. calculated net cash change
11. closing cash and cash equivalents
12. balance-sheet net cash change
13. reconciliation difference
`free_cash_flow` statement completeness manifestinin parçası değildir; `CASH_FLOW_OPTIONAL_ANALYTICS_MANIFEST_V1` içinde tek optional analytical line'dır. FCF eksikliği nakit akış tablosunu tek başına PARTIAL yapmaz fakat ratio/report coverage'da görünür kalır.

`available_ratio = (exact + derived + estimated) / required_line_count`, `Decimal("0.0001")` scale ile `ROUND_HALF_EVEN` quantize edilir. `UNAVAILABLE` değer paydaya dahildir. Statement evidence sayıları toplamı daima 13'tür. Bu oran veri kapsamıdır; muhasebesel doğruluk puanı değildir.

`COMPLETE_*` yalnız `estimated_count == 0 and unavailable_count == 0` iken mümkündür. Mandatory statement line'da herhangi bir `ESTIMATED` veya `UNAVAILABLE` varsa sonuç `PARTIAL_*` olur. FX/reclassification için sıfır yalnız `applicability=PROVEN_NOT_APPLICABLE` ve authoritative evidence varken `EXACT(0)` olabilir; `UNKNOWN` ise amount `None` ve evidence `UNAVAILABLE` kalır.

## 14. Dolaylı Yöntem Hesaplama Sırası

Hesaplama sırası sabit ve test edilebilir olmalıdır:

1. Contract ve version doğrulaması.
2. Current/prior scope, period ve digest doğrulaması.
3. Comparable-period doğrulaması.
4. Account mapping registry doğrulaması ve mapping.
5. Opening/closing cash materialization.
6. Net profit başlangıç noktası.
7. Proven non-cash adjustment'lar.
8. Working-capital movements.
9. Diğer proven operating adjustment'lar.
10. Operating cash-flow subtotal.
11. Investing canonical movements.
12. Financing canonical movements.
13. Presentation policy projection.
14. Authoritative FX/reclassification etkileri.
15. Net cash change ve reconciliation.
16. Free cash flow.
17. Evidence/completeness/status üretimi.

Hiçbir sonraki adım önceki adımın `None` değerini sıfır saymaz.

## 15. Operating Cash Flow

Canonical formül:

```text
operating_cash_flow =
    net_profit
  + proven_non_cash_expense_adjustments
  - proven_non_cash_income_adjustments
  + operating_asset_movement_effects
  + operating_liability_movement_effects
  + other_proven_operating_adjustments
  + accrual_reversal_adjustments_for_flexible_items
  + actual_cash_items_presented_as_operating
```

### 15.1 Net-profit accrual-to-cash bridge

Net profit faiz, vergi ve alınan temettü/faiz accrual'larını zaten içerir. Actual cash line'ı doğrudan eklemek double count yaratacağından her flexible item iki adımda işlenir:

```text
1. Net profit içindeki accrual etkisini ters çevir:
   embedded expense  → pozitif add-back
   embedded income   → negatif removal

2. Authoritative actual cash amount'ı presentation policy'nin seçtiği
   activity'ye signed cash flow olarak ekle:
   receipt  → positive
   payment  → negative
```

Closed mirror line'lar:

- `INTEREST_EXPENSE_ACCRUAL_REVERSAL`
- `INTEREST_INCOME_ACCRUAL_REVERSAL`
- `DIVIDEND_INCOME_ACCRUAL_REVERSAL`
- `CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL`
- `AUTHORITATIVE_INTEREST_PAID`
- `AUTHORITATIVE_INTEREST_RECEIVED`
- `AUTHORITATIVE_DIVIDENDS_RECEIVED`
- `AUTHORITATIVE_INCOME_TAX_PAID`

`PROVEN_DIVIDENDS_PAID` net profit bridge'inde reversal almaz; dağıtım net profit expense'i değildir. Accrual amount veya actual cash amount kanıtlanamıyorsa affected reclassification yapılmaz, ilgili line `UNAVAILABLE` olur ve etkilenen aggregate `None/PARTIAL` kalır. Gideri ödeme saymak veya tek taraflı reversal yasaktır.

Bridge yalnız dedicated authoritative components ile çalışır; aggregate `financing_expenses` interest expense sayılmaz ve `profit_before_tax-net_profit` current tax expense sayılmaz. Signed payable denklemi:

```text
closing_payable = opening_payable + recognized_expense_or_declared_amount
                  + signed_noncash_or_reclassification_to_payable
                  - cash_paid_magnitude
cash_paid_magnitude = opening_payable + recognized_expense_or_declared_amount
                      + signed_noncash_or_reclassification_to_payable
                      - closing_payable
presented_cash_payment = -cash_paid_magnitude
```

Signed receivable denklemi:

```text
closing_receivable = opening_receivable + recognized_income
                     + signed_noncash_or_reclassification_to_receivable
                     - cash_received
cash_received = opening_receivable + recognized_income
                + signed_noncash_or_reclassification_to_receivable
                - closing_receivable
```

Interest/tax/dividend payment bridge'i sırasıyla dedicated recognized interest expense/current tax expense/declared dividend ve `INTEREST_PAYABLE`/`TAX_PAYABLE`/`DIVIDEND_PAYABLE` kullanır. Interest/dividend receipt bridge'i dedicated recognized income ile `INTEREST_RECEIVABLE`/`DIVIDEND_RECEIVABLE` kullanır; tax refund desteklenirse ayrı `TAX_RECEIVABLE` kanıtı gerekir. Her opening, recognized, signed non-cash/reclassification ve closing component aynı exact flow window'a ait olmalıdır.

Interest paid/received, dividend received ve current income tax paid için embedded accrual reversal ile authoritative actual cash amount **birlikte** zorunludur; biri eksikse direct cash movement evidence-only kalır fakat aggregate contributor olamaz, ilgili aggregate `None/PARTIAL` olur. Bu exact durumda authoritative cash line `canonical_amount=None`, `evidence_kind=UNAVAILABLE`, `presentation_allocations=()`, `missing_inputs` içinde eksik reversal component code'u taşır; known direct movement yalnız evidence reference'ta kalır. Aksi davranış net profit etkisini iki kez sayar. `PROVEN_DIVIDENDS_PAID` P&L reversal istemeyen tek istisnadır; direct authoritative payment evidence contributor olmak için yeterlidir. Bir bridge component veya sign provenance eksikse bridge kullanılmaz.

### 15.2 Working-capital işaret kuralları

Her account için `delta = closing_balance - opening_balance`:

| Account nature | Delta | Cash-flow etkisi |
|---|---:|---:|
| Operating asset | artış `> 0` | `-delta` — outflow |
| Operating asset | azalış `< 0` | `-delta` — inflow |
| Operating liability | artış `> 0` | `+delta` — inflow |
| Operating liability | azalış `< 0` | `+delta` — outflow |

Cash/cash-equivalent hesapları working capital dışında tutulur. Financing liabilities, tax/interest payable, investing assets ve equity hesapları generic working-capital toplamına giremez.

Current/prior account mapping aynı registry version ile yapılır. Bir hesap yalnız bir dönemde varsa diğer dönem bakiyesi ancak authoritative trial balance o hesabın gerçekten bulunmadığını ve sıfır bakiyeli olduğunu kanıtlıyorsa `0` kabul edilebilir; kaynak veri eksikse `None` kalır.

### 15.3 Non-cash adjustment

- Direct IS'de açık amortisman/itfa: `DERIVED`, çünkü net profit'ten geri eklenir fakat kaynak tutar explicit'tir.
- Mizan hesap kodu ve hareketiyle doğrulanmış amortisman: `DERIVED`.
- Provision, impairment, revaluation, disposal gain/loss ve non-cash FX yalnız closed mapping + authoritative evidence ile kullanılır.
- Deferred-tax expense/income yalnız dedicated authoritative evidence ile `OTHER_PROVEN_NON_CASH_ADJUSTMENTS` içinde add-back/removal olur; `CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL` ile karıştırılmaz. Current + deferred tax aynı periodda line-level dedup/no-double-count invariant'ına tabidir.
- Expense toplamından tahmini amortisman ayrıştırılmaz.
- Non-cash borç-sermaye dönüşümü cash-flow değildir; evidence kaydında dışlanır.
- Profit/loss başlangıç işareti sabittir: profit pozitif, loss negatif.
- Accumulated depreciation bilanço hareketi tek başına period depreciation expense kanıtı değildir.

## 16. Investing Cash Flow

Investing line'lar yalnız authoritative gross movement evidence varsa `EXACT` veya `DERIVED` olabilir:

- PPE/intangible acquisitions negatif;
- disposals pozitif;
- financial investment purchases negatif, disposals/redemptions pozitif;
- satın alınan/satılan işletme veya iştirak hareketi v1 registry'de açık mapping yoksa `UNAVAILABLE`.

Yalnız opening/closing asset balance farkı:

- depreciation,
- impairment,
- revaluation,
- transfer,
- disposal,
- acquisition,
- FX

etkilerini ayırmadığı için brüt capex/sale üretemez. Bütün gerekli bridge bileşenleri kanıtlıysa derived gross movement hesaplanabilir. Bileşenler eksikse yalnız `ESTIMATED_NET_INVESTMENT_MOVEMENT` veya `UNAVAILABLE` üretilebilir.

Net estimate de ham delta değildir. Her investing asset family için economic debit-balance convention altında exact residual formülü:

```text
asset_delta = closing_economic_balance - opening_economic_balance

estimated_net_investment_cash_flow =
    -(asset_delta - signed_proven_noncash_asset_movement)
```

`signed_proven_noncash_asset_movement`, yalnız aynı account family/flow window için closed bridge ledger'daki authoritative bileşenlerin toplamıdır. İşaret manifesti: depreciation/amortization/impairment asset azaltımı olarak negatif; upward/downward revaluation ve FX/translation actual signed asset-balance etkisiyle; non-cash acquisition/lease recognition pozitif; transfer family'ye girişte pozitif, çıkışta negatif ve paired transfer ID ile net-zero; disposal gain pozitif/loss negatif bridge correction olarak yalnız carrying-amount derecognition ve gain/loss kanıtı birlikteyse kullanılır. Disposal carrying amount delta içinde kalır, ikinci kez ledger'a yazılmaz. Bilinmeyen component sıfır sayılamaz.

Buradaki `opening_economic_balance`/`closing_economic_balance` tek hesap veya gross `PPE` role toplamı değildir; Section 10 exact family manifestinden hesaplanan `NET_CARRYING_ASSET family_balance` değeridir. Family code, balance basis ve `account_family_reference_digest` current/prior account evidence ile her bridge component'ta exact aynı olmalıdır. Gross ve contra member'lar önce ayrı economic balance üretir, yalnız family formula'sında birleştirilir. Başka family, null family, registry-digest mismatch veya incomplete member coverage residual estimate'i `UNAVAILABLE` yapar.

Estimate eligibility exact'tir: ilgili closed non-cash bridge manifestindeki her category ya authoritative amount taşır ya `PROVEN_NOT_APPLICABLE` exact zero proof'u taşır; herhangi bir category `UNKNOWN` ise estimated line da `UNAVAILABLE` olur. Gross acquisition/disposal evidence varsa o family için proven gross lines kullanılır ve estimated residual yasaktır. Gross lines ile estimated residual aynı account/evidence component'ini paylaşamaz; source component ID/digest bazında exact-one dedup uygulanır. OCF'deki depreciation/non-cash add-back aynı evidence'a referans verebilir fakat investing residual ledger'da yalnız balance-bridge correction olarak kullanılır; ikinci cash contributor oluşturmaz.

```text
proven_capital_expenditure_outflow_magnitude =
    abs(PROVEN_PPE_ACQUISITIONS) + abs(PROVEN_INTANGIBLE_ACQUISITIONS)

free_cash_flow = operating_cash_flow - proven_capital_expenditure_outflow_magnitude
```

FCF operand'ına financial investment purchase, disposal proceeds veya estimated net investment movement girmez. İki acquisition line'ı da amount-known (`EXACT/DERIVED`) veya authoritative `PROVEN_NOT_APPLICABLE` exact zero olmalıdır. Bunlardan biri `ESTIMATED`, `UNKNOWN` veya `UNAVAILABLE` ise `free_cash_flow=None`; optional analytics completeness bunu unavailable sayar.

## 17. Financing Cash Flow

- `PROVEN_BORROWING_PROCEEDS` ve `PROVEN_DEBT_REPAYMENTS` ayrı line item'lardır.
- Yalnız net debt balance değişimi brüt borrowing/repayment'e ayrılamaz.
- Gross evidence yoksa `ESTIMATED_NET_DEBT_MOVEMENT` üretilebilir; iki brüt satır `UNAVAILABLE` kalır.
- Equity contribution yalnız cash evidence ile pozitif financing flow'dur.
- Dividend paid yalnız actual cash-payment evidence ile negatif financing flow'dur.
- Retained earnings değişimi dividend değildir.
- Debt-to-equity conversion, lease recognition, accrued interest ve benzeri non-cash hareketler cash-flow dışında tutulur.

Financing subtotal, yalnız line item amount'ları biliniyorsa hesaplanır. `UNAVAILABLE` gross line'ların estimated net replacement'ı varsa subtotal `ESTIMATED`; replacement da yoksa subtotal `None` olur.

Her borrowing family için credit-balance convention altında exact residual:

```text
debt_delta = closing_economic_balance - opening_economic_balance

estimated_net_debt_cash_flow =
    debt_delta - signed_proven_noncash_debt_movement
```

Closed debt bridge ledger lease recognition/modification, debt-to-equity conversion, non-cash acquisition financing, capitalized interest, transfer/reclassification ve FX/translation etkilerini liability delta üzerindeki signed amount'larıyla taşır. Artış pozitif, azalış negatif olur. Her category authoritative amount veya `PROVEN_NOT_APPLICABLE` proof'u taşımadan residual estimate üretilemez; unknown component → `ESTIMATED_NET_DEBT_MOVEMENT=None/UNAVAILABLE`. Gross borrowing/repayment evidence varsa aynı borrowing family'de estimated residual yasaktır. Principal cash movement, non-cash ledger ve accrual interest bridge source component ID/digest bazında exact-one assignment'a tabidir; accrued/capitalized interest ne debt principal cash flow'u ne actual interest paid olarak iki kez sayılamaz.

`debt_delta`, Section 10'daki exact `BORROWING_GROSS / GROSS_LIABILITY_OBLIGATION` family balance farkıdır; arbitrary BORROWING-like veya unclassified account toplamı değildir. Current/prior principal membership ve bridge family code/basis/reference digest parity'si zorunludur. V1 manifestinde liability-contra member yoktur; non-zero `302/308/402/408` veya başka unresolved borrowing candidate family completeness'ini kapatır ve estimated debt cash flow üretilmez.

## 18. Faiz, Vergi, Temettü ve Kur Farkı

1. Income Statement `financing_expenses` actual interest paid değildir.
2. Tax expense actual income tax paid değildir.
3. Declared dividend actual dividend payment değildir.
4. Cash-paid line için ödeme hareketi veya opening/accrual/closing bridge'inin bütün bileşenleri gerekir.
5. Canonical cash-paid tutarı bir kez hesaplanır; activity `CashFlowPresentationPolicy` ile atanır.
6. FX effect yalnız foreign-currency cash balances ve authoritative conversion evidence ile üretilebilir.
7. Reconciliation residual'ı FX effect olamaz.
8. FX evidence yoksa `authoritative_fx_effect=None`; zero varsayılmaz.

Buradaki FX event evidence ile Section 8 monetary-source translation farklıdır. V1 bütün source amount'larını functional TRY/major-unit olarak kabul eder; yabancı para hesabının authoritative muhasebe sisteminde kaydedilmiş TRY karşılığı FX hareketi, exact event/source proof'uyla `FX_OR_TRANSLATION` component olabilir. Engine foreign source currency'yi kendisi çeviremez ve `translation_provenance_digest` üretmez. Yani foreign-currency source payload'ı reddedilirken authoritative TRY-denominated FX event amount'ı kabul edilebilir; ikisi birbirinin fallback'i değildir.

## 19. Reconciliation

Bağlayıcı formüller:

```text
opening_cash = prior-period cash and cash equivalents
closing_cash = current-period cash and cash equivalents

opening_cash == prior Balance Sheet reported cash and cash equivalents
closing_cash == current Balance Sheet reported cash and cash equivalents

balance_sheet_net_change = closing_cash - opening_cash

calculated_net_change =
    operating_cash_flow
  + investing_cash_flow
  + financing_cash_flow
  + authoritative_fx_effect
  + authoritative_reclassification_effect

reconciliation_difference =
    balance_sheet_net_change - calculated_net_change
```

Bir bileşen `None` ise `calculated_net_change` ve `reconciliation_difference` `None` olur; kısmi toplama eksik bileşeni sıfır saymaz.

İlk iki parity eşitliği arithmetic öncesi mandatory endpoint gate'idir. İki taraftan biri missing ise yalnız `INSUFFICIENT_DATA`; iki non-null authoritative değer farklıysa `SOURCE_EVIDENCE_CONFLICT` failure outcome'u üretilir. Reconciliation tolerance bu endpoint farkına uygulanmaz ve endpoint mismatch'i operating/investing/financing/FX/reclassification residual'ına dönüştürülmez.

### 19.1 Versioned tolerance

`CASH_FLOW_RECONCILIATION_POLICY_VERSION = "1.0.0"`:

```text
rounding_tolerance = max(Decimal("1.00"), abs(balance_sheet_net_change) * Decimal("0.0001"))
material_threshold = max(Decimal("100.00"), abs(balance_sheet_net_change) * Decimal("0.005"))
```

| Fark | Reconciliation status |
|---|---|
| Minimum dönem zemini yok | `NOT_PERFORMED_INSUFFICIENT_DATA` |
| Minimum zemin var, aggregate/applicability bileşeni eksik | `NOT_PERFORMED_INCOMPLETE_COMPONENTS` |
| `diff == 0` | `RECONCILED` |
| `0 < abs(diff) <= rounding_tolerance` | `ROUNDING_DIFFERENCE`; stored difference korunur, sessizce zero yapılmaz |
| rounding üstü, material dahil/altı | `UNRECONCILED_NON_MATERIAL` |
| `abs(diff) > material_threshold` | `UNRECONCILED_MATERIAL` |

`RECONCILED` ve `ROUNDING_DIFFERENCE` outer result'ta reconciled ailesine map edilir. Reference zero ise yüzdelik hesaplanmaz, mutlak eşikler uygulanır.

## 20. Status ve Persistence Decision Matrix

| Cash-flow status | Koşul | Engine execution | CashFlowResult payload | FinancialAnalysisResult owner | Terminal run record |
|---|---|---|---|---|---|
| `COMPLETE_RECONCILED` | Tüm manifest satırları exact/derived; estimated=0, unavailable=0; tolerance içinde | `COMPLETED` | var | persisted `COMPLETED` | persisted |
| `COMPLETE_UNRECONCILED` | Tüm manifest satırları exact/derived; estimated=0, unavailable=0; tolerance dışında | `DEGRADED` | var | persisted `COMPLETED` + warning inventory | persisted |
| `PARTIAL_RECONCILED` | Mandatory statement line'da estimated/unavailable var fakat bütün net-change bileşenleri available ve tolerance içinde | `DEGRADED` | var | persisted `COMPLETED` + partial metadata | persisted |
| `PARTIAL_UNRECONCILED` | Mandatory line estimated/unavailable; reconciliation ya outside tolerance ya da incomplete components nedeniyle `NOT_PERFORMED_INCOMPLETE_COMPONENTS`; non-cash-ground non-zero `UNRESOLVED` row varsa üç activity subtotal'ı unavailable | `DEGRADED` | var | persisted `COMPLETED` + warnings | persisted |
| `INSUFFICIENT_DATA` | Minimum source/period/cash zemini yok; integrity sağlam | `DEGRADED` | var; parasal alanlar `None`, missing inventory dolu | persisted `COMPLETED` diagnostic financial result | persisted |
| `INVALID_INPUT` engine failure outcome | Engine/builder'a ulaşmış şekil/version/policy/mapping/Decimal contract geçersiz | `FAILED` | yok | üretilmez | exact Cash Flow code'lu structured error persisted |
| `INTEGRITY_FAILURE` engine failure outcome | Engine/builder input'unda currency/evidence/mapping integrity conflict | `FAILED` | yok | üretilmez | exact Cash Flow code'lu redacted structured error persisted |

`FinancialAnalysisResult.status=COMPLETED`, payload'ın muhasebesel olarak complete olduğu anlamına gelmez; yalnız immutable result payload'ın başarıyla üretildiğini/persist edildiğini belirtir. Muhasebesel durum yalnız `CashFlowResult.status`'tır.

Endpoint parity mismatch result-bearing status değildir: `SOURCE_EVIDENCE_CONFLICT` typed failure üretir. Non-zero unresolved cash candidate `INSUFFICIENT_DATA`; başka non-zero unresolved account zorunlu olarak `PARTIAL_UNRECONCILED` olur. Bu iki durum `COMPLETE_*` veya `PARTIAL_RECONCILED` olarak yükseltilemez.

`INSUFFICIENT_DATA` sonucu aynı fingerprint ile idempotent olarak tekrar okunabilir. Yeni veya düzeltilmiş kaynak digest'i fingerprint'i değiştirir ve yeni run gerektirir.

### 20.1 Failure-origin ve lifecycle manifesti

On altı `CashFlowErrorCode` tek public taxonomy'dir fakat her code engine outcome değildir. Origin/lifecycle manifesti kapalıdır:

| Code | Origin | Engine çağrısı | Terminal run | Application davranışı |
|---|---|---:|---:|---|
| `INVALID_CONTRACT` | engine/builder | evet | persisted terminal result | success outcome içinde algorithm-derived run-status command DTO + execution error |
| `PERIOD_NOT_COMPARABLE` | pre-run comparable resolver | hayır | yok | failure outcome, `INVALID_COMMAND`, exact CF code |
| `PERIOD_SELECTION_AMBIGUOUS` | pre-run comparable resolver | hayır | yok | failure outcome, `INVALID_COMMAND`, exact CF code |
| `POLICY_VERSION_UNSUPPORTED` | pre-run policy resolver veya engine guard | origin'e göre | yalnız engine-origin ise terminal result persisted | resolver'da `INVALID_COMMAND`; engine'de algorithm-derived command DTO |
| `MAPPING_REGISTRY_VERSION_UNSUPPORTED` | engine registry guard | evet | terminal result persisted | algorithm-derived command DTO |
| `DECIMAL_NON_FINITE_OR_SCALE_INVALID` | engine/builder | evet | terminal result persisted | algorithm-derived command DTO |
| `SOURCE_NOT_FOUND` | pre-run source resolver | hayır | yok | failure outcome, `NOT_FOUND`, exact CF code |
| `SOURCE_SCOPE_MISMATCH` | pre-run source resolver | hayır | yok | failure outcome, `SCOPE_MISMATCH`, exact CF code |
| `SOURCE_STATUS_INVALID` | pre-run source resolver | hayır | yok | failure outcome, `PERSISTENCE_INTEGRITY_ERROR`, exact CF code |
| `SOURCE_DIGEST_MISMATCH` | pre-run source resolver/terminal revalidation | hayır | yok | failure outcome, `PERSISTENCE_INTEGRITY_ERROR`, exact CF code |
| `SOURCE_CURRENCY_MISMATCH` | resolver veya same-run builder | origin'e göre | yalnız builder-origin ise terminal result persisted | resolver'da integrity error; builder'da algorithm-derived command DTO |
| `SOURCE_EVIDENCE_CONFLICT` | resolver veya engine/builder | origin'e göre | yalnız engine-origin ise terminal result persisted | resolver'da integrity error; engine'de algorithm-derived command DTO |
| `MAPPING_CONFLICT` | engine registry/compiler | evet | terminal result persisted | algorithm-derived command DTO |
| `PERSISTENCE_INTEGRITY_FAILURE` | terminal persistence | tamamlanmış olabilir | commit yok | failure outcome, `PERSISTENCE_INTEGRITY_ERROR` |
| `SOURCE_RESOLUTION_UNAVAILABLE` | pre-run resolver infrastructure | hayır | yok | failure outcome, `PERSISTENCE_UNAVAILABLE`, retryable |
| `PERSISTENCE_UNAVAILABLE` | terminal persistence infrastructure | tamamlanmış olabilir | commit yok | failure outcome, `PERSISTENCE_UNAVAILABLE`, retryable |

`CashFlowEngineFailure` constructor'ı yalnız origin manifestinde engine/builder bulunan code'ları kabul eder; resolver/persistence-only code ile synthetic `CashFlowEngineOutcome` kurmak yasaktır. Resolver typed `CashFlowPortError` döndürür/atıp application boundary'de normalize edilir; `EngineRawInputsV3` error sentinel taşımaz ve resolver error için sahte `OrchestrationRunResultV3` yaratılmaz. Terminal persistence failure da engine sonucunu rewrite etmez.

Pure orchestrator typed Cash Flow failure'ı exception değildir: valid `OrchestrationRunResultV3` içinde Cash Flow execution `FAILED` + exact `StructuredErrorV3` üretir. Overall `RunStatusV3` hardcode edilmez; donmuş 5.0A algoritmasının V3 enum-copy karşılığı bütün execution record'larından hesaplanır: cancelled → `CANCELLED`; record yok veya alive status yok → `FAILED`; en az bir alive (`COMPLETED|DEGRADED|REUSED`) ve en az bir `FAILED|SKIPPED` → `PARTIALLY_COMPLETED`; aksi halde `DEGRADED` varsa `COMPLETED_WITH_DEGRADATIONS`; aksi halde `FULLY_COMPLETED`. BS/IS alive iken Cash Flow typed failure'ın tipik overall status'u `PARTIALLY_COMPLETED`'dır. Pre-persistence authorization revalidation'dan sonra application bu terminal run'ı owner olmadan persist eder; commit/finalize başarılıysa `ApplicationOutcomeV2.success=True`, value zorunlu `AnalysisCommandResultDTOV2.status` exact `run_result.status` projection'ıdır. Yalnız orchestrator port'unun beklenmeyen exception/contract dışı dönüşü `EXECUTION_FAILED`, no-terminal-persistence failure outcome'udur. Böylece retry/idempotent read terminal result'ı yeniden çalıştırmaz.

## 21. Evidence, Provenance ve Auditability

Her non-null line item en az bir `CashFlowEvidenceReference` taşır. `UNAVAILABLE` line en az bir `missing_inputs` reason taşır. Kanıt zinciri:

```text
line item
  → mapping_id / derivation_code
  → source role
  → source FinancialAnalysisResult id
  → source canonical digest
  → source period
  → immutable cross-period lineage row
```

Evidence sınıfı kuralları:

- `EXACT`: authoritative kaynaktaki doğrudan cash movement/balance.
- `DERIVED`: bütün girdileri exact/derived olan açık formül sonucu.
- `ESTIMATED`: net movement gibi sınırlı, açıkça tanımlı approximation.
- `UNAVAILABLE`: güvenilir değer üretilemedi.

Bir derived line'ın reliability'si kaynaklarının en zayıf evidence kind'ından daha güçlü olamaz. `ESTIMATED` kullanan aggregate en fazla `ESTIMATED` olur. Evidence roll-up keyfi bir confidence score üretmez.

Warnings deterministic, kapalı code'lu ve hassas veri içermeyen metadata taşır. Raw account name, raw exception, SQL, DSN, dosya içeriği veya PII public warning/error alanına girmez.

## 22. Cross-Period Lineage — Additive Immutable Model

Mevcut `financial_analysis_result_sources` aynı-period FK'leri nedeniyle değiştirilmeyecek; 5.0B contract'ı bozulmayacaktır. Tek yeni additive tablo:

```text
cash_flow_cross_period_lineage
----------------------------------------------
id                              UUID PK
cash_flow_analysis_result_id    UUID NOT NULL
tenant_id                       UUID NOT NULL
company_id                      UUID NOT NULL
current_period_id               UUID NOT NULL
prior_period_id                 UUID NULL
source_period_id                UUID NOT NULL
source_analysis_result_id       UUID NOT NULL
source_role                     VARCHAR NOT NULL
source_canonical_digest         VARCHAR(64) NOT NULL
source_provenance_digest        VARCHAR(64) NOT NULL
source_analysis_type            VARCHAR NOT NULL
source_engine_version           VARCHAR(32) NOT NULL
current_period_descriptor_digest VARCHAR(64) NOT NULL
prior_period_descriptor_digest  VARCHAR(64) NULL
comparability_proof_digest      VARCHAR(64) NULL
created_at                      TIMESTAMPTZ NOT NULL
```

### 22.1 Constraint'ler

- Parent FK: `(cash_flow_analysis_result_id, company_id, current_period_id)` → `financial_analysis_results(id, company_id, period_id)`.
- Source FK: `(source_analysis_result_id, company_id, source_period_id)` → `financial_analysis_results(id, company_id, period_id)`.
- `(company_id, tenant_id)` composite FK → `companies(id, tenant_id)`; ORM metadata'da hedef `UniqueConstraint("id", "tenant_id", name="uq_companies_id_tenant_id")` ile migration DDL birebir aynı olmalıdır. Production cash-flow unbound/null-tenant company kabul etmez.
- Current/prior period-company composite FK'leri zorunludur; `prior_period_id` COMPLETE/PARTIAL için dolu, prior eksik `INSUFFICIENT_DATA` için null olabilir.
- Parent `analysis_type='cash_flow'` ve source role/type matrix PostgreSQL trigger ile doğrulanır.
- `source_canonical_digest` ve `source_provenance_digest` exact lowercase `[0-9a-f]{64}` CHECK taşır.
- Üç period/proof digest kolonu lowercase `[0-9a-f]{64}` formatındadır. COMPLETE/PARTIAL satırlarda üçü de non-null; `INSUFFICIENT_DATA` lineage satırında current digest zorunlu, prior/proof ya hep birlikte dolu ya hep birlikte null'dır.
- `source_role` kapalı CHECK enum'dur.
- `UNIQUE(cash_flow_analysis_result_id, source_role)` — duplicate role yasak.
- `UNIQUE(cash_flow_analysis_result_id, source_analysis_result_id)` — aynı kaynak iki role ile kullanılamaz.
- `source_period_id <> current_period_id` yalnız `PRIOR_*` role'lerinde zorunlu; `CURRENT_*` role'lerinde eşitlik zorunlu.
- Aynı parent'ın bütün satırları aynı tenant/company/current/prior binding'ini taşır; trigger parent satırını kilitler ve `IS NOT DISTINCT FROM` eşitliği uygular.
- `PRIOR_*` source period, comparable-period resolver'ın seçtiği exact prior period olmalıdır.
- stored source payload digest insert anında source owner digest ile; stored provenance digest Company namespace lock'u altında Section 8 exact bounded recursive `cf.provenance_closure.v1` bytes'ından yeniden üretilen digest ile eşit olmalıdır. Direct row-set hash'i veya yalnız root binding listesi yeterli değildir.
- Bütün yeni FK'ler non-deferrable `ON DELETE RESTRICT`'tir; ORM relationship'lerde `delete`/`delete-orphan` cascade yoktur ve payload içeren repr üretilmez (UUID-only safe repr). Model/DDL parity testi FK action, deferrability, cascade ve repr'i kilitler.
- Ek `INDEX(source_analysis_result_id)` zorunludur. `(cash_flow_analysis_result_id, source_role)` lookup'u zaten named UNIQUE constraint'in backing B-tree index'iyle karşılanır; duplicate ikinci index oluşturulmaz.
- Candidate-set phantom koruması company-scoped relational namespace lock'tur. Migration 1, her `financial_periods` INSERT/UPDATE/DELETE için affected OLD/NEW company UUID'lerini canonical sırada `SELECT companies ... FOR UPDATE NOWAIT` ile kilitleyen trigger ekler. Migration 2 aynı fail-fast parent-lock protokolünü her `financial_documents`, `financial_analysis_results` ve `financial_analysis_result_sources` INSERT/UPDATE/DELETE, `cash_flow_cross_period_lineage` INSERT ve `NEW.financial_analysis_result_id IS NOT NULL` olan **her** `orchestration_engine_executions` INSERT'e uygular. Execution `00_namespace` trigger'ı owner'a SELECT yapmadan yalnız immutable `NEW.run_id → orchestration_runs.company_id` yoluyla company'yi çözer/kilitler; engine⇔analysis-type branch'i ancak lock'tan sonraki `10_validate` içinde owner okunarak belirlenir. PostgreSQL aynı event/timing trigger'larını isim sırasıyla çalıştırdığı için adlandırma executable contract'tır: namespace trigger'ı exact `trg_cf_00_namespace_<table>_<event>`, validation trigger'ı `trg_cf_10_validate_<table>_<event>`, immutability/seal trigger'ı `trg_cf_20_guard_<table>_<event>` olur; `<event>` lowercase `ins|upd|del` değeridir. Bir event'te birden çok validation gerekiyorsa tek `10_validate` function body içinde declaration-order çalışır; aynı prefix/ordinalle ikinci trigger kurulamaz. Catalog/startup test'i exact table/event/timing/name/function manifestini ve `00 < 10 < 20` lexical sırasını doğrular. Her namespace function etkilenebilecek bütün company UUID'lerini unique+sorted alır ve hiçbir owner/parent/closure SELECT'i `00` öncesinde çalışmaz. Row-level UPDATE/DELETE hedef satırı trigger'dan önce kilitleyebildiği için `NOWAIT` bağlayıcıdır: company lock başkasındaysa statement SQLSTATE `55P03` ile derhal rollback olur; target row'u tutup company lock beklemek yasaktır ve repository bu durumu redacted retryable infrastructure conflict'e normalize eder fakat otomatik retry yapmaz. Cash Flow V3 terminal repository herhangi bir aday sorgusundan önce aynı company row'u blocking `FOR UPDATE` ile alır ve bütün document/period/result/binding candidate revalidation'ı canonical plain `SELECT` ile yapar. Terminal kodu child satırlara açık row lock istemez; non-deferrable FK'nin dahili referential check'i yalnız fail-fast mutation transaction'ı rollback ederken kısa süre bekleyebilir ve positive bounded `lock_timeout` aşılırsa tüm terminal write fail-closed rollback olur. Bu trigger-backed FK namespace serialization'ı distributed lock, active-job registry veya application mutex değildir; yalnız aynı company'nin document/period/source candidate kümesini terminal revalidation süresince sabitler.
- Trusted repository/strict codec, owner veya lineage stage edilmeden önce source payload'ı kendi authoritative codec'iyle yeniden encode eder ve stored digest'i constant-time karşılaştırır; yalnız digest kolonuna güvenmez. Aynı rehash existing-owner resolution, every load ve resume/reuse yolunda tekrarlanır.
- UPDATE ve DELETE PostgreSQL immutable trigger ile reddedilir.
- `V3_TERMINAL_PROTECTED_ROOTS`, `orchestration_engine_executions.financial_analysis_result_id` ile bir exact V3 run'a (`schema/model/plan=3.0.0`) bağlanan **her** BS/IS/Cash Flow/Ratio financial owner'dır; Cash Flow owner'lar zero-lineage `INSUFFICIENT_DATA` dahil ayrıca unconditional seed'dir. Protected graph seed'leri bu roots, Cash Flow cross-period lineage source IDs ve bunların Section 8 bounded recursive `financial_analysis_result_sources` descendants'ıdır. Böylece no-CF V3 BS/IS/Ratio run'ı ve Ratio→Cash Flow outbound edge'i de korunur; V2 behavior genişletilmez. Protected bütün `FinancialAnalysisResult` satırlarının bütün fiziksel kolonları immutable'dır. Trigger protected row için `TG_OP='UPDATE'` veya `TG_OP='DELETE'` gördüğü anda değerleri karşılaştırmadan unconditional `RAISE` eder; no-op UPDATE dahi reddedilir. Protection predicate OLD/NEW id'yi cycle-safe recursive CTE ile herhangi bir protected graph'ta arar; depth cap'e gelmek veya cycle görmek mutation'a izin vermez, integrity raise eder. `OLD.analysis_type='cash_flow' OR NEW.analysis_type='cash_flow'` ayrıca non-cash owner'ı Cash Flow'a UPDATE ile çevirme bypass'ını kapatır. `id`, company/period/type/source-mode, `document_id`, status, `result_json`, `error_message`, engine/version/digest, started/completed/created/audit timestamps ve gelecekte eklenen kolon dahil alan allowlist'i yoktur.
- `financial_analysis_result_sources` graph'ı da aynı protected graph boyunca transitive immutable'dır. Guard iki bağımsız predicate'i yalnız edge'in **outbound parent** kimliği olan `OLD.analysis_result_id`/`NEW.analysis_result_id` üzerinde uygular: (a) parent owner `analysis_type='cash_flow'` ise her INSERT/UPDATE/DELETE unconditional reddedilir; Cash Flow owner'ın legacy source tablosunda daima exact zero satırı vardır; (b) parent herhangi bir `V3_TERMINAL_PROTECTED_ROOTS` closure'ında veya Cash Flow lineage-source closure'ında reachable ise sonradan INSERT, her UPDATE ve her DELETE unconditional reddedilir. UPDATE'te hem OLD hem NEW parent predicate'i uygulanır; böylece protected parent'tan/parent'a reparent bypass yoktur. Target'ın protected olması tek başına incoming edge'i yasaklamaz: unrelated, unprotected bir parent'ın protected target'ı normal FK/scope kurallarıyla source göstermesi izinlidir ve protected owner'ın frozen outbound provenance'ını değiştirmez. Same-run BS/IS owner ve bütün same-period source-binding satırları Cash Flow lineage ve V3 owner-bearing execution INSERT'ten önce stage/flush edilir. Trusted repository company namespace lock'u altında recursive closure'u canonical plain SELECT/CTE ile okur, Section 8 bytes'ını Python strict codec ile yeniden üretir ve `source_provenance_digest` ile karşılaştırır; PostgreSQL trigger SHA-256 üretmez. Lineage/execution trigger aynı company namespace lock'unu fail-fast alıp bounded/cycle-free structural closure ve transitive immutability koşullarını uygular; binding veya source-owner row lock'u istemez. Source-binding INSERT/UPDATE/DELETE namespace trigger'ı parent'a pre-lock SELECT yapmaz; tabloda zaten NOT NULL bulunan `OLD.company_id`/`NEW.company_id` union'unu unique+canonical sırada `NOWAIT` kilitler. Parent/target/FK/type/immutability çözümlemeleri yalnız bu Company lock'tan sonra çalışır. Concurrent execution/lineage insert ile provenance mutation bu tek namespace'te serialize olur. Bu ayrı digest donmuş 5.0B `owner_content_digest` byte domain'ini değiştirmez.
- Protected graph'ın belge zinciri de transitive immutable'dır. Protected document seti, her protected root/descendant owner'ın primary `document_id` alanı ile frozen outbound binding `source_document_id` değerlerinin union'ıdır. `financial_documents` BEFORE UPDATE/DELETE guard'ı OLD veya NEW id protected setteyse bütün fiziksel kolonlar için unconditional raise eder; no-op UPDATE, checksum/size/type/status/path-metadata/company/period/id değişikliği ve DELETE reddedilir. Protection predicate OLD/NEW kimliklerini birlikte inceler; reparent/key-change bypass yoktur. Exact `trg_cf_00_namespace_*` lexical olarak `trg_cf_20_guard_*` öncesinde çalışır. Bu DB immutability, content-addressed write-once external object + terminal/load/resume byte rehash proof'uyla birlikte durable provenance sağlar; transient planned proof tek başına yeterli sayılmaz.
- `source_analysis_type` ve `source_engine_version`, insert anında source owner'ın exact değerleriyle karşılaştırılan immutable audit snapshot'larıdır; mismatch reddedilir.
- Lineage BEFORE INSERT trigger'ı önce NEW.company_id namespace'ini `FOR UPDATE NOWAIT` alır; parent için `analysis_type=CASH_FLOW`, `source_mode=MULTI_SOURCE_DERIVED`, `document_id IS NULL`, `status=COMPLETED` ve non-null payload/lowercase-hex digest formatını; source için role/type matrix yanında `status=COMPLETED`, non-null payload/lowercase-hex digest, exact company/period/tenant ve stored type/version/digest **column equality**'sini plain SELECT ile doğrular. Aynı company namespace'i bütün parent/source/period mutasyonlarını dışladığından trigger'ın ikinci bir source-row lock'u istemesi yasaktır; referential existence ve delete/key-change koruması non-deferrable FK'ye aittir.
- Aynı trigger append seal uygular: parent Cash Flow owner herhangi bir committed veya current-transaction `orchestration_engine_executions.financial_analysis_result_id` tarafından sahiplenilmişse yeni lineage INSERT unconditional reddedilir. Initial terminal sıra owner → bütün lineage rows → owner-bearing execution'dır; execution INSERT aynı Company namespace'ini alıp graph'ı seal eder. Existing-owner reuse yeni lineage yazmaz, exact sealed graph'ı doğrular. Direct/concurrent lineage ile execution insert'ten hangisi namespace'i önce alırsa tamamlanır; execution seal önceyse append reddedilir, lineage önceyse execution yalnız final exact graph revalidation'dan sonra seal eder. Post-terminal append, optional role ekleme dahil, imkânsızdır.
- Cash Flow owner'ın orphan commit'i ayrıca exact named `trg_cf_90_owner_sealed_deferred` constraint trigger'ıyla engellenir. Trigger `financial_analysis_results` üzerinde `AFTER INSERT`, `DEFERRABLE INITIALLY DEFERRED` çalışır ve transaction sonundaki yeni Cash Flow owner için en az bir aynı-scope current-transaction **non-reused** `orchestration_engine_executions` row'u ister: `engine_code='cash_flow'`, `result_kind='CashFlowResult'`, owner FK exact, V3 schema/model/fingerprint versions exact, non-null lowercase SHA-256 biçimli `owner_content_digest`, status `COMPLETED|DEGRADED` ve `reused_from_engine_execution_id IS NULL`. Forged yalnız-REUSED seal geçemez. Sıfır origin reference commit'i reddeder. Sonraki immutable references yalnız bütün DB-provable scope/engine/kind/version/status alanları ve stored owner-content digest değerleri exact aynıysa kabul edilir; herhangi bir tutarsız reference integrity failure'dır. PostgreSQL wrapper bytes/hash üretmez: FAR payload→five-field owner wrapper canonical rehash/equality'si trusted repository'nin write/read/resume/reuse sorumluluğudur. Existing-owner resolver exact payload+lineage+wrapper rehash eşleşmesine ek olarak bu sealed-reference setini doğrular; orphan/unsealed veya inconsistent candidate'ı asla reuse etmez. Initial terminal sıra owner → lineage → owner-bearing execution olduğu için deferred check aynı transaction'da geçer.
- Her owner-bearing execution INSERT'i exact `trg_cf_10_validate_orchestration_engine_executions_ins` tarafından run+owner join'iyle sınıflandırılır. Parent run exact V3 discriminator taşıyorsa dört financial mapping çift yönlü zorunludur: `fs_balance_sheet → (analysis_type=balance_sheet, result_kind=BalanceSheetAnalysisOutcomeV3)`, `fs_income_statement → (income_statement, IncomeStatementAnalysisOutcomeV3)`, `cash_flow → (cash_flow, CashFlowResult)`, `ratio → (analysis_type=financial_ratios, result_kind=dict)`. Ratio analysis-type literal'i mevcut `AnalysisType.FINANCIAL_RATIOS.value` olan exact `financial_ratios` değeridir; kısaltılmış `ratio` storage literal'i geçersizdir. Wrong FS↔IS/Ratio/Cash Flow owner ve wrong kind reddedilir. V3 common guard run company/current-period ile owner company/period parity'sini, engine manifest schema/model/fingerprint versions'ını, owner-content digest format/presence'ını, status/result/reuse XOR'unu ve owner `result_json`/canonical-result-digest parity'sini doğrular; BS/IS diagnostic null-payload istisnası Section 24.8 exact kuralıdır, CF/Ratio payload/digest zorunludur. Exact V2 run bu additive V3 mapping guard'ına girmez ve 5.0B davranışı değişmez.

Cash Flow-specific alt-branch ayrıca `NEW.engine_code='cash_flow' OR referenced owner.analysis_type='cash_flow'` olduğunda çalışır: engine⇔owner/kind pairing, owner legacy source count=0 ve kapalı `inner_status`→execution-status→lineage yapısı zorunludur. Non-reused result execution'da `inner_status` exact beş result-bearing `CashFlowResultStatus.value` değerinden biridir ve reuse FK null'dır: `complete_reconciled → status='completed'`; `complete_unreconciled|partial_reconciled|partial_unreconciled|insufficient_data → status='degraded'`. Null, failure-status veya unknown `inner_status` ile owner seal edilemez. COMPLETE/PARTIAL inner-status'ta DB lineage seti exact üç base role'ü ve yalnız gerçekten kullanılan optional current/prior Trial Balance role subset'ini taşır; `insufficient_data` yalnız structural olarak doğrulanmış role subset'i veya empty set kabul eder ve complete-role varmış gibi yorumlanmaz. Repository strict owner payload'ını decode/rehash edip `CashFlowResult.status.value == NEW.inner_status` ve payload `source_lineage_references` seti == durable lineage seti parity'sini INSERT öncesi ve her read/resume/reuse'da doğrular; SQL trigger JSON codec'i taklit etmez. `REUSED` execution'da reuse FK zorunlu, `inner_status` source execution'ın non-null inner-status'u ve strict decoded owner payload statusuyla exact eşittir; source execution finalized V3 Cash Flow run'ında ve source run DB id'si yeni run'ın immutable `previous_run_id` FK'sine exact eşit olmalıdır. Ayrıca aynı FAR owner/content digest/scope/schema/model/fingerprint/input fingerprint ve aynı verified lineage semantics'i zorunludur; arbitrary older run'dan atlama yasaktır. Deferred owner seal yalnız bu common ve Cash Flow-specific guard'ları geçmiş non-reused row ile sağlanabilir. Bütün mevcut Cash Flow execution references'ın DB-provable digest/scope/version parity'si korunur. SQL trigger payload hashlemez; repository INSERT öncesi ve read/reuse sonrasında strict owner wrapper + recursive provenance/lineage rehash'ini ayrıca yapar.
- Lineage'siz `INSUFFICIENT_DATA` owner bu trigger'a uğramayabileceği için `financial_analysis_results` üzerinde ayrı Cash-Flow BEFORE INSERT guard her owner için exact şunları zorunlu kılar: `analysis_type='cash_flow'`, `source_mode='multi_source_derived'`, `document_id IS NULL`, `status='completed'`, `engine_version='1.0.0'`, non-null `result_json`, lowercase-hex non-null `canonical_result_digest`, `error_message IS NULL`, non-null `started_at/completed_at` ve `completed_at >= started_at`. DTO/repository naive datetime'ı reddeder ve UTC'ye normalize eder; DB kolonları `TIMESTAMPTZ`'dir, ancak PostgreSQL coercion sonrasında client timezone-awareness'ı trigger ile kanıtlamaya çalışmaz. Parent company tenant bindingi ve current period scope'u da doğrulanır. Failure outcome owner yaratamaz. Zero-lineage sonucu trusted repository tarafından strict payload rehash edilmeden yazılamaz; DB trigger format/structural semantics'i, repository canonical bytes equality'sini sağlar.
- Parent/source payload bu tabloda tutulmaz; yalnız ownership ve digest reference vardır.

PostgreSQL trigger Python strict codec byte projection'ını yeniden üretmeye çalışmaz; SQL canonicalizer/`pgcrypto` bağımlılığı yoktur. Katman ayrımı: malformed/non-lowercase digest DB CHECK ile; formatı doğru fakat payload'a yanlış digest repository write-before-stage ile; load/resume corruption repository/snapshot rehash ile reddedilir.

Terminal lock/stage topolojisi same-run owner zamanlamasını açıkça ayırır:

1. Terminal transaction + nested SAVEPOINT açılır. Herhangi bir owner stage edilmeden authoritative `Company` row'u `FOR UPDATE` alınır. Bu lock altındayken exact comparable-period candidate query'si ve bütün authoritative document/prior/TB/existing-owner candidate query'leri baştan canonical plain SELECT ile çalıştırılır; 0/1/>1 cardinality ile selected IDs/digests pre-run context/proof'a exact eşit olmalıdır. Current/prior `FinancialPeriod`, persisted selected sources ve source-binding rows da canonical sırayla plain SELECT edilir; açık `FOR SHARE`/`FOR NO KEY UPDATE` yoktur. Her planned document authoritative write-once store'dan bounded read ile yeniden hashlenir. Company tenant/currency, document scope/type/status/checksum/size/seal proof, period descriptor/proof, source monetary-unit, payload ve provenance digest yeniden doğrulanır.
2. BS → IS owner node'ları sırayla resolve edilir. Existing candidate set company lock altında plain SELECT ile exact 0/1/>1 kuralına göre değerlendirilir. New owner ile bütün same-period source-binding rows aynı SAVEPOINT içinde stage/flush edilir. Her iki modda final owner UUID + canonical payload/owner-content/provenance digest map'e yazılmadan sonraki node'a geçilmez.
3. Cash Flow planned same-run locator'ları bu final map'e çevrilir. Newly staged/reused current BS/IS row ve source-binding seti company namespace lock'u altında tekrar materialize/rehash edilir. Cash Flow existing-owner candidate query'si payload/owner/provenance/period/lineage equality yanında exact sealed V3 execution-reference setini de doğrular: 0 candidate create, 1 fully sealed candidate reuse, >1 semantic candidate veya orphan/inconsistent reference integrity failure'dır. Create yolunda Cash Flow owner + lineage stage edilir; deferred owner-seal execution yazılmadan commit'e izin vermez. Lineage trigger aynı namespace'in tutulduğunu/doğrudan SQL yolunda `NOWAIT` alınabildiğini ve structural equality'yi doğrular.
4. Ratio node'u aynı map'teki gerçek Cash Flow owner'ını supporting source'a dönüştürür. Bütün owner/lineage targeted flush'larından sonra `orchestration_runs` row'u flush edilir; unique winner/loser kararı bu noktada verilir. Winner değilse tüm staged graph SAVEPOINT rollback/discard edilir. Winner ise artifacts/locations, execution rows ve error rows bu sırada yazılır. Her mismatch tüm SAVEPOINT/terminal transaction rollback'idir.

Tek relational namespace lock Company row'udur. Terminal sırası `Company FOR UPDATE` → canonical plain revalidation → BS → IS → Cash Flow → Ratio stage'dir; terminal açık period/source/binding row lock'u almaz. Period, financial-result ve binding row mutation'ları hedef satırı PostgreSQL tarafından önceden kilitlenmiş olsa dahi Company lock'u **bekleyemez**; BEFORE trigger `NOWAIT` başarısızlığında statement/transaction rollback olur. Bu fail-fast kural, terminalin non-deferrable FK kontrolü sırasında hedef satıra geri beklemesiyle oluşabilecek Company↔target-row deadlock'unu kapatır. Candidate mutation terminalden önce commit ederse terminal rerun cardinality/proof mismatch eder; terminal Company lock'unu önce aldıysa mutation `55P03` ile retryable infrastructure conflict olarak dışarı normalize edilir, internal retry yapılmaz. Source-binding mutation da önce commit edip provenance mismatch olur veya fail-fast reddedilir; lineage commit sonrasında immutable guard'da kalıcı reddedilir. Same-run node sırası BS → IS → Cash Flow → Ratio'dur. Henüz oluşmamış UUID'yi pre-lock etme varsayımı yoktur; stale candidate/provenance ile lineage commit edilemez.

`CashFlowResult` içindeki current/prior `CashFlowPeriodDescriptor` snapshot'ları ile üç digest, application owner binding'i ve her lineage row'unda aynen taşınır. Terminal repository Company namespace lock'u altında current/prior `financial_periods` satırlarını canonical plain SELECT ile yeniden materialize eder ve descriptor/proof digest'lerini tekrar hesaplar. Pre-run resolution ile terminal write arasındaki status/date/type/months/currency/basis/policy/annual-boundary değişikliği `PERSISTENCE_INTEGRITY_FAILURE` olur; owner/lineage stage edilmez.

Read mode ayrımı exact'tir. 5.0E `Company.tenant_id` immutability aynen korunur; tenant drift desteklenen bir durum veya test fixture'ı değildir ve her mutation DB'de reddedilir. Ordinary `AnalysisReadPortV2` historical/audit read'i immutable owner payload'ını strict codec/canonical digest ile, stored lineage/proof'un kendi iç parity'sini ve referenced immutable document/source bytes'ını doğrular; sonradan değişmiş current Company currency veya current FinancialPeriod policy metadata'sını historical snapshot'ın yerine koymaz ve yalnız bu drift nedeniyle eski sonucu gizlemez. External object/source corruption yine integrity failure'dır. Buna karşılık `SnapshotReaderPortV3` ile resume/reuse/source-for-new-run path'i Company namespace lock'unu alır; immutable tenant binding yanında current Company currency ve current/prior period metadata'sını stored descriptor/lineage scope'uyla exact karşılaştırır. Currency veya period drift'inde yeni hesap/reuse fail-closed reddedilir ve eski currency/policy ile yeni run başlatılamaz.

### 22.2 Role/type matrix

| Role | Source analysis type | Period relation |
|---|---|---|
| `CURRENT_BALANCE_SHEET` | `balance_sheet` | current |
| `PRIOR_BALANCE_SHEET` | `balance_sheet` | prior |
| `CURRENT_INCOME_STATEMENT` | `income_statement` | current |
| `CURRENT_TRIAL_BALANCE` | `trial_balance` | current; yalnız gerçekten kullanıldıysa |
| `PRIOR_TRIAL_BALANCE` | `trial_balance` | prior; yalnız gerçekten kullanıldıysa |

`PRIOR_INCOME_STATEMENT` v1 minimum contract'ında kullanılmadığı için role enum'a eklenmez. COMPLETE/PARTIAL result exact base role seti `CURRENT_BALANCE_SHEET`, `PRIOR_BALANCE_SHEET`, `CURRENT_INCOME_STATEMENT`'tır; Trial Balance role'leri yalnız account evidence bu kaynaklardan materialize edildiyse eklenir. `INSUFFICIENT_DATA` yalnız gerçekten doğrulanabilen mevcut source role'lerini taşır; missing role payload warning inventory'sinde görünür.

### 22.3 Transaction sınırı

Cash-flow financial owner, cross-period lineage rows, engine execution record, artifacts ve terminal run tek 5.0B terminal persistence transaction'ında atomik yazılır. Cash-flow owner için ayrıca `financial_analysis_result_sources` satırı yazılmaz; beş cash-flow role'ünün tek canonical lineage sahibi yeni tablodur. Eski tablo BS/IS/Ratio için değişmeden kalır.

Physical FK-safe write order ile semantic owner order birleşik ve exact'tir. Terminal transaction + nested SAVEPOINT içinde Company lock/revalidation ve initial existing-run check'ten sonra BS owner/bindings → IS owner/bindings → Cash Flow owner/lineage → Ratio owner/bindings targeted flush edilir; pending run olmadığı için repository autoflush'i disabled/explicit flush'tur. Sonra `orchestration_runs` row'u stage/flush edilir ve unique race burada çözülür. Winner ise artifacts/physical locations → engine executions → orchestration errors yazılır; execution'dan önce run parent artık mevcut olduğu için non-deferrable FK geçerlidir. Loser ise owner/lineage dahil SAVEPOINT'in tamamı rollback/discard edilir. Son parity revalidation'dan sonra commit edilir; deferred Cash Flow owner-seal check execution mevcutken çalışır. Execution'ı run parent'tan önce yazmak yasaktır.

Concurrent idempotent loser akışında:

1. run/owner/lineage/artifact/execution staging'in tamamı tek nested SAVEPOINT içindedir;
2. pre-existing canonical run görülürse veya concurrent run unique flush loser olursa, winner projection'ından önce SAVEPOINT rollback-to-savepoint edilir;
3. staged owner/lineage/artifact/run ORM state'i expunge/discard edilir; initial existing-run check staging öncesi hit ederse cleanup no-op, unique-race path'inde bütün staged owner/lineage/run graph'ını discard eder;
4. loser transaction hiçbir run, owner, lineage, artifact veya execution satırı commit edemez;
5. dönen winner ancak request fingerprint **ve** terminal content digest, V3 contract/schema/model/plan discriminator'ları, tenant/company/period scope ve her execution'ın doğrulanmış owner content/canonical digest + normalized lineage/period proof semantics'i exact eşitse idempotent success olabilir. Winner'ın generated owner FK'si semantic owner'a resolve edilip doğrulanır; loser'ın staged random owner UUID'si rollback/discard edilir ve winner FK'siyle karşılaştırılmaz. Yalnız pre-existing provenance document/source UUID'leri exact identity olarak karşılaştırılır. Herhangi bir semantic fark conflict'tir ve winner response'a map edilmez.

Existing-owner candidate cardinality de kapalıdır: exact payload + exact normalized lineage + exact descriptor/proof için 0 aday varsa `allow_existing_canonical_owner=True` ise create yoluna gidilir; 1 aday exact reuse edilir; 1'den fazla aday `PERSISTENCE_INTEGRITY_ERROR` ile fail-closed olur. `allow_existing_canonical_owner=False` iken herhangi bir existing candidate conflict'tir. Query/lock order canonical UUID sırasıdır; “ilk satırı seç” yasaktır.

Bu tablo event store değildir ve event sourcing oluşturmaz.

## 23. Migration Tasarımı

**Migration sayısı: 2 additive, sıralı migration.** İlki mevcut head `b2e5f0c7d902`'nin doğrudan child'ı, ikincisi onun child'ı olur; bu tasarım revision ID uydurmaz ve daima tek Alembic head bırakır.

İki revision self-contained historical DDL'dir: import allowlist yalnız Python standard library, `alembic.op` ve `sqlalchemy`/dialect modülleridir; `app.*` model/enum/registry/codec import'u kesin yasaktır. Enum/CHECK değerleri, trigger name/event/function manifests, V3/legacy discriminator allowlist'leri, yedi engine-reachable typed error code→safe-message satırı ve Section 24.3'teki altı V3 generic `category→(exact message, normalized_exception_label allowlist)` satırı revision içinde immutable literal tuple/string olarak bulunur. Migration runtime `app.*` manifestini veya doküman referansını çözmez. AST/import golden testi ve generated DDL snapshot'ı gelecekteki runtime code değişikliğinin eski upgrade/downgrade davranışını değiştirememesini zorunlu kılar.

Migration 1 — period policy metadata:

1. `financial_periods` tablosuna nullable `accounting_basis_code`, `accounting_policy_version`, `annual_reporting_period_start_date`, `annual_reporting_period_end_date`, `ifrs18_early_adopted` alanlarını ekler.
2. Exact all-null XOR all-non-null CHECK; supported basis/policy pair CHECK; annual boundary order ve period containment CHECK ekler.
3. `financial_periods` INSERT/UPDATE/DELETE için affected OLD/NEW company UUID'lerini canonical sırada `companies FOR UPDATE NOWAIT` alan exact `trg_cf_00_namespace_financial_periods_<ins|upd|del>` BEFORE trigger/function manifestini oluşturur; lexical order, SQLSTATE `55P03`, rollback/no-internal-retry sözleşmesi migration testinde kilitlenir.
4. Existing row'a default/backfill uydurmaz. Section 28 internal `CashFlowPrerequisiteAdministrationPort.register_period_policy()` ile metadata girilene kadar Cash Flow minimum data gate'i kapanmaz; manual SQL supported production yolu değildir.
5. Downgrade, beş alandan herhangi biri non-null ise veri kaybını önlemek için fail-closed durur; hepsi null ise önce named namespace trigger/function'ı, sonra check/column'ları kaldırabilir.

Migration 2 — Cash Flow persistence/lineage:

1. Upgrade preflight bütün mevcut `orchestration_runs` satırlarının exact legacy allowlist `orchestration_schema_version='2.0.0'`, `orchestration_model_version='2.0.0'`, `execution_plan_version='2.0.0'`, `fingerprint_schema_version='1.0.0'` taşımasını zorunlu kılar. Tek bir pre-existing `3.x`, bilinmeyen/future discriminator veya manuel/sahipsiz `AnalysisType.CASH_FLOW` owner varsa backfill/yorum uydurmadan migration durur. Böylece trigger kurulurken doğrulanmamış no-Cash-Flow V3 row'lar dahi sonradan V3 protected-root/error semantiğine sessizce alınmaz. V3 durable row yalnız migration tamamlandıktan sonra V3 repository tarafından yazılabilir.
2. `companies(id, tenant_id)` composite unique hedefini exact `uq_companies_id_tenant_id` adıyla ekler; `Company.__table_args__` aynı named constraint'i taşır.
3. `cash_flow_cross_period_lineage` tablosu, period/proof digest kolonları, PK/FK/unique/check/explicit source index'leri ve parent/source validation trigger'larını oluşturur. Ayrıca owner→execution/protected-root/seal lookup'ları için ORM/DDL parity'li exact named `ix_orchestration_engine_executions_financial_analysis_result_id` B-tree index'ini `orchestration_engine_executions(financial_analysis_result_id)` üzerinde oluşturur; duplicate eşdeğer index yasaktır. Reused-execution FK için bu milestone ayrı sorgu deseni tanımlamadığından ek index uydurulmaz.
4. `financial_documents`, `financial_analysis_results`, `financial_analysis_result_sources` INSERT/UPDATE/DELETE, lineage INSERT ve non-null financial-owner FK taşıyan her orchestration execution INSERT için affected company UUID'lerini canonical `FOR UPDATE NOWAIT` alan exact `trg_cf_00_namespace_<table>_<ins|upd|del>` manifestini oluşturur. Source-binding trigger parent'a dokunmadan doğrudan NOT NULL `OLD.company_id`/`NEW.company_id` union'unu; execution trigger owner'a bakmadan immutable parent run'ın company UUID'sini kilitler. Parent/owner/source/FK/immutability/seal kontrolleri lexically sonraki `trg_cf_10_validate_*`/`trg_cf_20_guard_*` functions içinde çalışır. Bütün trigger'lar exact SQLSTATE `55P03`, immediate rollback, bounded terminal `lock_timeout` ve no-internal-retry contract'ını paylaşır.
5. Bütün Cash-Flow owners için BEFORE INSERT guard; `V3_TERMINAL_PROTECTED_ROOTS` ve Cash Flow lineage-source graph'ı için full owner/outbound-source/document immutable UPDATE/DELETE/append guard'ları; lineage post-execution append seal'i; deferred `trg_cf_90_owner_sealed_deferred`; Cash Flow parent exact-zero legacy-source kuralını ekler. No-CF V3 BS/IS/Ratio roots ve Ratio→Cash Flow outbound edge bu protection'a dahildir, legacy V2 root'lar mevcut davranışını korur. Catalog manifest exact lexical trigger order/functions/events'i doğrular.
6. `orchestration_engine_executions.engine_code` CHECK'ini `cash_flow` ile; execution owner-mapping CHECK'ini BS/IS/Cash Flow/Ratio financial owner kümesiyle genişletir. `orchestration_errors` ORM/DDL'sine nullable `cash_flow_error_code VARCHAR(64)`, PostgreSQL `safe_metadata_json JSONB` ve `error_retryable BOOLEAN` eklenir. Üçü exact all-null/all-nonnull'dır; non-null extension ⇒ `engine_code='cash_flow'`, fakat Cash Flow engine code ⇒ extension zorunlu değildir. Exact `trg_cf_10_validate_orchestration_errors_<ins|upd>` relational guard'ı her satırda parent run'ı yükleyip contract discriminator'ını sınıflandırır. Non-null extension branch'i yalnız exact V3 run'da geçerlidir ve `engine_execution_id` zorunlu, referenced execution `run_id=NEW.run_id`, execution/error `engine_code='cash_flow'`, execution status `failed`, V3 Cash Flow schema/model/fingerprint versions exact, error category `engine_contract_violation`, `original_exception_type IS NULL` şartlarını doğrular. Code yalnız engine-reachable yedi değer (`INVALID_CONTRACT`, `POLICY_VERSION_UNSUPPORTED`, `MAPPING_REGISTRY_VERSION_UNSUPPORTED`, `MAPPING_CONFLICT`, `DECIMAL_NON_FINITE_OR_SCALE_INVALID`, `SOURCE_CURRENCY_MISMATCH`, `SOURCE_EVIDENCE_CONFLICT`) olabilir; resolver/persistence-only dokuz code terminal execution error'una yazılamaz. V1 engine failures retryable olmadığından `error_retryable=false`, `safe_metadata_json='{}'::jsonb` ve `message` Section 13 exact code→safe-message manifestine eş olmalıdır. Exact V3 generic dependency/cancel/orchestration-level branch'inde üç extension exact null kalır ve trigger Section 24.3 V3 generic category→message/normalized-exception-label manifestini doğrular; safe metadata/retryable bu manifestten empty/false olarak V3 reader tarafından yeniden kurulur. Exact V2 run'ın all-null extension'lı error row'u bu V3 generic-message manifestine sokulmaz ve mevcut 5.0B validation/read davranışı aynen korunur; V2 row'a V3 code, metadata, retry veya message uydurulmaz. Bilinmeyen contract discriminator'lı row V3 olarak yorumlanmaz ve V3 repository tarafından fail-closed reddedilir. V3 repository insert/read strict JSON object + origin/code/message/retry parity'sini DB guard'a ek olarak yeniden doğrular; scalar/array/unknown key kabul etmez.
7. Existing satırlara backfill yapmaz.
8. Downgrade DB-executable ve future-safe legacy allowlist preflight kullanır: herhangi bir `orchestration_runs` row'unda `orchestration_schema_version IS DISTINCT FROM '2.0.0' OR orchestration_model_version IS DISTINCT FROM '2.0.0' OR execution_plan_version IS DISTINCT FROM '2.0.0' OR fingerprint_schema_version IS DISTINCT FROM '1.0.0'` ise fail-closed durur. Böylece V3 yanında bilinmeyen V4+ veya future fingerprint discriminator da geçemez. Ek savunma olarak `engine_code='cash_flow'` execution, non-null Cash Flow error extension, lineage row veya `analysis_type='cash_flow'` owner varlığı da downgrade'ı durdurur. Snapshot/binding gibi durable olmayan Python nesneleri migration predicate'i değildir. Yalnız bütün durable run'lar exact legacy V2/fingerprint ve diğer predicate'ler boşsa önce named namespace/immutability/validation trigger'ları, sonra `ix_orchestration_engine_executions_financial_analysis_result_id`, lineage table/error columns/CHECK widening/composite unique değişiklikleri dependency-safe sırayla geri alınabilir. Migration 1 period trigger'ı migration 2 downgrade'ında kaldırılmaz.

Kabul: head0 → migration1 → migration2 → migration1 → head0 → migration1 → migration2 tam cycle; her aşamada tek head. Period metadata populated iken migration1 downgrade, Cash Flow/error-extension/lineage populated iken migration2 downgrade reddedilir. Migration2 upgrade öncesi raw `3.x`, `4.x` veya unknown discriminator içeren run ayrı PostgreSQL vakalarında reddedilir. All-null/all-set, unsupported basis, annual containment, trigger order/catalog, OLD/NEW multi-company locking, SQLSTATE `55P03`, bounded lock timeout, owner-execution index catalog/ORM parity ve bütün lineage FK/check/trigger negatifleri gerçek PostgreSQL SQL'iyle çalışır.

## 24. 5.0A–5.0C Versioned Contract Evolution

Mevcut contract'lar yerinde ve anlamları değişmeden korunur. Cash-flow yalnız yeni major contract sürümünde kullanılabilir.

### 24.1 Sürüm matrisi

| Contract ekseni | Legacy/current | Cash-flow sürümü | Kural |
|---|---:|---:|---|
| Orchestration schema | 2.0.0 | 3.0.0 | v2 reader korunur |
| Orchestration model | 2.0.0 | 3.0.0 | v2 run backfill edilmez |
| Execution plan | 2.0.0 | 3.0.0 | graph shape ayrı doğrulanır |
| Fingerprint schema | 1.0.0 | 1.0.0 | canonical algoritma değişmez; version-aware branch eklenir |
| Application DTO schema | 1.0.0 | 2.0.0 | v1 replay/digest birebir korunur |
| Cash-flow schema/model | yok | 1.0.0 / 1.0.0 | kapalı codec |
| Mapping registry | yok | 1.0.0 | fingerprint girdisi |
| Reconciliation policy | yok | 1.0.0 | fingerprint girdisi |
| Report schema/model | 1.0.0 | 1.1.0 / 1.1.0 | yalnız cash-flow varsa yeni optional projection |
| Ratio formula registry | 1.1.0 | 1.1.0 | formüller değişmez |

Fingerprint canonicalization algoritması değişmediği için `FINGERPRINT_SCHEMA_VERSION` artırılmaz. Ancak v2 legacy projection'a yeni default alan veya `cash_flow_fingerprint=None` eklenmez. V1 application command digest'i de yeni DTO default'larıyla yeniden hesaplanmaz.

### 24.2 Exhaustive etki tablosu

| Bileşen | Değişiklik | Backward compatibility |
|---|---|---|
| `OrchestrationEngineCodeV3` | ayrı 11 üyeli enum; `CASH_FLOW="cash_flow"` | mevcut `EngineCode` 10 üyeli ve byte-for-byte değişmez |
| `ApplicationEngineCodeV2` | ayrı v2 enum; `CASH_FLOW` içerir | mevcut `ApplicationEngineCode` değişmez ve Cash Flow isteyemez |
| `EngineRawInputsV3` | ayrı type; `cash_flow_pre_resolved_context` taşır | mevcut `EngineRawInputs` shape/digest değişmez |
| Request/result | ayrı `OrchestrationRunRequestV3/ResultV3`, `run_orchestration_v3()` | mevcut `OrchestrationRunRequest/Result` ve `run_orchestration()` v2 olarak değişmez |
| DAG registry | 11 node/28 edge v3 graph | v2 10/24 manifest okunabilir |
| Dispatch | `CASH_FLOW → analyze_cash_flow` | v2 dispatch manifest korunur |
| Fingerprint | cash-flow branch ve koşullu downstream digest | legacy golden vektörler değişmez |
| Result accessor | yalnız V3 result için `get_cash_flow_result_v3()` | v2 accessor kümesi değişmez |
| Resume snapshot | strict CashFlow codec/lineage branch | eski run'a fake snapshot eklenmez |
| Reuse | yalnız V3→V3; current engine version + source graph + policy equality | V2 sonuç V3'e reuse edilmez; legacy V2 path kendi içinde değişmez |
| Ownership registry | 4 financial + 7 artifact owner | BS/IS/Ratio sahipliği değişmez |
| Owner ordering | BS → IS → Cash Flow → Ratio | same-transaction lineage mümkün |
| DTO projection | ayrı application-v2 cash-flow projection | v1 DTO types/digest değişmez; engine dataclass doğrudan açılmaz |
| Read/history | engine enum ve financial owner reference | existing DTO fields korunur |
| Persistence CHECK | engine code + owner mapping genişletilir | migration additive/widening |

### 24.3 V3 DAG

```text
FS_BALANCE_SHEET ─┐
                  ├─(all_of)→ CASH_FLOW ─(optional)→ RATIO
FS_INCOME_STATEMENT┘                         │
                                             ├→ BENCHMARK → HEALTH → CREDIT → RECOMMENDATION
                                             └───────────────────────────────┐
CASH_FLOW ─────────────────────────────(optional)────────────────────────→ EXECUTIVE_REPORT
```

Exact dependency registry:

- `CASH_FLOW.all_of=(FS_BALANCE_SHEET, FS_INCOME_STATEMENT)`;
- ayrı V3 `EngineInvocationSpecV3.dependency_failure_behavior` alanı vardır; default `SKIP`, yalnız CASH_FLOW için `INVOKE_DIAGNOSTIC_ONLY` olur; mevcut v2 `EngineInvocationSpec` değişmez;
- `RATIO.any_of=(FS_BALANCE_SHEET, FS_INCOME_STATEMENT)` değişmez;
- `RATIO.optional=(CASH_FLOW,)`;
- `EXECUTIVE_REPORT` mevcut `all_of` kümesini korur ve `optional=(CASH_FLOW,)` alır;
- `DASHBOARD.optional=(BENCHMARK,)` değişmez.

| Ölçü | V2 | V3 |
|---|---:|---:|
| Node | 10 | 11 |
| `all_of` edge | 21 | 23 |
| `any_of` edge | 2 | 2 |
| `optional` edge | 1 | 3 |
| Toplam edge | 24 | 28 |

Deterministik alphabetical-ready plan:

```text
fs_balance_sheet
fs_income_statement
cash_flow
ratio
benchmark
health_score
credit_score
recommendation
dashboard
executive_report
render_contract
```

Optional dependency bir engine'i kendiliğinden requested yapmaz. Yalnız Cash Flow requested ise closure `FS_BALANCE_SHEET + FS_INCOME_STATEMENT + CASH_FLOW` olur. Report içinde cash-flow isteniyorsa caller hem `CASH_FLOW` hem `EXECUTIVE_REPORT` ister.

V2 ve V3 selection ambiguous değildir: mevcut `run_orchestration(request: OrchestrationRunRequest, ...)` yalnız v2'yi kabul eder; yeni `run_orchestration_v3(request: OrchestrationRunRequestV3, ...)` yalnız `contract_version=3.0.0` kabul eder. `ORCHESTRATION_V2_ENGINE_CODE_MANIFEST` mevcut 10 değeri, `ORCHESTRATION_V3_ENGINE_CODE_MANIFEST` aynı sıradaki 10 değer + `cash_flow` değerini taşır. Stored v2 run read-only v2 decoder'dan geçer; auto-upcast/backfill yoktur. Type/discriminator uyuşmazlığı fail-closed'dur.

V3 enum manifesti exact şu sıradadır: `fs_balance_sheet, fs_income_statement, cash_flow, ratio, benchmark, health_score, credit_score, recommendation, executive_report, dashboard, render_contract`. Application-v2 engine manifesti aynı 11 değeri kullanır; mevcut v2 orchestration/v1 application manifestleri kendi eski sıralarını korur.

```python
class OrchestrationEngineCodeV3(str, Enum):
    FS_BALANCE_SHEET = "fs_balance_sheet"
    FS_INCOME_STATEMENT = "fs_income_statement"
    CASH_FLOW = "cash_flow"
    RATIO = "ratio"
    BENCHMARK = "benchmark"
    HEALTH_SCORE = "health_score"
    CREDIT_SCORE = "credit_score"
    RECOMMENDATION = "recommendation"
    EXECUTIVE_REPORT = "executive_report"
    DASHBOARD = "dashboard"
    RENDER_CONTRACT = "render_contract"

class EngineExecutionStatusV3(str, Enum):
    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"
    REUSED = "reused"

class RunStatusV3(str, Enum):
    FULLY_COMPLETED = "fully_completed"
    COMPLETED_WITH_DEGRADATIONS = "completed_with_degradations"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class OrchestrationErrorCategoryV3(str, Enum):
    ENGINE_CONTRACT_VIOLATION = "engine_contract_violation"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    VERSION_INCOMPATIBLE_ON_REUSE = "version_incompatible_on_reuse"
    FINGERPRINT_MISMATCH_ON_REUSE = "fingerprint_mismatch_on_reuse"
    INVALID_RUN_REQUEST = "invalid_run_request"
    CANCELLED = "cancelled"

class FinancialAnalysisStatusV3(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class FinancialSourceModeV3(str, Enum):
    DIRECT_DOCUMENT = "direct_document"
    TRIAL_BALANCE_DERIVED = "trial_balance_derived"
    MULTI_SOURCE_DERIVED = "multi_source_derived"

OrchestrationJsonScalarV3 = None | bool | str | int | Decimal | UUID | date
OrchestrationJsonValueV3 = (
    OrchestrationJsonScalarV3
    | tuple["OrchestrationJsonValueV3", ...]
    | "OrchestrationJsonObjectV3"
)

@dataclass(frozen=True)
class OrchestrationJsonObjectV3:
    items: tuple[tuple[str, OrchestrationJsonValueV3], ...]

@dataclass(frozen=True)
class StructuredErrorV3:
    category: OrchestrationErrorCategoryV3
    engine_code: OrchestrationEngineCodeV3 | None
    message_tr: str
    cash_flow_error_code: CashFlowErrorCode | None
    safe_metadata: OrchestrationJsonObjectV3
    retryable: bool
    original_exception_type: str | None = None

@dataclass(frozen=True)
class BalanceSheetAnalysisOutcomeV3:
    status: FinancialAnalysisStatusV3
    source_mode: FinancialSourceModeV3 | None
    result_json: OrchestrationJsonObjectV3 | None
    error_message: str | None
    trial_balance_usage: str | None

@dataclass(frozen=True)
class IncomeStatementAnalysisOutcomeV3:
    status: FinancialAnalysisStatusV3
    source_mode: FinancialSourceModeV3 | None
    result_json: OrchestrationJsonObjectV3 | None
    error_message: str | None
    trial_balance_usage: str | None

V3EngineResultValue = (
    BalanceSheetAnalysisOutcomeV3
    | IncomeStatementAnalysisOutcomeV3
    | CashFlowResult
    | OrchestrationJsonObjectV3
    | HealthScoreResult
    | CreditScoreResult
    | RecommendationResult
    | ExecutiveReportResult
    | DashboardSnapshot
    | RenderContractPreview
)

@dataclass(frozen=True)
class EngineResultEnvelopeV3:
    engine_code: OrchestrationEngineCodeV3
    result_kind: str
    result: V3EngineResultValue

@dataclass(frozen=True)
class PerEngineExecutionRecordV3:
    engine_code: OrchestrationEngineCodeV3
    status: EngineExecutionStatusV3
    result: EngineResultEnvelopeV3 | None
    inner_status_value: str | None
    error: StructuredErrorV3 | None
    dependency_engine_codes: tuple[OrchestrationEngineCodeV3, ...]
    engine_schema_version_used: str | None
    engine_model_version_used: str | None
    input_fingerprint: str
    fingerprint_schema_version: str

@dataclass(frozen=True)
class ExecutionProvenanceV3:
    execution_plan_version: str
    engine_call_sequence: tuple[OrchestrationEngineCodeV3, ...]
    reused_engine_codes: tuple[OrchestrationEngineCodeV3, ...]
    skipped_engine_codes: tuple[OrchestrationEngineCodeV3, ...]

@dataclass(frozen=True)
class PreviousEngineSnapshotV3:
    engine_code: OrchestrationEngineCodeV3
    execution_status: EngineExecutionStatusV3
    engine_schema_version_used: str | None
    engine_model_version_used: str | None
    input_fingerprint: str
    fingerprint_schema_version: str
    result: EngineResultEnvelopeV3 | None = None

@dataclass(frozen=True)
class PreviousExecutionSnapshotV3:
    previous_run_id: str
    request_fingerprint: str
    orchestration_schema_version: str
    orchestration_model_version: str
    execution_plan_version: str
    engine_snapshots: tuple[PreviousEngineSnapshotV3, ...]

@dataclass(frozen=True)
class OrchestrationRunOptionsV3:
    industry_code: str | None = None
    company_size_bucket: str | None = None
    tenant_id: str | None = None
    report_type: str | None = None
    dashboard_type: str | None = None
    company_metadata: OrchestrationJsonObjectV3 | None = None
    reporting_period_label_tr: str | None = None
    optional_sections: tuple[str, ...] | None = None
    currency_display_policy: str | None = None
    locale: str = "tr-TR"
    render_contract: OrchestrationJsonObjectV3 | None = None

@dataclass(frozen=True)
class BalanceSheetFactsV3:
    current_assets: Decimal | None
    non_current_assets: Decimal | None
    total_assets: Decimal | None
    short_term_liabilities: Decimal | None
    long_term_liabilities: Decimal | None
    equity: Decimal | None
    total_liabilities_and_equity: Decimal | None
    cash_and_equivalents: Decimal | None
    inventory: Decimal | None
    trade_receivables: Decimal | None
    trade_payables: Decimal | None
    account_details: OrchestrationJsonObjectV3 | None

@dataclass(frozen=True)
class IncomeStatementFactsV3:
    gross_sales: Decimal | None
    sales_deductions: Decimal | None
    net_sales: Decimal | None
    cost_of_sales: Decimal | None
    gross_profit: Decimal | None
    operating_expenses: Decimal | None
    other_operating_income: Decimal | None
    other_operating_expenses: Decimal | None
    operating_profit: Decimal | None
    depreciation_and_amortization: Decimal | None
    ebit: Decimal | None
    ebitda: Decimal | None
    financing_expenses: Decimal | None
    extraordinary_income: Decimal | None
    extraordinary_expenses: Decimal | None
    profit_before_tax: Decimal | None
    net_profit: Decimal | None
    account_details: OrchestrationJsonObjectV3 | None

@dataclass(frozen=True)
class EngineRawInputsV3:
    balance_sheet_content: bytes | None
    balance_sheet_filename: str | None
    income_statement_content: bytes | None
    income_statement_filename: str | None
    trial_balance_result: OrchestrationJsonObjectV3 | None
    prior_period_balance_sheet_facts: BalanceSheetFactsV3 | None
    prior_period_income_statement_facts: IncomeStatementFactsV3 | None
    prior_period_balance_sheet_result: OrchestrationJsonObjectV3 | None
    prior_period_income_statement_result: OrchestrationJsonObjectV3 | None
    period_start_date: date | None
    period_end_date: date | None
    period_months_covered: int | None
    cash_flow_pre_resolved_context: CashFlowPreResolvedContext | None

@dataclass(frozen=True)
class OrchestrationRunRequestV3:
    run_id: str
    correlation_id: str | None
    generated_at: str | None
    requested_outputs: tuple[OrchestrationEngineCodeV3, ...]
    engine_inputs: EngineRawInputsV3
    run_options: OrchestrationRunOptionsV3
    previous_execution_snapshot: PreviousExecutionSnapshotV3 | None
    contract_version: str = "3.0.0"

@dataclass(frozen=True)
class OrchestrationRunResultV3:
    run_id: str
    correlation_id: str | None
    generated_at: str | None
    status: RunStatusV3
    engine_records: tuple[PerEngineExecutionRecordV3, ...]
    warnings: tuple[OrchestrationJsonObjectV3, ...]
    structured_errors: tuple[StructuredErrorV3, ...]
    execution_provenance: ExecutionProvenanceV3
    input_version_inventory: OrchestrationJsonObjectV3
    orchestration_schema_version: str
    orchestration_model_version: str
    execution_plan_version: str
    request_fingerprint: str

@dataclass(frozen=True)
class PerEngineTelemetryV3:
    engine_code: OrchestrationEngineCodeV3
    started_at_offset_ms: float | None
    duration_ms: float | None

@dataclass(frozen=True)
class ExecutionTelemetryV3:
    per_engine: tuple[PerEngineTelemetryV3, ...]
    total_duration_ms: float | None

class AnalysisOrchestratorPortV3(Protocol):
    def run(
        self,
        request: OrchestrationRunRequestV3,
        *,
        cancellation_probe: Callable[[], bool] | None = None,
    ) -> tuple[OrchestrationRunResultV3, ExecutionTelemetryV3 | None]: ...
```

`OrchestrationJsonObjectV3` constructor'ı recursive closed algebra'yı zorunlu kılar: key yalnız non-empty NFC `str`, tuple key'leri Unicode code-point order'ında strictly increasing ve unique; nested sequence yalnız tuple'dır. Decimal finite/canonical magnitude-scale guard'ını, UUID lowercase canonical text round-trip'ini ve `date` exact ISO round-trip'ini geçer. `bool`, `int`'ten önce ayrıştırılır; float/NaN/Infinity, bytes, list, dict, set, datetime, Enum, unknown dataclass, mutable node ve repr/string fallback reddedilir. Enum boundary adapter tarafından kapalı manifestte `.value` string'e; datetime ilgili typed field'a veya açık UTC string contract'ına çevrilmeden object'e giremez. Strict canonical node encoder Decimal/UUID/date için Section 24.4 tagged representation'ını, tuple/object için aynı tagged shape'i kullanır. Cash-flow builder bunu field-by-field `CashFlowJsonObject`'a dönüştürür; application core type'i import edilmez.

`StructuredErrorV3` exact error-preservation boundary'sidir. `cash_flow_error_code` yalnız gerçekten `CashFlowEngineFailure` origin'li typed Cash Flow execution failure'ında zorunlu, `safe_metadata` exact empty object ve `retryable` Section 20 manifestinden türetilmiş olmalıdır; caller bunları değiştiremez. Cash Flow node'u engine çağrılmadan `DEPENDENCY_UNAVAILABLE`, cancellation veya orchestration-level contract error ile sonlanmışsa ve Cash Flow dışı error'larda code null'dır; broad category'nin kendi frozen generic safe message'i kullanılır. Typed Cash Flow `message_tr` Section 13 literal safe-message manifestinden gelir; raw exception/SQL/DSN/path/claim/PII içermez. `original_exception_type` typed expected failure'da null, unexpected technical exception'ta yalnız allowlisted generic class label olabilir. Persist/read adapter exact origin + code + safe metadata + retryable parity'sini doğrular.

Generic V3 error reconstruction manifesti de kapalıdır; böylece nullable Cash Flow extension'ı olmayan durable row terminal bytes'a geri dönebilir:

| Category | Exact `message_tr` | `safe_metadata` | `retryable` | `original_exception_type` |
|---|---|---|---:|---|
| `ENGINE_CONTRACT_VIOLATION` | `Motor sözleşmesi doğrulanamadı.` | exact empty object | false | null veya exact normalized `unexpected_engine_failure` |
| `DEPENDENCY_UNAVAILABLE` | `Gerekli motor bağımlılığı kullanılamıyor.` | exact empty object | false | null |
| `VERSION_INCOMPATIBLE_ON_REUSE` | `Önceki çalıştırmanın motor sürümü uyumlu değil.` | exact empty object | false | null |
| `FINGERPRINT_MISMATCH_ON_REUSE` | `Önceki çalıştırmanın girdi parmak izi eşleşmiyor.` | exact empty object | false | null |
| `INVALID_RUN_REQUEST` | `Analiz isteği geçersiz.` | exact empty object | false | null |
| `CANCELLED` | `Analiz iptal edildi.` | exact empty object | false | null |

Generic branch'te `cash_flow_error_code=None` ve durable üç Cash Flow extension kolonu all-null'dır; repository category + exact message + normalized exception label'dan empty metadata/false retryable değerini deterministik yeniden kurar. Başka metadata, retry flag, message veya raw Python exception class adı contract error'dur. Typed Cash Flow branch'i aynı category'yi kullanabilse de non-null code ile Section 13 manifestine gider ve generic message'e düşmez.

V3 tipleri yukarıdaki exact field manifestleridir; V2 import/alias edilmez ve cross-version decoder type confusion reddedilir. `BalanceSheetFactsV3`/`IncomeStatementFactsV3`, mevcut mutable 5.0A facts class'larının alias'ı değildir; adapter field-by-field frozen copy kurar, unknown legacy nested shape'i reddeder ve 5.0A class'ını değiştirmez. Run-options string alanları serbest string değildir: `report_type`, `dashboard_type`, `optional_sections`, locale ve render/company object shape'leri ayrı `ORCHESTRATION_V3_RUN_OPTION_MANIFEST` tarafından mevcut engine registry literal'larına exact doğrulanır; unknown literal/field fail-closed'dur.

`V3_RESULT_KIND_TYPE_MANIFEST` exact'tir: BS→`("BalanceSheetAnalysisOutcomeV3", BalanceSheetAnalysisOutcomeV3)`, IS→`("IncomeStatementAnalysisOutcomeV3", IncomeStatementAnalysisOutcomeV3)`, Cash Flow→`("CashFlowResult", CashFlowResult)`, Ratio→`("dict", OrchestrationJsonObjectV3)`, Benchmark→`("dict", OrchestrationJsonObjectV3)`, Health→`("HealthScoreResult", HealthScoreResult)`, Credit→`("CreditScoreResult", CreditScoreResult)`, Recommendation→`("RecommendationResult", RecommendationResult)`, Report→`("ExecutiveReportResult", ExecutiveReportResult)`, Dashboard→`("DashboardSnapshot", DashboardSnapshot)`, Render→`("RenderContractPreview", RenderContractPreview)`. V3 dispatch adapter legacy mutable BS/IS outcome'larını status/source-mode enum-value check + result_json recursive frozen copy + exact five-field construction ile V3 outcome'a; mutable dict sonuçlarını envelope kurulmadan frozen `OrchestrationJsonObjectV3`'e dönüştürür. Legacy object hiçbir V3 envelope'a doğrudan konamaz. Diğer sonuçlarda runtime type ve engine/kind pair exact doğrulanır.

Cash Flow engine port'u internal olarak `CashFlowEngineOutcome` döndürür fakat envelope bunu taşımaz. `outcome.success=True` ise execution `COMPLETED` veya domain durumuna göre `DEGRADED`, `EngineResultEnvelopeV3.result_kind="CashFlowResult"`, `result=outcome.value` olur. `outcome.success=False` ise execution `FAILED`, `result=None`, `error=StructuredErrorV3` olur; failure outcome yalnız güvenli error mapping için tüketilir ve owner/snapshot payload'ı değildir. `get_cash_flow_result_v3()` exact kind/type kontrolüyle `CashFlowResult | None` döndürür. Success execution'ın `canonical_result_digest` değeri strict `cf.result.v1` payload bytes'ını; ayrı `owner_content_digest` değeri Section 24.4'teki frozen five-field financial-owner semantic wrapper'ını bağlar. Failure record'da iki digest/owner da yoktur.

`EngineRawInputsV3`, v2 alanlarının ayrı v3 kopyasına ek olarak `cash_flow_pre_resolved_context: CashFlowPreResolvedContext | None` taşır. 5.0C-v2 mapper, trusted resolvers ile prior/TB/evidence bağlamını run öncesi üretir. V3 `_invoke_engine(CASH_FLOW)` yalnız dependency records içindeki current FS `EngineResultEnvelopeV3.result` değerlerini alır ve saf `build_indirect_cash_flow_input(pre_resolved, current_bs, current_is)` ile final input'u kurar; DB/persistence import etmez.

Dependency gate consumer-specific'tir. Cash Flow için FS dependency, FS callable'ının denenmiş ve bir outcome envelope üretmiş olmasıyla scheduling'i sağlar; domain outcome içindeki `result_json=None`, builder'a `None` snapshot olarak gider ve engine yalnız `INSUFFICIENT_DATA` üretir. FS technical exception/`FAILED`/`SKIPPED` veya envelope yokluğu Cash Flow'u `DEPENDENCY_UNAVAILABLE` ile çalıştırmaz ve owner üretmez. Ratio'nun mevcut “en az bir usable FS `result_json`” gate'i aynen korunur. Diagnostic yolda parasal line/allocation üretmek invariant breach'tir. Böylece eksik business data persisted outcome olurken teknik failure business result'a çevrilmez; edge sayıları değişmez.

### 24.4 Strict Cash-Flow financial-owner codec

`CASH_FLOW_FINANCIAL_RESULT_CODEC_VERSION="1.0.0"` 5.0B artifact serializer değildir; `FinancialAnalysisResult` payload codec'idir ve cash-flow owner reference'ta `artifact_serializer_schema_version=None` kalır. Canonical node manifesti kapalıdır:

- `None/bool/str/int` doğrudan JSON scalar;
- `Decimal` → `{"$type":"decimal","value":<normalized finite exact text>}`; negative zero `0` olur;
- `UUID` → `{"$type":"uuid","value":<lowercase canonical UUID>}`;
- `date` → `{"$type":"date","value":"YYYY-MM-DD"}`;
- enum → `{"$type":"enum","name":<stable logical type tag>,"value":<enum.value>}`;
- tuple → `{"$type":"tuple","items":[...]}`; list kabul edilmez;
- `CashFlowJsonObject` → `{"$type":"object","items":[[key,node],...]}`; NFC string key'ler unique ve code-point sorted;
- frozen dataclass → `{"$type":"record","name":<stable logical type tag>,"fields":[[declared_field_name,node],...]}`; declaration sırası exact'tir.

`CASH_FLOW_LOGICAL_TYPE_TAG_REGISTRY_V1`, her enum/record class'ını module-qualified Python adına değil release boyunca sabit kalan literal kimliğe bağlayan kapalı manifesttir (`cf.result.v1`, `cf.line_item.v1`, `cf.status.v1` gibi). Rename/import path değişikliği digest'i değiştiremez; unknown, duplicate veya manifest dışı tag fail-closed'dur. Canonical bytes UTF-8 ve `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)` ile üretilir; duplicate-key rejection decoder'da zorunludur. JSONB load, driver'ın verdiği object'i önce strict node decoder'dan geçirir, sonra aynı canonical encoder ile yeniden encode/rehash eder; PostgreSQL'in object-key sırası authoritative sayılmaz. Float/NaN/Infinity, unknown tag/type/enum, missing/extra/reordered record field, mutable input map/list ve invalid UUID/Decimal/date kesin reddedilir. `canonical_digest=sha256(canonical_bytes).hexdigest()` lowercase olur ve decode/load sırasında yeniden hesaplanıp constant-time karşılaştırılır. Strict decoder exact `CashFlowResult` kurucusunu çalıştırır; field/identity/evidence/allocation invariant'ları geçmeden owner okunmaz. UUID/Decimal/Enum/date/tuple/object/record, logical-tag registry, JSONB re-encode ve tam `CashFlowResult` round-trip + golden digest testleri zorunludur.

Exact logical-tag manifest:

```text
records: cf.json_object.v1, cf.issue.v1, cf.period_descriptor.v1,
         cf.source_snapshot.v1, cf.account_evidence.v1,
         cf.noncash_bridge_component.v1, cf.pre_resolved_context.v1,
         cf.indirect_input.v1, cf.computation_draft.v1,
         cf.evidence_bundle.v1, cf.mapping_registry.v1,
         cf.account_family.v1, cf.account_disposition_proof.v1,
         cf.engine_fingerprint.v1, cf.source_candidate_set.v1,
         cf.document_storage_key.v1, cf.document_source_proof.v1,
         cf.provenance_closure.v1, cf.source_root_semantics.v1,
         cf.account_mapping.v1,
         cf.role_behavior.v1, cf.cash_equivalent_policy.v1,
         cf.presentation_policy.v1,
         cf.evidence_reference.v1,
         cf.activity_allocation.v1, cf.line_item.v1,
         cf.cash_availability_observation.v1,
         cf.cash_availability_disclosure.v1,
         cf.endpoint_reconciliation.v1, cf.completeness.v1,
         cf.source_lineage_reference.v1, cf.result.v1
enums:   cf.method.v1, cf.activity.v1, cf.cash_availability_classification.v1,
         cf.availability_period_position.v1, cf.aggregation_role.v1,
         cf.evidence_kind.v1, cf.applicability.v1, cf.status.v1,
         cf.reconciliation_status.v1, cf.endpoint_reconciliation_status.v1,
         cf.line_code.v1, cf.source_role.v1, cf.source_mode.v1,
         cf.mapping_match_kind.v1, cf.account_role.v1,
         cf.account_disposition.v1, cf.account_family_code.v1,
         cf.family_balance_basis.v1, cf.family_member_kind.v1,
         cf.normal_balance.v1,
         cf.working_capital_kind.v1, cf.cash_eligibility_rule.v1,
         cf.statement_basis.v1, cf.accounting_basis_code.v1,
         cf.balance_semantics.v1, cf.zero_omission_policy.v1,
         cf.derivation_code.v1, cf.noncash_bridge_domain.v1,
         cf.noncash_bridge_kind.v1, cf.warning_code.v1, cf.error_code.v1,
         cf.presentation_profile.v1, cf.presentation_rule.v1,
         cf.role_selection_rule.v1, cf.period_type.v1, cf.period_status.v1,
         fin.analysis_type.v1, fin.analysis_status.v1, orch.engine_code.v3
```

Registry key'i exact Python class object'i, value'su yukarıdaki literal tag'dir; başka record/enum encode edilmez. Decimal text algoritması context-independent'dır: finite ve scale/magnitude guard sonrası negative zero → `"0"`; aksi halde `format(value, "f")`, fractional trailing zero'ları ve sonda kalan noktayı kaldırır, leading plus/exponent üretmez, integer zero'yu `"0"` yapar. Decode edilen text aynı algoritmayla yeniden encode edilmeden kabul edilmez.

Yeni auxiliary SHA-256 domain'leri exact ASCII prefix + NUL + aşağıdaki canonical root node bytes'ını kullanır. “Canonical digest” sözü tek başına field seçimi yetkisi vermez:

| Domain/prefix | Exact root projection |
|---|---|
| `cash-flow/evidence-bundle/v1` | `cf.evidence_bundle.v1` ordered record: `account_evidence` tuple, `noncash_bridge_components` tuple |
| `cash-flow/pre-resolved-context/v1` | declaration-order `cf.pre_resolved_context.v1` record'ının tamamı; içindeki `pre_resolved_evidence_bundle_digest` dahil |
| `cash-flow/source-provenance/v1` | Section 8'deki exact `cf.provenance_closure.v1` root-semantics/root-edge/node/edge/document record'u |
| `cash-flow/account-family/v1` | Section 10 exact family code/domain/basis/registry-version/ordered-member record'u |
| `cash-flow/account-disposition/v1` | Section 10 exact source/account/mapping/disposition/proof record'u |
| `cash-flow/period-descriptor/v1` | exact `cf.period_descriptor.v1` record |
| `cash-flow/source-snapshot/v1` | exact declaration-order `cf.source_snapshot.v1` record |
| `cash-flow/source-candidate-set/v1` | role declaration order'ında exact eligible-candidate tuple'ları |
| `cash-flow/comparability-proof/v1` | Section 9'daki named ordered proof object |
| `cash-flow/mapping-registry/v1` | ordered record: version, mapping rows, behavior rows, family-definition rows |
| `cash-flow/policy-bundle/v1` | ordered record: `policy_version`, accounting basis/version, cash-equivalent policy row, presentation policy row, reconciliation policy version, mapping registry version |
| `cash-flow/component-reference/v1` | aşağıdaki self-field-excluded bridge projection |
| `cash-flow/computation-draft/v1` | declaration-order `cf.computation_draft.v1` record'ının tamamı |
| `cash-flow/document-storage-key/v1` | `(document_id, content_sha256, byte_size)` exact record |
| `cash-flow/document-source-proof/v1` | Section 28 exact scope/type/status/MIME/content/storage-proof record'u |

`cf.evidence_bundle.v1` bu tabloda auxiliary-only stable record tag'idir. `CashFlowAccountEvidence` declaration-order bütün alanlarıyla encode edilir ve tuple `(source_role declaration index, locator_tag, locator_value, account_code, canonical_account_role.value-or-empty)` key'iyle sıralanır. `CashFlowNonCashBridgeComponent` declaration-order bütün alanlarıyla encode edilir ve mevcut bridge key'iyle sıralanır. Her iki tuple'da duplicate sort key fail-closed'dur. `component_reference_digest` hesaplanırken self-reference yaratmamak için exact projection yalnız şu declaration-order alanları içerir: `economic_event_reference_digest`, `account_family_reference_digest`, `account_family_code`, `family_balance_basis`, `domain`, `bridge_kind`, source locator XOR, `source_canonical_digest`, `source_provenance_digest`, `statement_basis`, coverage dates, `applicability`, `evidence_kind`, source/functional monetary fields, normalized `signed_residual_adjustment`, `translation_provenance_digest`, `paired_transfer_reference_digest`, sorted supporting-evidence digests. Hesaplanan digest component field'ına yazıldıktan sonra full component evidence-bundle'a girer.

`CashFlowComputationDraft` canonical bytes'ı exact declaration-order `cf.computation_draft.v1` record'udur; nested line/evidence/lineage/warning tuple'ları aşağıdaki canonical sort manifestini kullanır. `computation_draft_digest = sha256(b"cash-flow/computation-draft/v1\0" + canonical_bytes(draft)).hexdigest()` olur. Draft'ta digest alanı bulunmaz; self-reference yoktur. Aynı strict input ve policy bundle aynı draft bytes/digest'i üretir; unknown/reordered/mutable nested value veya duplicate sort key fail-closed'dur.

Mapping-registry projection'ı exact `cf.mapping_registry.v1` ordered record'udur: `version`, ardından mapping rows, behavior rows ve family-definition rows. Her mapping row `CashFlowAccountMapping` declaration-order alanlarının **tamamını** (`mapping_id`, `match_kind`, `account_code_or_prefix`, `explicit_account_role`, `resolved_account_role`, `code_normal_balance`, `account_family_code`, `family_member_kind`, `model_version_introduced`) taşır ve `(match_kind precedence, account_code_or_prefix-or-empty, explicit_account_role.value-or-empty, resolved_account_role.value, mapping_id)` ile sıralanır. Behavior rows `CashFlowAccountRole` declaration order'ındadır ve her row kendi `CashFlowRoleBehavior` declaration-order alanlarının tamamını taşır. Family-definition rows `CashFlowAccountFamilyCode` declaration order'ında Section 10 exact domain/basis/member tuple'larıyla encode edilir. Readable table text digest'e girmez; tablodaki normal ve family üyeliği compiler'ın canonical alanlarına dönüştüğü için canonical row üzerinden bağlanır. Policy-bundle row'ları Section 8/11/12/19'daki literal manifest row'larından alınır; caller-built map kabul edilmez. Missing/extra/reordered projection field veya computed-version/digest mismatch fail-closed'dur.

Financial owner `canonical_result_digest`, mevcut `FinancialAnalysisResult` contract'ıyla uyum için prefix eklemeden root `cf.result.v1` tagged canonical JSON bytes'ının SHA-256'sıdır. Cash Flow `owner_content_digest` bunun alias'ı değildir: mevcut 5.0B `canonical_json_bytes` semantiğiyle exact named object `{"status": AnalysisStatus.COMPLETED, "source_mode": SourceMode.MULTI_SOURCE_DERIVED, "result_json": <strict cf.result.v1 JSON node>, "error_message": None, "trial_balance_usage": None}` encode edilir ve çıkan bytes'ın SHA-256'sı alınır. Object key sırası 5.0B canonical encoder tarafından lexical sort edilir; value'ların yukarıdaki exact type/value parity'si create/read/resume/reuse sırasında doğrulanır. BS/IS aynı dondurulmuş five-field projection'ı kendi gerçek owner değerleriyle, Ratio kendi exact owner result object'iyle kullanır. Artifact engines mevcut 5.0B artifact codec/content digest'ini kullanır. Result kind veya engine-code branch mismatch fail-closed'dur; `canonical_result_digest`, `owner_content_digest` ve artifact digest birbirinin yerine geçmez.

Canonical tuple sort manifesti: line items declaration-order line manifestinde; her line-item `warning_codes` `CashFlowWarningCode` declaration order'ında unique; allocations `CashFlowActivity` declaration order'ında; evidence `(source_role_order, locator_tag, locator_value, source_digest, source_provenance_digest, derivation_code, account_codes_tuple, mapping_ids_tuple)`; account evidence yukarıdaki exact key ile; account/mapping/missing-input/supporting-evidence string/digest tuple'ları NFC code-point order'ında; warning/error `(code.value, canonical_safe_metadata_bytes)`; source lineage `source_role` declaration order'ında ve provenance digest'iyle; disclosures `component_reference_digest`; observations `(OPENING, CLOSING)`; endpoint reconciliation `(OPENING, CLOSING)`; bridge components `(domain.value, account_family_reference_digest, bridge_kind.value, component_reference_digest)`; source snapshots `source_role` declaration order'ındadır. Duplicate sort key veya duplicate warning/supporting digest fail-closed'dur; insertion/DB row order hiçbir digest'e giremez.

### 24.5 Fingerprint projection

`compute_request_fingerprint_v2()` mevcut `_compute_request_fingerprint()` byte projection'ının isimlendirilmiş dondurulmuş karşılığıdır; legacy golden byte/digest değişmez. V3 fingerprint codec'in kapalı logical-tag manifesti `orch.request_fingerprint.v3`, `orch.engine_inputs_fingerprint.v3`, `orch.run_options.v3`, `orch.bs_facts.v3`, `orch.is_facts.v3` ve `orch.json_object.v3` record tag'lerinden oluşur; unknown dataclass/repr fallback yasaktır. `compute_request_fingerprint_v3()` exact formülü şudur:

```text
sha256(
  b"orchestration/request-fingerprint/v3\0" +
  canonical_bytes(orch.request_fingerprint.v3(
    contract_version,
    requested_outputs,
    engine_inputs_v3_digest,
    run_options_v3_digest
  ))
).hexdigest()
```

Field sırası yukarıdaki gibidir. `requested_outputs`, `OrchestrationEngineCodeV3` declaration order'ında unique tuple'dır; caller order, duplicate, missing closure veya unknown engine hash'ten önce reddedilir. `run_id`, `correlation_id`, `generated_at`, previous snapshot ve raw payload bu idempotency fingerprint'ine girmez; scope/subject ownership ayrı durable claim ile korunur.

`engine_inputs_v3_digest = sha256(b"orchestration/engine-inputs/v3\0" + canonical_bytes(orch.engine_inputs_fingerprint.v3(...))).hexdigest()` olup root declaration-order exact şu alanlardır: `balance_sheet_content_sha256`, `balance_sheet_filename`, `income_statement_content_sha256`, `income_statement_filename`, `trial_balance_result_digest`, `prior_period_balance_sheet_facts_digest`, `prior_period_income_statement_facts_digest`, `prior_period_balance_sheet_result_digest`, `prior_period_income_statement_result_digest`, `period_start_date`, `period_end_date`, `period_months_covered`, `cash_flow_pre_resolved_context_digest`. Raw content digest'i doğrudan raw bytes SHA-256'sıdır; object-result digests sırasıyla `sha256(b"orchestration/json-object/v3\0" + canonical_bytes(orch.json_object.v3(value)))`; BS facts `sha256(b"orchestration/bs-facts/v3\0" + canonical_bytes(orch.bs_facts.v3(value)))`; IS facts `sha256(b"orchestration/is-facts/v3\0" + canonical_bytes(orch.is_facts.v3(value)))`; pre-context Section 24.4 `cash-flow/pre-resolved-context/v1` domain'idir. Null her field'da canonical null'dır; bytes'ın kendisi girmez. Filename NFC exact string'dir; path normalization veya basename rewrite yoktur.

Facts field order serbest “dataclass order” referansı değildir; V3 manifesti literal olarak kilitlidir. Balance Sheet: `(current_assets, non_current_assets, total_assets, short_term_liabilities, long_term_liabilities, equity, total_liabilities_and_equity, cash_and_equivalents, inventory, trade_receivables, trade_payables, account_details)`. Income Statement: `(gross_sales, sales_deductions, net_sales, cost_of_sales, gross_profit, operating_expenses, other_operating_income, other_operating_expenses, operating_profit, depreciation_and_amortization, ebit, ebitda, financing_expenses, extraordinary_income, extraordinary_expenses, profit_before_tax, net_profit, account_details)`. Decimal/null ve strict sorted account-details object dışında type kabul edilmez; field missing/extra/reorder fail-closed'dur.

`run_options_v3_digest = sha256(b"orchestration/run-options/v3\0" + canonical_bytes(orch.run_options.v3(...))).hexdigest()`; root field sırası exact `OrchestrationRunOptionsV3` declaration order'ıdır: `industry_code`, `company_size_bucket`, `tenant_id`, `report_type`, `dashboard_type`, `company_metadata`, `reporting_period_label_tr`, `optional_sections`, `currency_display_policy`, `locale`, `render_contract`. Option enum/string manifest validation hash'ten önce çalışır. Canonical bytes aynı strict scalar/tuple/object kurallarını kullanır; float, list, unknown dataclass veya repr fallback yasaktır. Full-field golden vectors ve her tek-field mutation testi bütün leaf/root digest'leri kilitler.

Cash-flow engine fingerprint'i CASH_FLOW invocation'ından hemen önce, FS dependency record'ları mevcutken late-bound hesaplanır; request fingerprint ile karıştırılmaz. Source locator projection'ı exact XOR'dur:

```text
persisted source = ("persisted", source_role, analysis_result_uuid,
                    source_snapshot_digest,
                    canonical_result_digest, source_provenance_digest,
                    engine_schema_version, engine_model_version)
same-run source  = ("same_run", source_role, dependency_engine_code,
                    dependency_input_fingerprint,
                    dependency_canonical_result_digest,
                    dependency_owner_content_digest,
                    source_provenance_digest,
                    dependency_engine_schema_version,
                    dependency_engine_model_version)
absent source    = ("absent", source_role)
```

`source_snapshot_digest = sha256(b"cash-flow/source-snapshot/v1\0" + canonical_bytes(cf.source_snapshot.v1(snapshot))).hexdigest()` olur. `dependency_canonical_result_digest`, owner ID oluşmadan exact source financial-result codec'iyle; `dependency_owner_content_digest`, aynı-run source'un frozen owner semantic projection'ıyla hesaplanır ve terminal execution'ın `owner_content_digest` alanına aynen yazılır. Persisted legacy Trial Balance/BS/IS owner'ı için universal orchestration `owner_content_digest` varsayılmaz; persisted locator yalnız strict canonical-result + recursive provenance + snapshot digest'lerini bağlar. Same-run source'a placeholder/result ID eklenmez. Source locator tuple'ları `CashFlowSourceRole` declaration order'ında, absent dahil exact birer kez bulunur.

Cash-flow engine fingerprint root'u exact declaration-order `cf.engine_fingerprint.v1` record'udur: `fingerprint_schema_version="1.0.0"`, `engine_schema_version="1.0.0"`, `engine_model_version="1.0.0"`, `current_period_descriptor_digest`, `prior_period_descriptor_digest`, `comparability_proof_digest`, `source_candidate_set_digest`, `source_locators`, `pre_resolved_context_digest`, `final_account_evidence_bundle_digest`, `functional_currency_code`, `monetary_unit_multiplier`, `accounting_basis_code`, `accounting_policy_version`, `cash_equivalent_policy_version`, `mapping_registry_version`, `presentation_policy_version`, `reconciliation_policy_version`, `policy_bundle_digest`. Null optionals canonical null'dır; currency/unit exact `TRY`/`Decimal("1")` olur. Hash formülü `sha256(b"cash-flow/engine-input-fingerprint/v1\0" + canonical_bytes(cf.engine_fingerprint.v1(...))).hexdigest()`'tır. Raw payload, raw account name, DB-generated future owner/lineage IDs ve caller order fingerprint'e girmez; source semantic UUID/digest/proof ve bütün amount-affecting policies girer. Missing/extra/reordered field, absent role omissionu veya one-field mismatch fail-closed'dur.

Dependency technical FAILED/SKIPPED ise result-content digest yoktur ve CASH_FLOW fingerprint/result üretilmez. Diagnostic domain outcome'da envelope digest vardır; minimum-data result fingerprint'i bu digest'i kapsar. Resume snapshot aynı locator tag/schema'yı kullanır; persisted locator ile same-run locator birbirine cast edilmez.

Ratio ve Executive Report fingerprint projection'ı üç kapalı branch'tir:

1. Cash Flow requested değil: v2 projection byte-for-byte kullanılır; yeni null/default key eklenmez.
2. Cash Flow requested ve payload sahibi `COMPLETED/DEGRADED/REUSED`: `cash_flow_state=("result", input_fingerprint, result_canonical_digest)` eklenir.
3. Cash Flow requested fakat result yok: `cash_flow_state=("no_result", execution_status, cash_flow_input_fingerprint)` sentinel'ı eklenir.

Böylece farklı başarısız Cash Flow girdileri aynı downstream fingerprint'e çökmez. Requested/status branch mismatch'te Ratio/Report reuse reddedilir.

### 24.6 Engine version compatibility manifesti

V3 reuse source of truth `ORCHESTRATION_V3_ENGINE_VERSION_MANIFEST` olup exact `(schema, model)` çiftleri şöyledir:

| Engine | Exact compatible version |
|---|---|
| FS Balance Sheet | `(None, "1.0.0")` |
| FS Income Statement | `(None, "1.0.0")` |
| Cash Flow | `("1.0.0", "1.0.0")` |
| Ratio | `("1.0", "1.1.0")` |
| Benchmark | `(None, "1.0.0")` |
| Health Score | `("1.0.0", "1.0.0")` |
| Credit Score | `("1.0.0", "1.0.0")` |
| Recommendation | `("1.0.0", "1.0.0")` |
| Executive Report | no-CF branch `("1.0.0", "1.0.0")`; CF-aware branch `("1.1.0", "1.1.0")` |
| Dashboard | `("1.0.0", "1.0.0")` |
| Render Contract | `("1.0.0", None)` |

`None` wildcard değildir; exact expected value'dır. Resume/reuse, branch tarafından beklenen pair ile stored pair'i exact karşılaştırır. Optional Cash Flow absent branch yalnız Cash Flow requested değilse satisfied sayılır. Requested-result branch exact result digest/fingerprint/version ister; requested-no-result branch downstream reuse'a izin vermez. Unknown version veya missing version manifest entry fail-closed'dur.

### 24.7 Resume/reuse

- V2 run yalnız legacy V2 read/query path'inden okunabilir; Cash Flow backfill edilmez.
- V3 Resume/Retry source run zorunlu olarak V3'tür. V2 source verilirse `VERSION_INCOMPATIBLE_ON_REUSE` ile fail-closed reddedilir; V2 node'u V3 snapshot'a taşınmaz ve fresh/clean-start fallback yapılmaz.
- Fresh V3 Start, Cash Flow istenmese dahi gereken V3 node'ları V3 contract altında çalıştırır; V2 execution reuse etmez. No-Cash-Flow fingerprint branch'inin V2 ile byte-eşit olması yalnız regression/compatibility garantisidir, cross-major reuse yetkisi değildir.
- V3 request Cash Flow istiyor fakat V3 snapshot'ta yoksa Cash Flow çalışır; snapshot'taki Ratio ve Executive Report cash-flow-aware request için reuse edilmez.
- `INSUFFICIENT_DATA` dahil payload sahibi degraded sonuç exact aynı fingerprint/lineage ile reuse edilebilir.
- Failure outcome reuse edilemez.
- Current engine schema/model version manifesti snapshot değerleriyle birebir karşılaştırılır; mevcut yalnız-fingerprint kontrolü yeterli değildir.
- Reuse dependency gate, kullanılan `all_of`, satisfied `any_of` ve satisfied `optional` dependency fingerprint'lerini kapsar.
- Cross-period source yeniden yüklenir, owner digest'i payload üzerinden tekrar hesaplanır ve lineage ile eşleştirilir.
- Eksik/corrupt source'ta clean-start fallback yasaktır.

Snapshot builder Cash Flow'u BS/IS generic branch'ine düşüremez; ayrı strict `CashFlowResult` codec branch'i zorunludur.

### 24.8 Ayrı V3 persistence contract'ı

Mevcut 5.0B `PersistTerminalRunCommand`, `FinancialResultOwnerBinding`, `ResumeEngineBinding`, `SnapshotLoadResult`, `RESULT_OWNERSHIP_REGISTRY`, `RunStorePort`, `SnapshotReaderPort` ve bunların transitif field manifestleri **aynen kalır**; V3 type'larına alias edilmez. Cash Flow persistence aşağıdaki ayrı contract ailesini kullanır:

```python
class ResultOwnerV3(str, Enum):
    FINANCIAL_ANALYSIS_RESULT = "financial_analysis_result"
    ORCHESTRATION_ARTIFACT = "orchestration_artifact"

@dataclass(frozen=True)
class ResultOwnershipSpecV3:
    owner: ResultOwnerV3
    analysis_type: AnalysisType | None

RESULT_OWNERSHIP_REGISTRY_V3: Mapping[OrchestrationEngineCodeV3, ResultOwnershipSpecV3]
# exact: FS_BALANCE_SHEET/FS_INCOME_STATEMENT/CASH_FLOW/RATIO financial;
# diğer yedi engine artifact owner.

@dataclass(frozen=True)
class PersistenceRunScopeV3:
    tenant_id: UUID
    company_id: UUID
    period_id: UUID

@dataclass(frozen=True)
class ResumeEngineBindingV3:
    engine_code: OrchestrationEngineCodeV3
    source_engine_execution_id: UUID
    artifact_id: UUID | None
    financial_analysis_result_id: UUID | None
    owner_content_digest: str | None
    financial_result_canonical_digest: str | None
    input_fingerprint: str
    engine_schema_version: str | None
    engine_model_version: str | None

@dataclass(frozen=True)
class ResumePersistenceContextV3:
    persisted_run_id: UUID
    previous_run_id: str
    scope: PersistenceRunScopeV3
    engine_bindings: tuple[ResumeEngineBindingV3, ...]
    orchestration_contract_version: str = "3.0.0"

@dataclass(frozen=True)
class SnapshotLoadResultV3:
    snapshot: PreviousExecutionSnapshotV3
    persistence_context: ResumePersistenceContextV3

@dataclass(frozen=True)
class FinancialResultSourceBindingV3:
    role: AnalysisSourceRole
    source_document_id: UUID | None
    source_analysis_result_id: UUID | None

@dataclass(frozen=True)
class CashFlowLineageBindingV3:
    source_role: CashFlowSourceRole
    source_analysis_result_id: UUID
    source_period_id: UUID
    source_canonical_digest: str
    source_provenance_digest: str
    source_analysis_type: AnalysisType
    source_engine_version: str
    current_period_descriptor_digest: str
    prior_period_descriptor_digest: str | None
    comparability_proof_digest: str | None

@dataclass(frozen=True)
class CreateFinancialResultOwnerV3:
    analysis_type: AnalysisType
    source_mode: SourceMode
    document_id: UUID | None
    engine_version: str
    started_at: datetime
    completed_at: datetime
    same_period_source_bindings: tuple[FinancialResultSourceBindingV3, ...]
    cash_flow_lineage: tuple[CashFlowLineageBindingV3, ...]

@dataclass(frozen=True)
class FinancialResultOwnerBindingV3:
    engine_code: OrchestrationEngineCodeV3
    existing_owner_id: UUID | None
    create_owner: CreateFinancialResultOwnerV3 | None
    expected_same_period_source_bindings: tuple[FinancialResultSourceBindingV3, ...]
    expected_cash_flow_lineage: tuple[CashFlowLineageBindingV3, ...]
    expected_canonical_result_digest: str | None
    expected_owner_content_digest: str
    expected_current_period_descriptor_digest: str | None
    expected_prior_period_descriptor_digest: str | None
    expected_comparability_proof_digest: str | None

@dataclass(frozen=True)
class PersistTerminalRunCommandV3:
    scope: PersistenceRunScopeV3
    run_result: OrchestrationRunResultV3
    requested_outputs: tuple[OrchestrationEngineCodeV3, ...]
    resume_context: ResumePersistenceContextV3 | None
    financial_owner_bindings: tuple[FinancialResultOwnerBindingV3, ...]
    telemetry: ExecutionTelemetryV3 | None
    persistence_contract_version: str = "3.0.0"

@dataclass(frozen=True)
class PersistedRunV3:
    id: UUID
    run_id: str
    request_fingerprint: str
    terminal_content_digest: str
    scope: PersistenceRunScopeV3
    finalized_at: datetime
    orchestration_contract_version: str

@dataclass(frozen=True)
class RunHistoryPageV3:
    items: tuple[PersistedRunV3, ...]
    next_cursor: str | None

class RunStorePortV3(Protocol):
    def load_run(self, run_id: str) -> PersistedRunV3 | None: ...
    def persist_terminal_run(self, command: PersistTerminalRunCommandV3) -> PersistedRunV3: ...
    def list_run_history(self, scope: PersistenceRunScopeV3, cursor: str | None, limit: int) -> RunHistoryPageV3: ...

class SnapshotReaderPortV3(Protocol):
    def build_previous_execution_snapshot(
        self, run_id: str, target_scope: PersistenceRunScopeV3
    ) -> SnapshotLoadResultV3: ...
```

`ResumeEngineBindingV3` owner XOR invariant'ı owner-bearing execution'da tam bir owner, result'sız technical FAILED/SKIPPED execution'da iki owner alanı da null olmasını zorunlu kılar. Financial owner'da `owner_content_digest` daima zorunludur. `financial_result_canonical_digest` yalnız non-null `result_json` için zorunludur. BS/IS domain-failure yolunda persisted owner `AnalysisStatus.FAILED`, `result_json=None`, `canonical_result_digest=None` taşırken onu sahiplenen orchestration execution `EngineExecutionStatusV3.DEGRADED` olabilir ve full diagnostic semantics'i `owner_content_digest` ile bağlar. Bu özel null yol yalnız BS/IS için ve exact source-mode/error/trial-balance semantics doğrulandığında geçerlidir; Cash Flow/Ratio payload owner'ında canonical digest zorunludur. Artifact'ta yalnız `owner_content_digest` zorunludur. Resume builder source execution'ın gerçek owner FK'sini, owner content digest'ini, nullable financial canonical-result digest kuralını, engine code/schema/model version'ını, input fingerprint'ini ve scope'u birebir doğrular. Unknown/missing/mixed V2/V3 binding fail-closed'dur.

`FinancialResultOwnerBindingV3` owner mode'u tam bir `existing_owner_id XOR create_owner`'dır. Expected lineage alanları XOR dışında ve her iki modda da zorunlu doğrulama kanıtıdır: BS/IS/Ratio yalnız `expected_same_period_source_bindings`, Cash Flow yalnız `expected_cash_flow_lineage` taşır. Create owner içindeki staged graph bu expected graph'a exact eşit; existing owner'ın durable graph'ı da aynı expected graph'a exact eşit olmadan reuse yoktur. Cash Flow binding'inde current descriptor digest zorunlu; COMPLETE/PARTIAL için prior descriptor + comparability proof zorunlu, `INSUFFICIENT_DATA` için ikisi birlikte null olabilir. BS/IS domain-failure owner'da `expected_canonical_result_digest=None`, diğer non-null financial payloadlarda lowercase SHA-256 zorunludur. Existing Cash Flow owner ancak strict result bytes/digest, period proof ve exact normalized lineage graph birlikte eşitse seçilebilir. `ResultOwnershipRegistryV3` dört financial/yedi artifact sayısını declaration-order golden manifest ile kilitler.

V3 adapter mevcut tabloları ve aynı terminal transaction mekanizmasını kullanır fakat V1 command/port'a downcast etmez. V1↔V3 command, snapshot, binding veya registry nesnesi kabul edilirse persistence başlamadan contract error oluşur. `RunStorePortV3.persist_terminal_run()` Cash Flow owner, lineage, execution/artifact ve terminal run'ı Section 22.3'teki SAVEPOINT kuralıyla atomik yazar. Bu yeni port ailesi 5.0B V1 public sözleşmesini değiştirmez; 4.5'e ait additive public contract'tır.

`ORCHESTRATION_V3_TERMINAL_TAG_MANIFEST` exact `orch.terminal_content.v3`, `orch.terminal_execution.v3`, `orch.structured_error.v3`, `orch.financial_owner_semantics.v3`, `orch.source_locator_existing_analysis.v3`, `orch.source_locator_same_run.v3` pure frozen record tag'lerini içerir; unknown record/repr fallback yoktur. `terminal_content_digest_v3` executable ve DB-ID bağımsızdır:

```text
sha256(
  b"orchestration/terminal-content/v3\0" +
  canonical_bytes(orch.terminal_content.v3(...))
).hexdigest()
```

Exact declaration-order root fields: `run_id`, `correlation_id`, `generated_at`, `request_fingerprint`, `persistence_scope=(tenant_id, company_id, period_id)`, `previous_run_reference`, `status`, declaration-order unique `requested_outputs`, `orchestration_schema_version`, `orchestration_model_version`, `execution_plan_version`, `execution_records`, `warnings`, `structured_errors`, `execution_provenance`, `input_version_inventory`, `financial_owner_semantics`. Null canonical null'dır. Start'ta `previous_run_reference=None`; Resume/Retry'da store `resume_context.persisted_run_id` ile authoritative previous run'ı yükleyip exact `(previous_run_id, request_fingerprint, terminal_content_digest, orchestration_schema_version, orchestration_model_version, execution_plan_version, fingerprint_schema_version)` record'unu kurar. Command logical `previous_run_id`, stored FK target ve bu semantic record exact eşleşmezse persistence başlamadan conflict'tir. `execution_records` graph execution ordinal'ında exact `orch.terminal_execution.v3` rows taşır: `engine_code`, `execution_ordinal`, `status`, `inner_status_value`, declaration-order dependency codes, engine schema/model, input fingerprint, fingerprint schema, result kind, `owner_content_digest`, nullable financial canonical-result digest, nullable artifact content digest, record-local exact structured-error projection ve nullable semantic reuse reference. Result/owner XOR ve digest parity engine registry'yle doğrulanır.

Her `StructuredErrorV3`, record-local ve run-level tuple'da exact `orch.structured_error.v3(category, engine_code, message_tr, cash_flow_error_code, safe_metadata, retryable, original_exception_type)` projection'uyla girer; Cash Flow code/metadata/retryable alanını düşürmek yasaktır. Warnings orchestrator'ın canonical tuple sırasını, errors `structured_errors` declaration/ordinal sırasını, execution provenance kendi field-order tuple'larını taşır; duplicate/non-canonical order fail-closed'dur.

Record/run error parity hash'ten ve persistence'tan önce zorunludur. `engine_code` non-null her `structured_errors` item'i exact aynı engine record'ın `error` alanıyla object equality taşır ve her record en fazla bir error taşır; record-local error run tuple'ında exact bir kez bulunur. `structured_errors` sırası önce engine execution ordinal'ındaki non-null record errors, sonra `engine_code=None` run-level errors'ın orchestrator declaration sırasıdır. Missing counterpart, duplicate, different code/message/metadata/retryable veya engine-code mismatch terminal contract violation'dır. Böylece aynı failure iki farklı projection olarak hashlenip persist edilemez.

`execution_provenance` serbest veya kayıplı bir second source of truth değildir; exact durable execution-record projection'ıdır. `execution_provenance.execution_plan_version == run_result.execution_plan_version` zorunludur. Engine records declaration/ordinal sırasında: `engine_call_sequence`, status'u `COMPLETED|DEGRADED|FAILED|REUSED` olan record'ların engine-code tuple'ı; `reused_engine_codes`, exact `REUSED` record'ları; `skipped_engine_codes`, exact `SKIPPED` record'larıdır. `NOT_STARTED` hiçbir tuple'a girmez. Her tuple unique ve declaration-order'dır; reused tuple call-sequence'in exact alt dizisi, skipped tuple call-sequence ile disjoint'tir. Store terminal hash/yazma öncesi supplied object'i bu derived projection'la object-equality karşılaştırır; restart reader yalnız durable engine rows + run execution-plan version'ından aynı projection'ı yeniden kurar. Aynı durable records için farklı call/reused/skipped tuple terminale yazılamaz veya aynı DB state'e çökemez.

`financial_owner_semantics`, financial engine declaration order'ında exact `orch.financial_owner_semantics.v3` row'larıdır: engine code, result kind, canonical-result digest, owner-content digest, source mode, primary pre-existing document ID ve normalized lineage. Same-period lineage role order'ında `(role, locator_tag, locator_value_or_engine_code, locator_semantic_digest_or_null, document_source_proof_digest_or_null)` taşır. Locator semantic digest document branch'inde document-source proof'tur; existing analysis branch'inde authoritative source canonical-result + recursive provenance projection'ının digest'i; same-run branch'inde source engine canonical-result + owner-content digest projection'ının digest'idir. Cash Flow lineage `CashFlowSourceRole` order'ında `(role, locator_tag, preexisting_source_uuid_or_same_run_engine_code, source_period_id, source_canonical_digest, source_provenance_digest, source_analysis_type, source_engine_version, current/prior descriptor digests, comparability_proof_digest)` taşır. Persisted legacy source için orchestration owner-content digest aranmaz. Same-run locator'da generated owner UUID yerine engine code + computed content digests kullanılır; pre-existing document/source UUID'leri provenance semantiği olduğu için girer. Create-vs-existing-owner seçimi, newly generated owner/lineage/run/execution/artifact UUID'leri, database `created_at/finalized_at`, SAVEPOINT adı, physical blob locator/credential ve telemetry duration terminal digest'e girmez. Caller-supplied `generated_at` root'ta kalır; persistence clock timestamps girmez.

`locator_semantic_digest` branch formülleri exact'tir: document branch'i `document_source_proof_digest` değerini aynen kullanır; existing-analysis branch'i `sha256(b"orchestration/source-locator/existing-analysis/v3\0" + canonical_bytes(orch.source_locator_existing_analysis.v3(source_analysis_result_id, canonical_result_digest, source_provenance_digest))).hexdigest()`; same-run branch'i `sha256(b"orchestration/source-locator/same-run/v3\0" + canonical_bytes(orch.source_locator_same_run.v3(source_engine_code, canonical_result_digest, owner_content_digest))).hexdigest()` kullanır. Document branch'inde iki digest exact eşit, diğer branch'lerde `document_source_proof_digest=None` olmalıdır. Branch field missing/extra veya persisted legacy source'a owner-content digest zorlamak contract error'dur.

Analysis-source locator tag'i final owner map'ten sonra canonical ve restart-reconstructible'dır. Final `source_analysis_result_id`, aynı terminal run'daki bir financial engine execution'ın owner FK'sine eşitse tek geçerli semantic branch `same_run` ve locator engine code o unique execution'ın engine code'udur; public/internal plan bunu `existing_analysis` diye getirmişse silent canonicalization yapılmaz, persistence-before-stage conflict'tir. Aynı run owner map'inde eşleşme yoksa tek geçerli branch `existing_analysis`'tir. Bir ID'nin birden fazla same-run engine'e map olması integrity failure'dır. Reader aynı run'ın durable financial execution owner map'ini kurup fiziksel `financial_analysis_result_sources.source_analysis_result_id` satırından aynı tag/engine-code'u deterministik yeniden üretir. Current BS/IS Cash Flow roles, REUSED current dependency ve injected Cash Flow→Ratio edge bu kurala; prior/TB external owner'lar existing branch'e tabidir. Böylece aynı fiziksel source row iki farklı terminal digest semantiğine sahip olamaz.

Semantic reuse reference exact `(source_run_id, source_engine_code, source_input_fingerprint, source_owner_content_digest, source_financial_canonical_digest_or_null, source_schema_version, source_model_version)` tuple'ıdır; DB execution UUID'si girmez. Aynı run/request/scope/previous-run/semantic terminal sonucu create/reuse veya concurrent winner/loser topology'sinden bağımsız aynı digest'i üretir. Her root/record/error/lineage tek-field mutation'ı digest'i değiştirir. Existing-run early return yalnız request fingerprint + bu exact terminal digest + scope + durable previous-run FK/reference eşitse olur; staged owner/lineage SAVEPOINT rollback/discard edilmeden winner döndürülemez. Böylece START winner RESUME/RETRY context'ine veya farklı previous run'a map edilemez; operation-kind/application-command-digest parity ayrıca immutable `RunScopeClaimV3` tarafından doğrulanır.

## 25. Ownership ve Application Projection

V3 ownership registry:

```text
FinancialAnalysisResult owners (4):
  FS_BALANCE_SHEET, FS_INCOME_STATEMENT, CASH_FLOW, RATIO

OrchestrationArtifact owners (7):
  BENCHMARK, HEALTH_SCORE, CREDIT_SCORE, RECOMMENDATION,
  EXECUTIVE_REPORT, DASHBOARD, RENDER_CONTRACT
```

Cash-flow financial payload reference:

- `owner_type=FINANCIAL_ANALYSIS_RESULT`;
- `financial_analysis_result_id` zorunlu;
- `canonical_digest` zorunlu;
- `artifact_serializer_schema_version=None`.

Application core CashFlow engine dataclass'ını dışarı açmaz. V2 application DTO projection, recursive ApplicationJsonValue algebra'sı ve typed cash-flow summary DTO'ları üzerinden yapılır. `source_lineage_references`, durable lineage tablosunun doğrulanmış read projection'ıdır; bağımsız write source değildir.

`SUPPORTED_APPLICATION_DTO_SCHEMA_VERSIONS=("1.0.0", "2.0.0")` olur. V1 command aynı eski digest'i üretir. Aynı `run_id` ile cash-flow eklenmiş v2 command farklı fingerprint/digest olduğundan fail-closed conflict'tir; eski run yerinde genişletilemez.

### 25.1 Exact application-v2 contract

V1 class/enum'ları yerinde değişmez. Ayrı `ApplicationEngineCodeV2` manifesti mevcut 10 application engine değerine `CASH_FLOW` ekler. Public caller persistence owner/FK/lineage seçmez; yalnız şu intent'i verir:

```python
class ApplicationEngineCodeV2(str, Enum):
    FS_BALANCE_SHEET = "fs_balance_sheet"
    FS_INCOME_STATEMENT = "fs_income_statement"
    CASH_FLOW = "cash_flow"
    RATIO = "ratio"
    BENCHMARK = "benchmark"
    HEALTH_SCORE = "health_score"
    CREDIT_SCORE = "credit_score"
    RECOMMENDATION = "recommendation"
    EXECUTIVE_REPORT = "executive_report"
    DASHBOARD = "dashboard"
    RENDER_CONTRACT = "render_contract"

class ApplicationFinancialSourceModeV2(str, Enum):
    DIRECT_DOCUMENT = "direct_document"
    TRIAL_BALANCE_DERIVED = "trial_balance_derived"
    MULTI_SOURCE_DERIVED = "multi_source_derived"

class ApplicationFinancialSourceRoleV2(str, Enum):
    PRIMARY_DOCUMENT = "primary_document"
    SUPPORTING_DOCUMENT = "supporting_document"
    PRIMARY_ANALYSIS = "primary_analysis"
    SUPPORTING_ANALYSIS = "supporting_analysis"
    TRIAL_BALANCE_FALLBACK = "trial_balance_fallback"
    PRIOR_PERIOD_REFERENCE = "prior_period_reference"

class ApplicationCashFlowMethodV2(str, Enum):
    INDIRECT = "indirect"

class ApplicationCashFlowPresentationProfileV2(str, Enum):
    TMS_TFRS_2024_INDIRECT_V1 = "tms_tfrs_2024_indirect_v1"
    BANK_CREDIT_V1 = "bank_credit_v1"
    MANAGEMENT_V1 = "management_v1"

@dataclass(frozen=True)
class FinancialSourceReferenceDTOV2:
    role: ApplicationFinancialSourceRoleV2
    source_document_id: UUID | None
    source_analysis_result_id: UUID | None
    source_engine_code: ApplicationEngineCodeV2 | None

@dataclass(frozen=True)
class FinancialSourceIntentDTOV2:
    engine_code: ApplicationEngineCodeV2
    company_id: UUID
    financial_period_id: UUID
    primary_document_id: UUID | None
    source_bindings: tuple[FinancialSourceReferenceDTOV2, ...]
    requested_source_mode: ApplicationFinancialSourceModeV2
    allow_existing_canonical_owner: bool
    expected_existing_owner_id: UUID | None
    provenance_metadata: ApplicationJsonValue
    caller_supplied_business_timestamp: datetime | None

@dataclass(frozen=True)
class CashFlowRequestDTOV2:
    method: ApplicationCashFlowMethodV2            # yalnız INDIRECT
    current_period_id: UUID
    expected_prior_period_id: UUID | None          # selection değil; varsa exact assertion
    presentation_profile: ApplicationCashFlowPresentationProfileV2
    accounting_policy_version: str
    cash_equivalent_policy_version: str
    mapping_registry_version: str
    reconciliation_policy_version: str
    cash_flow_contract_version: str = "1.0.0"
```

`FinancialSourceReferenceDTOV2` locator'ı exact XOR'dur; role/locator matrix mevcut V1 semantics'inin literal V2 karşılığıdır. `FinancialSourceIntentDTOV2.engine_code` yalnız `FS_BALANCE_SHEET`, `FS_INCOME_STATEMENT`, `RATIO` olabilir; `CASH_FLOW` intent'i kesin reddedilir. Cash Flow requested run'da BS/IS intent source graph'ı pre-resolvable olmak zorundadır: her binding yalnız `source_document_id` veya authoritative existing `source_analysis_result_id` taşır; nested `source_engine_code` preflight'ta `INVALID_COMMAND` ile reddedilir. Böylece current FS owner'ın final canonical source-binding tuple'ı ve `source_provenance_digest` Cash Flow invocation'ından önce bilinir. Ratio intent'indeki `source_engine_code` yalnız frozen legacy upstream BS/IS semantics'i için kullanılabilir; caller'ın `source_engine_code=CASH_FLOW` veya Cash Flow role/edge assembly göndermesi `INVALID_COMMAND`'dır. Cash Flow ve Ratio birlikte requested ve gerçek Cash Flow owner üretilmişse application owner planner exact `SUPPORTING_ANALYSIS(CASH_FLOW)` edge'ini otomatik ve tek kez inject eder; caller bunu seçemez/omit edemez/override edemez. Ratio graph'ı Cash Flow result bytes'ına girmez. Provisional/final iki digest veya placeholder UUID yoktur. Cash Flow owner/source/lineage assembly, gerçek V3 engine result ve trusted resolver çıktısından post-result yapılır. `expected_prior_period_id=None` “opening cash zero” demek değildir; resolver exact prior seçer. Doluysa resolver sonucu bununla eşleşmezse fail-closed olur. Source owner ID, canonical digest, account evidence, owner selection, lineage role veya `CashFlowPreResolvedContext` public command alanı değildir.

Command intent coverage, requested-output dependency closure'ündeki BS/IS/Ratio engine'leri için unique intent ister; Cash Flow için intent yasaktır. Eksik/fazla intent preflight'ta `INVALID_COMMAND` olur; owner planner'daki defensive eksik-intent kontrolü `PERSISTENCE_INTEGRITY_ERROR` ile durur. FAILED/SKIPPED/result-null engine için mevcut intent owner yaratmaz. Cash Flow `INSUFFICIENT_DATA` owner'ı doğrulanabilen source subset'i/zero-lineage ile üretilebilir; eksik source'u intent'ten uydurmaz.

V2 command'lar `ApplicationScopeDTO`, `ApplicationAuditContextDTO`, `AnalysisInputsDTO`, `AnalysisRunOptionsDTO`, `PriorPeriodProjectionDTO`, `CompanyMetadataDTO`, `ReportRequestDTO`, `DashboardRequestDTO` ve `RenderContractRequestDTO` gibi engine-code taşımayan frozen V1 leaf value object'lerini **değiştirmeden** nested value olarak kullanır. Bu leaf class'lara alan/default/schema eklenmez; V1 decoder ve digest aynen kalır. V2 top-level codec her nested leaf'i mevcut exact leaf manifestiyle encode eder ve unknown/missing field'i reddeder.

Üç write command'ın alanları tek tek ve exact'tir; “same as” inheritance serialization'ı yoktur:

```python
@dataclass(frozen=True)
class StartAnalysisCommandV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTOV2, ...]
    cash_flow_request: CashFlowRequestDTOV2 | None
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTO | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = "2.0.0"

@dataclass(frozen=True)
class ResumeAnalysisCommandV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO                 # operation=RESUME, previous_run_id zorunlu
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTOV2, ...]
    cash_flow_request: CashFlowRequestDTOV2 | None
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTO | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = "2.0.0"

@dataclass(frozen=True)
class RetryAnalysisCommandV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO                 # operation=RETRY, previous/original operation zorunlu
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    inputs: AnalysisInputsDTO
    run_options: AnalysisRunOptionsDTO
    source_intents: tuple[FinancialSourceIntentDTOV2, ...]
    cash_flow_request: CashFlowRequestDTOV2 | None
    prior_period_projection: PriorPeriodProjectionDTO | None
    company_metadata: CompanyMetadataDTO | None
    report_request: ReportRequestDTO | None
    dashboard_request: DashboardRequestDTO | None
    render_contract_request: RenderContractRequestDTO | None
    application_contract_version: str = "2.0.0"
```

Invariant: `CASH_FLOW in requested_outputs XOR cash_flow_request is None` değil, tam eşitliktir; Cash Flow requested ise request zorunlu, değilse yasaktır. Scope current period/company/tenant ile request current period exact eşleşir. Resume/Retry `scope.previous_run_id` zorunlu ve target `run_id`'den farklıdır; V3 source şartı geçmezse clean-start fallback yapmadan error outcome döner.

Cancel ve dört V2 query'nin alanları da ayrı ve exact'tir:

```python
@dataclass(frozen=True)
class CancelAnalysisCommandV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    application_contract_version: str = "2.0.0"

@dataclass(frozen=True)
class GetAnalysisStatusQueryV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    application_contract_version: str = "2.0.0"

@dataclass(frozen=True)
class GetAnalysisResultQueryV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    include_payloads: bool
    application_contract_version: str = "2.0.0"

@dataclass(frozen=True)
class GetExecutionDetailQueryV2:
    run_id: str
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    engine_code: ApplicationEngineCodeV2
    include_payload: bool
    application_contract_version: str = "2.0.0"

@dataclass(frozen=True)
class ListAnalysisHistoryQueryV2:
    correlation_id: str
    generated_at: datetime
    scope: ApplicationScopeDTO
    audit_context: ApplicationAuditContextDTO
    authorization_context_reference: str
    cursor: str | None
    limit: int
    application_contract_version: str = "2.0.0"
```

Kimlik/time/scope/limit invariant'ları V1'in aynısıdır; her query V3 contract discriminator'ına sahip run'ı ister ve V2 run'ı V3 DTO'ya upcast etmez. V2 result ailesi engine-code alanlarında `ApplicationEngineCodeV2` kullanır ve Cash Flow execution'ını aşağıdaki ayrı projection ile taşır:

```python
class ApplicationCashFlowStatusV2(str, Enum):
    COMPLETE_RECONCILED = "complete_reconciled"
    COMPLETE_UNRECONCILED = "complete_unreconciled"
    PARTIAL_RECONCILED = "partial_reconciled"
    PARTIAL_UNRECONCILED = "partial_unreconciled"
    INSUFFICIENT_DATA = "insufficient_data"
    INVALID_INPUT = "invalid_input"
    INTEGRITY_FAILURE = "integrity_failure"

ApplicationCashFlowResultBearingStatusV2 = Literal[
    ApplicationCashFlowStatusV2.COMPLETE_RECONCILED,
    ApplicationCashFlowStatusV2.COMPLETE_UNRECONCILED,
    ApplicationCashFlowStatusV2.PARTIAL_RECONCILED,
    ApplicationCashFlowStatusV2.PARTIAL_UNRECONCILED,
    ApplicationCashFlowStatusV2.INSUFFICIENT_DATA,
]

class ApplicationCashFlowReconciliationStatusV2(str, Enum):
    RECONCILED = "reconciled"
    ROUNDING_DIFFERENCE = "rounding_difference"
    UNRECONCILED_NON_MATERIAL = "unreconciled_non_material"
    UNRECONCILED_MATERIAL = "unreconciled_material"
    NOT_PERFORMED_INCOMPLETE_COMPONENTS = "not_performed_incomplete_components"
    NOT_PERFORMED_INSUFFICIENT_DATA = "not_performed_insufficient_data"

class ApplicationCashFlowEvidenceKindV2(str, Enum):
    EXACT = "exact"
    DERIVED = "derived"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"

class ApplicationCashFlowApplicabilityV2(str, Enum):
    APPLICABLE = "applicable"
    PROVEN_NOT_APPLICABLE = "proven_not_applicable"
    UNKNOWN = "unknown"

class ApplicationCashFlowActivityV2(str, Enum):
    OPERATING = "operating"
    INVESTING = "investing"
    FINANCING = "financing"
    CASH_AND_CASH_EQUIVALENTS = "cash_and_cash_equivalents"
    FX_EFFECT = "fx_effect"
    RECLASSIFICATION_EFFECT = "reclassification_effect"
    RECONCILIATION = "reconciliation"
    UNCLASSIFIED = "unclassified"

class ApplicationCashAvailabilityClassificationV2(str, Enum):
    UNRESTRICTED_INCLUDED = "unrestricted_included"
    RESTRICTED_INCLUDED = "restricted_included"
    RESTRICTED_EXCLUDED = "restricted_excluded"
    ELIGIBILITY_UNRESOLVED = "eligibility_unresolved"

class ApplicationCashFlowLineAggregationRoleV2(str, Enum):
    PRESENTATION_CONTRIBUTOR = "presentation_contributor"
    SUBTOTAL = "subtotal"
    ANALYTIC = "analytic"
    RECONCILIATION = "reconciliation"

class ApplicationCashFlowAvailabilityPeriodPositionV2(str, Enum):
    OPENING = "opening"
    CLOSING = "closing"

class ApplicationCashFlowEndpointReconciliationStatusV2(str, Enum):
    MATCHED = "matched"
    NOT_PERFORMED_INSUFFICIENT_DATA = "not_performed_insufficient_data"

# Exact literal member-pair constants; engine enum import/iteration yoktur.
APPLICATION_CASH_FLOW_LINE_CODE_MEMBER_PAIRS_V2 = (
    ("OPENING_CASH_AND_CASH_EQUIVALENTS", "opening_cash_and_cash_equivalents"),
    ("NET_PROFIT", "net_profit"),
    ("DEPRECIATION_AND_AMORTIZATION", "depreciation_and_amortization"),
    ("OTHER_PROVEN_NON_CASH_ADJUSTMENTS", "other_proven_non_cash_adjustments"),
    ("NON_CASH_ADJUSTMENT_TOTAL", "non_cash_adjustment_total"),
    ("INVENTORY_MOVEMENT", "inventory_movement"),
    ("TRADE_RECEIVABLES_MOVEMENT", "trade_receivables_movement"),
    ("OTHER_OPERATING_ASSET_MOVEMENT", "other_operating_asset_movement"),
    ("TRADE_PAYABLES_MOVEMENT", "trade_payables_movement"),
    ("OTHER_OPERATING_LIABILITY_MOVEMENT", "other_operating_liability_movement"),
    ("WORKING_CAPITAL_MOVEMENT_TOTAL", "working_capital_movement_total"),
    ("OTHER_PROVEN_OPERATING_ADJUSTMENTS", "other_proven_operating_adjustments"),
    ("INTEREST_EXPENSE_ACCRUAL_REVERSAL", "interest_expense_accrual_reversal"),
    ("INTEREST_INCOME_ACCRUAL_REVERSAL", "interest_income_accrual_reversal"),
    ("DIVIDEND_INCOME_ACCRUAL_REVERSAL", "dividend_income_accrual_reversal"),
    ("CURRENT_TAX_EXPENSE_ACCRUAL_REVERSAL", "current_tax_expense_accrual_reversal"),
    ("OPERATING_CASH_FLOW", "operating_cash_flow"),
    ("PROVEN_PPE_ACQUISITIONS", "proven_ppe_acquisitions"),
    ("PROVEN_PPE_DISPOSALS", "proven_ppe_disposals"),
    ("PROVEN_INTANGIBLE_ACQUISITIONS", "proven_intangible_acquisitions"),
    ("PROVEN_INTANGIBLE_DISPOSALS", "proven_intangible_disposals"),
    ("PROVEN_FINANCIAL_INVESTMENT_MOVEMENTS", "proven_financial_investment_movements"),
    ("ESTIMATED_NET_INVESTMENT_MOVEMENT", "estimated_net_investment_movement"),
    ("INVESTING_CASH_FLOW", "investing_cash_flow"),
    ("PROVEN_BORROWING_PROCEEDS", "proven_borrowing_proceeds"),
    ("PROVEN_DEBT_REPAYMENTS", "proven_debt_repayments"),
    ("ESTIMATED_NET_DEBT_MOVEMENT", "estimated_net_debt_movement"),
    ("PROVEN_EQUITY_CONTRIBUTIONS", "proven_equity_contributions"),
    ("PROVEN_DIVIDENDS_PAID", "proven_dividends_paid"),
    ("FINANCING_CASH_FLOW", "financing_cash_flow"),
    ("AUTHORITATIVE_INTEREST_PAID", "authoritative_interest_paid"),
    ("AUTHORITATIVE_INTEREST_RECEIVED", "authoritative_interest_received"),
    ("AUTHORITATIVE_DIVIDENDS_RECEIVED", "authoritative_dividends_received"),
    ("AUTHORITATIVE_INCOME_TAX_PAID", "authoritative_income_tax_paid"),
    ("AUTHORITATIVE_FX_EFFECT", "authoritative_fx_effect"),
    ("AUTHORITATIVE_RECLASSIFICATION_EFFECT", "authoritative_reclassification_effect"),
    ("CALCULATED_NET_CASH_CHANGE", "calculated_net_cash_change"),
    ("CLOSING_CASH_AND_CASH_EQUIVALENTS", "closing_cash_and_cash_equivalents"),
    ("BALANCE_SHEET_NET_CASH_CHANGE", "balance_sheet_net_cash_change"),
    ("RECONCILIATION_DIFFERENCE", "reconciliation_difference"),
    ("FREE_CASH_FLOW", "free_cash_flow"),
)
APPLICATION_CASH_FLOW_WARNING_CODE_MEMBER_PAIRS_V2 = (
    ("MINIMUM_DATA_INCOMPLETE", "minimum_data_incomplete"),
    ("ACCOUNT_UNCLASSIFIED", "account_unclassified"),
    ("CASH_EQUIVALENT_ELIGIBILITY_UNPROVEN", "cash_equivalent_eligibility_unproven"),
    ("NON_CASH_ADJUSTMENT_UNAVAILABLE", "non_cash_adjustment_unavailable"),
    ("GROSS_MOVEMENT_UNAVAILABLE", "gross_movement_unavailable"),
    ("ESTIMATED_NET_MOVEMENT_USED", "estimated_net_movement_used"),
    ("RECONCILIATION_DIFFERENCE", "reconciliation_difference"),
    ("MATERIAL_RECONCILIATION_DIFFERENCE", "material_reconciliation_difference"),
    ("PRESENTATION_EVIDENCE_UNAVAILABLE", "presentation_evidence_unavailable"),
    ("NEGATIVE_CASH_BALANCE", "negative_cash_balance"),
    ("OVERDRAFT_RECLASSIFIED_TO_FINANCING", "overdraft_reclassified_to_financing"),
)
APPLICATION_CASH_FLOW_ERROR_CODE_MEMBER_PAIRS_V2 = (
    ("INVALID_CONTRACT", "invalid_contract"),
    ("PERIOD_NOT_COMPARABLE", "period_not_comparable"),
    ("PERIOD_SELECTION_AMBIGUOUS", "period_selection_ambiguous"),
    ("SOURCE_NOT_FOUND", "source_not_found"),
    ("SOURCE_SCOPE_MISMATCH", "source_scope_mismatch"),
    ("SOURCE_STATUS_INVALID", "source_status_invalid"),
    ("SOURCE_DIGEST_MISMATCH", "source_digest_mismatch"),
    ("SOURCE_CURRENCY_MISMATCH", "source_currency_mismatch"),
    ("SOURCE_EVIDENCE_CONFLICT", "source_evidence_conflict"),
    ("POLICY_VERSION_UNSUPPORTED", "policy_version_unsupported"),
    ("MAPPING_REGISTRY_VERSION_UNSUPPORTED", "mapping_registry_version_unsupported"),
    ("MAPPING_CONFLICT", "mapping_conflict"),
    ("DECIMAL_NON_FINITE_OR_SCALE_INVALID", "decimal_non_finite_or_scale_invalid"),
    ("PERSISTENCE_INTEGRITY_FAILURE", "persistence_integrity_failure"),
    ("SOURCE_RESOLUTION_UNAVAILABLE", "source_resolution_unavailable"),
    ("PERSISTENCE_UNAVAILABLE", "persistence_unavailable"),
)
APPLICATION_CASH_FLOW_ACCOUNT_ROLE_MEMBER_PAIRS_V2 = (
    ("CASH_ON_HAND", "cash_on_hand"), ("BANK_ACCOUNT_CANDIDATE", "bank_account_candidate"),
    ("RESTRICTED_BANK_ASSET", "restricted_bank_asset"), ("DEMAND_DEPOSIT", "demand_deposit"),
    ("CASH_EQUIVALENT_INVESTMENT", "cash_equivalent_investment"), ("CHECK_RECEIVABLE", "check_receivable"),
    ("ISSUED_CHECK_OR_PAYMENT_ORDER", "issued_check_or_payment_order"), ("OTHER_LIQUID_ASSET_CANDIDATE", "other_liquid_asset_candidate"),
    ("POS_RECEIVABLE", "pos_receivable"), ("OPERATING_RECEIVABLE", "operating_receivable"),
    ("INVENTORY", "inventory"), ("OTHER_OPERATING_ASSET", "other_operating_asset"),
    ("OPERATING_PAYABLE", "operating_payable"), ("OTHER_OPERATING_LIABILITY", "other_operating_liability"),
    ("PPE", "ppe"), ("INTANGIBLE_ASSET", "intangible_asset"),
    ("FINANCIAL_INVESTMENT", "financial_investment"), ("EQUITY_FINANCIAL_INVESTMENT", "equity_financial_investment"),
    ("LONG_TERM_FINANCIAL_INVESTMENT", "long_term_financial_investment"), ("NON_CASH_INVESTMENT_COMMITMENT", "non_cash_investment_commitment"),
    ("BORROWING", "borrowing"), ("EQUITY", "equity"), ("NON_CASH_EQUITY", "non_cash_equity"),
    ("TAX_PAYABLE", "tax_payable"), ("TAX_RECEIVABLE", "tax_receivable"),
    ("INTEREST_PAYABLE", "interest_payable"), ("INTEREST_RECEIVABLE", "interest_receivable"),
    ("DIVIDEND_PAYABLE", "dividend_payable"), ("DIVIDEND_RECEIVABLE", "dividend_receivable"),
    ("INTEREST_EXPENSE_ACCRUAL", "interest_expense_accrual"), ("INTEREST_INCOME_ACCRUAL", "interest_income_accrual"),
    ("DIVIDEND_INCOME_ACCRUAL", "dividend_income_accrual"), ("CURRENT_TAX_EXPENSE_ACCRUAL", "current_tax_expense_accrual"),
    ("DEFERRED_TAX_ACCRUAL", "deferred_tax_accrual"), ("NON_CASH_ADJUSTMENT", "non_cash_adjustment"),
    ("UNCLASSIFIED", "unclassified"),
)
APPLICATION_CASH_FLOW_SOURCE_ROLE_MEMBER_PAIRS_V2 = (
    ("CURRENT_BALANCE_SHEET", "current_balance_sheet"),
    ("PRIOR_BALANCE_SHEET", "prior_balance_sheet"),
    ("CURRENT_INCOME_STATEMENT", "current_income_statement"),
    ("CURRENT_TRIAL_BALANCE", "current_trial_balance"),
    ("PRIOR_TRIAL_BALANCE", "prior_trial_balance"),
)
APPLICATION_CASH_FLOW_DERIVATION_CODE_MEMBER_PAIRS_V2 = (
    ("SOURCE_VALUE", "source_value"), ("BALANCE_DELTA", "balance_delta"),
    ("OPERATING_ASSET_SIGN_INVERSION", "operating_asset_sign_inversion"),
    ("OPERATING_LIABILITY_SIGN_PRESERVED", "operating_liability_sign_preserved"),
    ("NET_PROFIT_ACCRUAL_REVERSAL", "net_profit_accrual_reversal"),
    ("INDIRECT_OPERATING_SUBTOTAL", "indirect_operating_subtotal"),
    ("INVESTING_SUBTOTAL", "investing_subtotal"), ("FINANCING_SUBTOTAL", "financing_subtotal"),
    ("PRESENTATION_RECLASSIFICATION", "presentation_reclassification"),
    ("NET_CASH_CHANGE_SUM", "net_cash_change_sum"),
    ("BALANCE_SHEET_CASH_DELTA", "balance_sheet_cash_delta"),
    ("RECONCILIATION_DIFFERENCE", "reconciliation_difference"),
    ("FREE_CASH_FLOW_FROM_PROVEN_CAPEX", "free_cash_flow_from_proven_capex"),
)

ApplicationCashFlowLineCodeV2 = Enum("ApplicationCashFlowLineCodeV2", dict(APPLICATION_CASH_FLOW_LINE_CODE_MEMBER_PAIRS_V2), type=str)
ApplicationCashFlowWarningCodeV2 = Enum("ApplicationCashFlowWarningCodeV2", dict(APPLICATION_CASH_FLOW_WARNING_CODE_MEMBER_PAIRS_V2), type=str)
ApplicationCashFlowErrorCodeV2 = Enum("ApplicationCashFlowErrorCodeV2", dict(APPLICATION_CASH_FLOW_ERROR_CODE_MEMBER_PAIRS_V2), type=str)
ApplicationCashFlowAccountRoleV2 = Enum("ApplicationCashFlowAccountRoleV2", dict(APPLICATION_CASH_FLOW_ACCOUNT_ROLE_MEMBER_PAIRS_V2), type=str)
ApplicationCashFlowSourceRoleV2 = Enum("ApplicationCashFlowSourceRoleV2", dict(APPLICATION_CASH_FLOW_SOURCE_ROLE_MEMBER_PAIRS_V2), type=str)
ApplicationCashFlowDerivationCodeV2 = Enum("ApplicationCashFlowDerivationCodeV2", dict(APPLICATION_CASH_FLOW_DERIVATION_CODE_MEMBER_PAIRS_V2), type=str)

@dataclass(frozen=True)
class ApplicationCashFlowActivityAllocationDTO:
    activity: ApplicationCashFlowActivityV2
    amount: Decimal

@dataclass(frozen=True)
class ApplicationCashFlowEvidenceReferenceDTO:
    evidence_kind: ApplicationCashFlowEvidenceKindV2
    source_role: ApplicationCashFlowSourceRoleV2
    financial_analysis_result_id: UUID
    source_canonical_digest: str
    source_provenance_digest: str
    account_codes: tuple[str, ...]
    mapping_ids: tuple[str, ...]
    derivation_code: ApplicationCashFlowDerivationCodeV2

@dataclass(frozen=True)
class ApplicationCashFlowLineItemDTO:
    line_code: ApplicationCashFlowLineCodeV2
    canonical_amount: Decimal | None
    aggregation_role: ApplicationCashFlowLineAggregationRoleV2
    presentation_allocations: tuple[ApplicationCashFlowActivityAllocationDTO, ...]
    applicability: ApplicationCashFlowApplicabilityV2
    evidence_kind: ApplicationCashFlowEvidenceKindV2
    evidence: tuple[ApplicationCashFlowEvidenceReferenceDTO, ...]
    missing_inputs: tuple[str, ...]
    warning_codes: tuple[ApplicationCashFlowWarningCodeV2, ...]

@dataclass(frozen=True)
class ApplicationCashFlowCompletenessDTO:
    manifest_version: str
    required_line_count: int
    exact_count: int
    derived_count: int
    estimated_count: int
    unavailable_count: int
    available_ratio: Decimal
    optional_analytics_available_count: int
    optional_analytics_unavailable_count: int

@dataclass(frozen=True)
class ApplicationCashAvailabilityObservationDTO:
    period_position: ApplicationCashFlowAvailabilityPeriodPositionV2
    classification: ApplicationCashAvailabilityClassificationV2
    amount: Decimal | None
    restriction_preserves_cash_nature: bool | None
    evidence: tuple[ApplicationCashFlowEvidenceReferenceDTO, ...]

@dataclass(frozen=True)
class ApplicationCashAvailabilityDisclosureDTO:
    component_reference_digest: str
    account_role: ApplicationCashFlowAccountRoleV2
    observations: tuple[ApplicationCashAvailabilityObservationDTO, ...]

@dataclass(frozen=True)
class ApplicationCashFlowEndpointReconciliationDTO:
    period_position: ApplicationCashFlowAvailabilityPeriodPositionV2
    policy_defined_cash_and_equivalents: Decimal | None
    reported_balance_sheet_cash_and_equivalents: Decimal | None
    difference: Decimal | None
    status: ApplicationCashFlowEndpointReconciliationStatusV2
    balance_sheet_evidence: tuple[ApplicationCashFlowEvidenceReferenceDTO, ...]

@dataclass(frozen=True)
class ApplicationCashFlowIssueDTO:
    code: ApplicationCashFlowWarningCodeV2 | ApplicationCashFlowErrorCodeV2
    safe_metadata: ApplicationJsonValue

@dataclass(frozen=True)
class ApplicationCashFlowLineageReferenceDTO:
    source_role: ApplicationCashFlowSourceRoleV2
    financial_analysis_result_id: UUID
    source_period_id: UUID
    canonical_digest: str
    source_provenance_digest: str

class ApplicationCashFlowPeriodTypeV2(str, Enum):
    YEAR_END = "year_end"
    QUARTER = "quarter"
    TEMPORARY_TAX = "temporary_tax"
    MONTHLY = "monthly"
    CUSTOM = "custom"

class ApplicationCashFlowPeriodStatusV2(str, Enum):
    CLOSED = "closed"

class ApplicationCashFlowAccountingBasisCodeV2(str, Enum):
    TR_TDHP_ACCRUAL = "tr_tdhp_accrual"

@dataclass(frozen=True)
class ApplicationCashFlowPeriodDescriptorDTO:
    period_id: UUID
    company_id: UUID
    tenant_id: UUID
    currency_code: str
    monetary_unit_multiplier: Decimal
    period_type: ApplicationCashFlowPeriodTypeV2
    start_date: date
    end_date: date
    annual_reporting_period_start_date: date
    annual_reporting_period_end_date: date
    months_covered: int
    status: ApplicationCashFlowPeriodStatusV2
    accounting_basis_code: ApplicationCashFlowAccountingBasisCodeV2
    accounting_policy_version: str
    ifrs18_early_adopted: bool

@dataclass(frozen=True)
class CashFlowProjectionDTOV2:
    opening_cash_and_cash_equivalents: Decimal | None
    closing_cash_and_cash_equivalents: Decimal | None
    operating_cash_flow: Decimal | None
    investing_cash_flow: Decimal | None
    financing_cash_flow: Decimal | None
    authoritative_fx_effect: Decimal | None
    authoritative_reclassification_effect: Decimal | None
    calculated_net_cash_change: Decimal | None
    balance_sheet_net_cash_change: Decimal | None
    reconciliation_difference: Decimal | None
    free_cash_flow: Decimal | None
    status: ApplicationCashFlowResultBearingStatusV2
    reconciliation_status: ApplicationCashFlowReconciliationStatusV2
    completeness: ApplicationCashFlowCompletenessDTO
    currency_code: str
    monetary_scale: int
    policy_version: str
    accounting_policy_version: str
    cash_equivalent_policy_version: str
    presentation_policy_version: str
    reconciliation_policy_version: str
    mapping_registry_version: str
    current_period_id: UUID
    prior_period_id: UUID | None
    current_period_descriptor: ApplicationCashFlowPeriodDescriptorDTO
    prior_period_descriptor: ApplicationCashFlowPeriodDescriptorDTO | None
    current_period_descriptor_digest: str
    prior_period_descriptor_digest: str | None
    comparability_proof_digest: str | None
    line_items: tuple[ApplicationCashFlowLineItemDTO, ...]
    cash_availability_disclosures: tuple[ApplicationCashAvailabilityDisclosureDTO, ...]
    endpoint_reconciliations: tuple[ApplicationCashFlowEndpointReconciliationDTO, ...]
    evidence: tuple[ApplicationCashFlowEvidenceReferenceDTO, ...]
    warnings: tuple[ApplicationCashFlowIssueDTO, ...]
    errors: tuple[ApplicationCashFlowIssueDTO, ...]
    source_lineage_references: tuple[ApplicationCashFlowLineageReferenceDTO, ...]
    cash_flow_schema_version: str
    cash_flow_model_version: str
    application_schema_version: str = "2.0.0"

class ApplicationPayloadKindV2(str, Enum):
    GENERIC_FINANCIAL = "generic_financial"
    CASH_FLOW = "cash_flow"
    ARTIFACT = "artifact"

@dataclass(frozen=True)
class ApplicationPayloadReferenceDTOV2:
    owner_type: PayloadOwnerType
    result_kind: str
    canonical_digest: str
    financial_analysis_result_id: UUID | None
    artifact_id: UUID | None
    artifact_serializer_schema_version: str | None

@dataclass(frozen=True)
class ApplicationProjectedErrorDTOV2:
    category: ExecutionCategory
    engine_code: ApplicationEngineCodeV2 | None
    cash_flow_error_code: ApplicationCashFlowErrorCodeV2 | None
    message: str
    retryable: bool
    safe_metadata: ApplicationJsonValue

@dataclass(frozen=True)
class ApplicationPayloadEnvelopeDTOV2:
    payload_reference: ApplicationPayloadReferenceDTOV2
    computation_status: FinancialComputationStatus
    source_mode: ApplicationFinancialSourceModeV2 | None
    payload_kind: ApplicationPayloadKindV2
    payload_materialized: bool
    generic_result_payload: ApplicationJsonValue | None
    cash_flow_projection: CashFlowProjectionDTOV2 | None
    structured_error: ApplicationProjectedErrorDTOV2 | None
    message: str | None
    inner_status: str | None
    trial_balance_usage: ApplicationJsonValue | None
    provenance_source_references: tuple[str, ...]
    engine_schema_version: str | None
    engine_model_version: str | None
    application_schema_version: str = "2.0.0"

@dataclass(frozen=True)
class AnalysisExecutionDTOV2:
    engine_code: ApplicationEngineCodeV2
    status: ApplicationExecutionStatus
    inner_status: str | None
    engine_schema_version: str | None
    engine_model_version: str | None
    input_fingerprint: str
    fingerprint_schema_version: str
    error: ApplicationProjectedErrorDTOV2 | None
    dependency_engine_codes: tuple[ApplicationEngineCodeV2, ...]
    payload: ApplicationPayloadEnvelopeDTOV2 | None
    reused_from_run_id: str | None
    application_schema_version: str = "2.0.0"

@dataclass(frozen=True)
class AnalysisCommandResultDTOV2:
    run_id: str
    status: ApplicationStatus
    request_fingerprint: str
    terminal_content_digest: str
    scope: ApplicationScopeDTO
    executions: tuple[AnalysisExecutionDTOV2, ...]
    persisted_at: datetime
    idempotent_replay: bool
    recovery_query_run_id: str
    application_schema_version: str = "2.0.0"

@dataclass(frozen=True)
class AnalysisRunSummaryDTOV2:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    finalized_at: datetime
    previous_run_id: str | None
    application_schema_version: str = "2.0.0"

@dataclass(frozen=True)
class AnalysisRunStatusDTOV2:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    finalized_at: datetime
    engine_statuses: tuple[tuple[ApplicationEngineCodeV2, ApplicationExecutionStatus], ...]
    terminal: bool
    application_schema_version: str = "2.0.0"

@dataclass(frozen=True)
class AnalysisResultDTOV2:
    run_id: str
    status: ApplicationStatus
    scope: ApplicationScopeDTO
    request_fingerprint: str
    executions: tuple[AnalysisExecutionDTOV2, ...]
    warnings: tuple[ApplicationJsonValue, ...]
    structured_errors: tuple[ApplicationProjectedErrorDTOV2, ...]
    execution_plan_version: str
    orchestration_schema_version: str
    orchestration_model_version: str
    finalized_at: datetime
    application_schema_version: str = "2.0.0"

@dataclass(frozen=True)
class AnalysisHistoryPageDTOV2:
    items: tuple[AnalysisRunSummaryDTOV2, ...]
    next_cursor: str | None
    application_schema_version: str = "2.0.0"

@dataclass(frozen=True)
class CancellationResultDTOV2:
    run_id: str
    status: CancellationStatus
    scope: ApplicationScopeDTO
    requested_at: datetime
    application_schema_version: str = "2.0.0"

@dataclass(frozen=True)
class AnalysisErrorDTOV2:
    code: AnalysisErrorCode
    cash_flow_error_code: ApplicationCashFlowErrorCodeV2 | None
    category: ApplicationErrorCategory
    message: str
    retryable: bool
    correlation_id: str
    safe_metadata: ApplicationJsonValue
    application_schema_version: str = "2.0.0"

@dataclass(frozen=True)
class AnalysisWarningDTOV2:
    code: ApplicationWarningCode
    message: str
    retryable: bool

@dataclass(frozen=True)
class ApplicationOutcomeV2(Generic[T]):
    success: bool
    value: T | None
    error: AnalysisErrorDTOV2 | None
    warnings: tuple[AnalysisWarningDTOV2, ...]
    correlation_id: str
    application_schema_version: str = "2.0.0"
```

Altı literal application enum manifesti bu contract'ın normatif parçasıdır: `(name,value)` çiftleri Section 7'deki `CashFlowLineCode`, `CashFlowWarningCode`, `CashFlowErrorCode`, `CashFlowAccountRole`, `CashFlowSourceRole` ve `CashFlowDerivationCode` declaration-order manifestleriyle exact eşittir; engine enum'u import/alias edilmez. Eksik/fazla/reordered member contract failure'dır. Contract golden testi iki manifestin değer eşitliğini ve type identity ayrılığını doğrular. Unknown enum value fail-closed'dur.

`ApplicationPayloadReferenceDTOV2` owner XOR'u V1 ile aynıdır. Financial owner için `financial_analysis_result_id` ve `canonical_digest` zorunlu, `artifact_id` ve `artifact_serializer_schema_version` null'dır. Artifact owner bunun tersidir ve serializer version zorunludur. `payload_kind=CASH_FLOW` yalnız `result_kind="CashFlowResult"` financial owner ile geçerlidir. `payload_materialized=True` ise Cash Flow'da yalnız `cash_flow_projection`, diğer iki kind'da yalnız `generic_result_payload` doludur; false ise ikisi de null'dır. `CashFlowProjectionDTOV2.status` yalnız ilk beş result-bearing application status olabilir; son iki değer execution error/outcome mapping içindir ve payload içinde reddedilir. Wrong-kind, çift payload veya wrong-owner projection fail-closed `DTO_PROJECTION_FAILED` outcome'udur.

Cash Flow projection `warnings` inventory'sini field-by-field korur ve V1 result invariant'ı gereği `errors=()` taşır; failure outcome `AnalysisExecutionDTOV2.error`/application error envelope'a güvenli biçimde map edilir, sahte Cash Flow payload'a dönüştürülmez. `ApplicationProjectedErrorDTOV2.cash_flow_error_code` Cash Flow typed execution error'ında zorunlu, diğer engine error'ında null'dır. `AnalysisErrorDTOV2.cash_flow_error_code` pre-run resolver veya terminal Cash Flow persistence error'ında zorunlu, unrelated application error'da null'dır. Her ikisinde code V1→V2 enum-value exact map edilir; retryable closed manifestten türetilir ve safe metadata recursive application JSON cebirine field-by-field redacted map edilir. Unknown code, raw cause veya message'dan code çıkarımı `DTO_PROJECTION_FAILED` olur.

`CashFlowProjectionDTOV2.endpoint_reconciliations` engine payload'ındaki exact iki-record tuple'ın field-by-field, ayrı application enum/type projection'ıdır; adapter yeniden endpoint hesabı yapmaz. MATCHED/not-performed status, amounts, zero/null difference ve BS evidence invariant'larından biri kaybolur veya değişirse `DTO_PROJECTION_FAILED` olur ve persisted owner geri alınmaz.

`ApplicationOutcomeV2` invariant'ı V1 ile aynıdır: success'te value zorunlu/error null, failure'da value null/error zorunlu; expected error raw exception fırlatmaz. Bu ayrı DTO'ların hiçbirinin default schema değeri V1 class'ına geri yazılmaz.

Adapter engine dataclass'ını döndürmez; field-by-field yeni DTO kurar, local JSON object'i 5.0C application JSON cebirine map eder ve durable lineage refs'i repository ile doğrular. `application_command_digest_v1()` mevcut bytes'ı korur; yeni `application_command_digest_v2()` exact v2 fields + explicit `application_contract_version` üzerinden canonicalizes. `to_orchestration_request_v3()` trusted pre-resolution sonrası V3 request kurar; mevcut `to_orchestration_request()` değişmez. V1 decoder v2'yi, v2 decoder unknown/missing field'i reddeder.

### 25.2 Cash-Flow owner assembly

5.0C-v2 phased persistence adapter'da generic Ratio fallback kullanılmaz; explicit Cash Flow branch'i yalnız result-bearing `COMPLETE_*`, `PARTIAL_*` veya `INSUFFICIENT_DATA` için şu exact owner'ı stage eder: `analysis_type=CASH_FLOW`, `source_mode=MULTI_SOURCE_DERIVED`, `document_id=None`, `status=COMPLETED`, `company_id/current_period_id` scope, `engine_version="1.0.0"`, strict codec `result_json` ve recomputed `canonical_digest`. Cash Flow typed failure taşıyan execution, technical FAILED/SKIPPED veya `PerEngineExecutionRecordV3.result is None` owner üretmez. Financial payload owner yalnız bu satırdır; artifact duplicate yoktur. Cross-period lineage yalnız yeni tabloya, owner ile aynı SAVEPOINT/terminal transaction içinde yazılır.

Existing-canonical-owner reuse ancak strict payload bytes/digest **ve** normalized exact lineage graph (base/optional role seti, source IDs, periods, type, version, digest, tenant/company/current/prior binding) birebir eşitse mümkündür. Missing/extra/different role/source/period/version/digest conflict'tir; aynı payload tek başına reuse yetkisi vermez.

### 25.3 Application-v2 port ve phased coordination topolojisi

V1 `AnalysisExecutionGatewayPort`, `AnalysisReadPort`, `RunPersistencePort`, `ApplicationTerminalPersistenceRequest` ve `AnalysisApplicationService` değişmez. Ayrı V2/V3 zinciri şöyledir:

```python
@dataclass(frozen=True)
class VerifiedTenantScopeV3:
    tenant_key: str
    tenant_id: UUID
    company_id: UUID
    initiating_subject_id: str

@dataclass(frozen=True)
class RunScopeClaimV3:
    claim_id: UUID
    run_id: str
    application_scope: ApplicationScopeDTO
    persistence_scope: PersistenceRunScopeV3
    initiating_subject_id: str
    application_command_digest: str
    status: RunScopeClaimStatus
    version: int
    claim_token: str
    persisted_run_id: UUID | None
    persisted_request_fingerprint: str | None
    persisted_terminal_content_digest: str | None
    claimed_at: datetime
    finalized_at: datetime | None

@dataclass(frozen=True)
class VerifiedApplicationScopeBindingV3:
    run_id: str
    scope: ApplicationScopeDTO
    persistence_scope: PersistenceRunScopeV3
    initiating_subject_id: str
    application_command_digest: str
    claim_id: UUID
    claim_version: int
    claim_status: RunScopeClaimStatus

class TenantScopeResolverPortV3(Protocol):
    def resolve(
        self,
        scope: ApplicationScopeDTO,
        actor: ApplicationAuditContextDTO,
    ) -> VerifiedTenantScopeV3: ...

class RunScopeClaimPortV3(Protocol):
    def claim(
        self,
        run_id: str,
        scope: ApplicationScopeDTO,
        verified_tenant: VerifiedTenantScopeV3,
        application_command_digest: str,
        claimed_at: datetime,
    ) -> RunScopeClaimV3: ...
    def verify(
        self,
        run_id: str,
        scope: ApplicationScopeDTO,
        verified_tenant: VerifiedTenantScopeV3,
        claim_token: str,
        expected_version: int,
    ) -> RunScopeClaimV3: ...
    def finalize(
        self,
        run_id: str,
        scope: ApplicationScopeDTO,
        verified_tenant: VerifiedTenantScopeV3,
        claim_token: str,
        expected_version: int,
        persisted_run: PersistedRunV3,
        finalized_at: datetime,
    ) -> RunScopeClaimV3: ...
    def load(self, run_id: str) -> RunScopeClaimV3 | None: ...

@dataclass(frozen=True)
class PlannedDocumentSourceProofV3:
    document_id: UUID
    company_id: UUID
    period_id: UUID
    document_type: str
    processing_status: str
    mime_type: str
    file_extension: str
    content_sha256: str
    byte_size: int
    immutable_storage_key_digest: str

@dataclass(frozen=True)
class PlannedSamePeriodSourceEdgeV3:
    role: AnalysisSourceRole
    source_document_id: UUID | None
    existing_source_analysis_result_id: UUID | None
    same_run_source_engine_code: ApplicationEngineCodeV2 | None
    document_proof: PlannedDocumentSourceProofV3 | None

@dataclass(frozen=True)
class PlannedCashFlowLineageEdgeV3:
    source_role: CashFlowSourceRole
    existing_source_analysis_result_id: UUID | None
    same_run_source_engine_code: ApplicationEngineCodeV2 | None
    source_period_id: UUID
    source_canonical_digest: str
    source_provenance_digest: str
    source_analysis_type: AnalysisType
    source_engine_version: str
    current_period_descriptor_digest: str
    prior_period_descriptor_digest: str | None
    comparability_proof_digest: str | None

@dataclass(frozen=True)
class ResolvedFinancialOwnerNodeV3:
    engine_code: ApplicationEngineCodeV2
    expected_existing_owner_id: UUID | None
    allow_existing_canonical_owner: bool
    create_new_owner: bool
    primary_document_id: UUID | None
    source_mode: ApplicationFinancialSourceModeV2
    same_period_lineage_plan: tuple[PlannedSamePeriodSourceEdgeV3, ...]
    cash_flow_lineage_plan: tuple[PlannedCashFlowLineageEdgeV3, ...]
    expected_canonical_result_digest: str | None
    expected_owner_content_digest: str
    expected_current_period_descriptor_digest: str | None
    expected_prior_period_descriptor_digest: str | None
    expected_comparability_proof_digest: str | None

@dataclass(frozen=True)
class ResolvedFinancialOwnershipPlanV3:
    nodes: tuple[ResolvedFinancialOwnerNodeV3, ...]
    started_at: datetime
    completed_at: datetime

@dataclass(frozen=True)
class ApplicationTerminalPersistenceRequestV3:
    verified_scope: VerifiedApplicationScopeBindingV3
    run_result: OrchestrationRunResultV3
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    resume_context: ResumePersistenceContextV3 | None
    financial_ownership_plan: ResolvedFinancialOwnershipPlanV3
    telemetry: ExecutionTelemetryV3 | None

@dataclass(frozen=True)
class TerminalPersistenceResultV3:
    persisted_run: PersistedRunV3
    idempotent_replay: bool

@dataclass(frozen=True)
class VerifiedDocumentContentProofV3:
    document_id: UUID
    content_sha256: str
    byte_size: int
    immutable_storage_key_digest: str

class ImmutableDocumentContentVerifierPortV3(Protocol):
    def read_and_verify(
        self,
        *,
        document_id: UUID,
        expected_content_sha256: str,
        expected_byte_size: int,
        expected_storage_key_digest: str,
    ) -> VerifiedDocumentContentProofV3: ...

@dataclass(frozen=True)
class InternalRunViewV3:
    persisted_run: PersistedRunV3
    status: ApplicationStatus
    requested_outputs: tuple[ApplicationEngineCodeV2, ...]
    previous_run_id: str | None

@dataclass(frozen=True)
class AuthorizedResumeSourceViewV3:
    run: InternalRunViewV3
    verified_scope: VerifiedApplicationScopeBindingV3
    payloads_materialized: bool
    snapshot_load_result: SnapshotLoadResultV3 | None

class ApplicationV2PortErrorCode(str, Enum):
    NOT_FOUND = "not_found"
    SCOPE_MISMATCH = "scope_mismatch"
    CONFLICT = "conflict"
    INTEGRITY = "integrity"
    UNAVAILABLE = "unavailable"

@final
class ApplicationV2PortError(Exception):
    # code ve stable safe_message constructor manifestinden türetilir;
    # raw cause/SQL/DSN/payload/identifier tutulmaz, class subclass edilemez.
    code: ApplicationV2PortErrorCode

class AnalysisExecutionGatewayPortV2(Protocol):
    def start(self, command: StartAnalysisCommandV2, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcomeV2[AnalysisCommandResultDTOV2]: ...
    def resume(self, command: ResumeAnalysisCommandV2, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcomeV2[AnalysisCommandResultDTOV2]: ...
    def retry(self, command: RetryAnalysisCommandV2, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcomeV2[AnalysisCommandResultDTOV2]: ...
    def cancel(self, command: CancelAnalysisCommandV2) -> ApplicationOutcomeV2[CancellationResultDTOV2]: ...

class AnalysisReadPortV2(Protocol):
    def get_run_by_id(self, run_id: str, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3) -> InternalRunViewV3 | None: ...
    def get_status(self, run_id: str, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3) -> AnalysisRunStatusDTOV2 | None: ...
    def get_result(self, run_id: str, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3, *, include_payloads: bool) -> AnalysisResultDTOV2 | None: ...
    def get_execution_detail(self, run_id: str, engine_code: ApplicationEngineCodeV2, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3, *, include_payload: bool) -> AnalysisExecutionDTOV2 | None: ...
    def list_history(self, scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3, cursor: str | None, limit: int) -> AnalysisHistoryPageDTOV2: ...
    def load_scope(self, run_id: str, verified_tenant: VerifiedTenantScopeV3) -> VerifiedApplicationScopeBindingV3 | None: ...
    def load_resume_source(self, previous_run_id: str, target_scope: ApplicationScopeDTO, verified_tenant: VerifiedTenantScopeV3, *, materialize_payloads: bool) -> AuthorizedResumeSourceViewV3: ...

class RunPersistencePortV3(Protocol):
    def persist_terminal_run(self, request: ApplicationTerminalPersistenceRequestV3) -> TerminalPersistenceResultV3: ...
    def build_previous_execution_snapshot(self, run_id: str, target_scope: PersistenceRunScopeV3) -> SnapshotLoadResultV3: ...
    def resolve_financial_ownership_plan(
        self,
        run_result: OrchestrationRunResultV3,
        source_intents: tuple[FinancialSourceIntentDTOV2, ...],
        cash_flow_request: CashFlowRequestDTOV2 | None,
        pre_resolved_context: CashFlowPreResolvedContext | None,
        verified_scope: VerifiedApplicationScopeBindingV3,
        started_at: datetime,
        completed_at: datetime,
    ) -> ResolvedFinancialOwnershipPlanV3: ...
    def resolve_payload_references(self, run_id: str, verified_scope: VerifiedApplicationScopeBindingV3, *, include_payloads: bool) -> tuple[ApplicationPayloadEnvelopeDTOV2, ...]: ...

class AnalysisApplicationServiceV2(AnalysisExecutionGatewayPortV2):
    def __init__(
        self,
        *,
        orchestrator: AnalysisOrchestratorPortV3,
        persistence: RunPersistencePortV3,
        reads: AnalysisReadPortV2,
        claims: RunScopeClaimPortV3,
        tenant_scopes: TenantScopeResolverPortV3,
        authorization: AuthorizationPort,
        security_audit: SecurityAuditPort,
        observability: ObservabilityPort,
        active_executions: ActiveExecutionPort,
        clock: ApplicationClockPort,
        cash_flow_sources: CashFlowSourceResolverPort,
        comparable_periods: ComparablePeriodResolverPort,
    ) -> None: ...
    def start(self, command: StartAnalysisCommandV2, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcomeV2[AnalysisCommandResultDTOV2]: ...
    def resume(self, command: ResumeAnalysisCommandV2, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcomeV2[AnalysisCommandResultDTOV2]: ...
    def retry(self, command: RetryAnalysisCommandV2, cancellation_probe: Callable[[], bool] | None = None) -> ApplicationOutcomeV2[AnalysisCommandResultDTOV2]: ...
    def cancel(self, command: CancelAnalysisCommandV2) -> ApplicationOutcomeV2[CancellationResultDTOV2]: ...

class AnalysisQueryServiceV2:
    def __init__(
        self,
        *,
        authorization: AuthorizationPort,
        security_audit: SecurityAuditPort,
        observability: ObservabilityPort,
        clock: ApplicationClockPort,
        tenant_scopes: TenantScopeResolverPortV3,
        reads: AnalysisReadPortV2,
    ) -> None: ...
    def get_status(self, query: GetAnalysisStatusQueryV2) -> ApplicationOutcomeV2[AnalysisRunStatusDTOV2]: ...
    def get_result(self, query: GetAnalysisResultQueryV2) -> ApplicationOutcomeV2[AnalysisResultDTOV2]: ...
    def get_execution_detail(self, query: GetExecutionDetailQueryV2) -> ApplicationOutcomeV2[AnalysisExecutionDTOV2]: ...
    def list_history(self, query: ListAnalysisHistoryQueryV2) -> ApplicationOutcomeV2[AnalysisHistoryPageDTOV2]: ...
```

`PlannedSamePeriodSourceEdgeV3` exact locator XOR'una bağlı proof invariant'ı taşır: yalnız `source_document_id` branch'inde `document_proof` zorunlu ve `document_proof.document_id == source_document_id`; diğer iki locator branch'inde null'dır. Proof caller/public command'dan gelmez. Trusted document resolver gerçek hesaplama byte'larını authoritative storage'dan okuyup SHA-256/size/type/scope doğruladıktan sonra internal planner bu immutable snapshot'ı üretir; raw bytes proof DTO'ya girmez.

Production Cash Flow V3 composition mevcut mutable ID-path store'u immutable saymaz. `ImmutableDocumentContentVerifierPortV3` yalnız finalized object'i `(document_id, content_sha256)` content-addressed key ile okuyan, overwrite/delete'i application credential düzeyinde yasaklayan write-once store adapter'ına bind edilebilir. Existing `{document_id}` yolunu checksum parametresini kullanmadan okuyan adapter Cash Flow readiness'te fail-closed'dur; legacy content kontrollü external sealing/import ile content-addressed key'e taşınmadan V3 run'a giremez. Bu dış object migration'ı DB backfill değildir ve public upload/API sözleşmesi eklemez.

Logical storage-key proof provider-neutral ve exact'tir: `immutable_storage_key_digest = sha256(b"cash-flow/document-storage-key/v1\0" + canonical_bytes(cf.document_storage_key.v1(document_id, content_sha256, byte_size))).hexdigest()`. `document_id` lowercase canonical UUID, checksum lowercase SHA-256 ve byte size non-negative integer'dır. Bucket/path/provider/region/version-ID gibi fiziksel locator metadata'sı bu digest'e girmez; iki compliant provider aynı logical tuple için aynı proof'u üretir. Actual object key adapter içinde content-addressed ve write-once'dır; overwrite/delete credential'ı production verifier/sealer'a verilmez.

Scope/type/status dahil terminal document proof'u ayrıdır: `document_source_proof_digest = sha256(b"cash-flow/document-source-proof/v1\0" + canonical_bytes(cf.document_source_proof.v1(document_id, company_id, period_id, document_type, processing_status, mime_type, file_extension, content_sha256, byte_size, immutable_storage_key_digest))).hexdigest()`. Field sırası literal bu sıradır. `processing_status` yalnız `ProcessingStatus.COMPLETED.value == "completed"` olabilir. Closed format manifesti yalnız `(".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ZIP/OOXML magic)` ve `(".pdf", "application/pdf", b"%PDF-")` rows'udur; lowercased derived extension, row MIME ve authoritative bytes magic'i aynı row'a exact uymalıdır. Document type resolver role'ünün existing 5.0D allowlist'iyle exact eşleşir. Bu digest `PlannedDocumentSourceProofV3`'ün tamamını bağlar; storage-key digest'in yerine geçmez. Scope/type/status/MIME/extension/checksum/size/key tek-field mutation'ı terminal digest ve persistence proof'unu değiştirir.

İki durable prerequisite için supported writer yolu kapalı internal administration service'idir; manual SQL, raw object copy, public API/UI, queue, scheduler veya batch runner değildir:

```python
@dataclass(frozen=True)
class RegisterCashFlowPeriodPolicyCommand:
    tenant_id: UUID
    company_id: UUID
    period_id: UUID
    accounting_basis_code: CashFlowAccountingBasisCode
    accounting_policy_version: str
    annual_reporting_period_start_date: date
    annual_reporting_period_end_date: date
    ifrs18_early_adopted: bool
    operator_subject_id: str
    correlation_id: str

@dataclass(frozen=True)
class SealCashFlowDocumentCommand:
    tenant_id: UUID
    company_id: UUID
    period_id: UUID
    document_id: UUID
    expected_content_sha256: str
    expected_byte_size: int
    operator_subject_id: str
    correlation_id: str

class CashFlowPrerequisiteAdministrationPort(Protocol):
    def register_period_policy(
        self, command: RegisterCashFlowPeriodPolicyCommand
    ) -> CashFlowPeriodDescriptor: ...
    def seal_document(
        self, command: SealCashFlowDocumentCommand
    ) -> VerifiedDocumentContentProofV3: ...
```

Production implementation `CashFlowPrerequisiteAdministrationService` + `SqlAlchemyCashFlowPrerequisiteRepository` + write-once object sealer'dır; only trusted operations composition root'ta bind edilir ve tek-record signed operational command tarafından çağrılır. Period operation Company namespace lock'u sonra period row'u aynı transaction'da okur: beş alan all-null ise exact command değerlerini yazar; zaten exact aynıysa idempotent success; partial veya farklı non-null değer varsa overwrite etmeden conflict. Document operation locked row'da tenant/company/period/type/status/checksum/size doğrular, legacy source bytes'ı bounded read ile rehash eder, deterministic content-addressed key'e stage→verify→publish eder; exact object zaten varsa idempotent success, farklı bytes/key collision veya unsealed/missing legacy content fail-closed. DB transaction object publish'ten sonra yeniden revalidate edilir; failure'da published content-addressed exact object orphan değil yeniden kullanılabilir immutable object'tir, fakat document ready sayılmaz ve proof dönmez.

Her command için internal prerequisite-authorization adapter trusted `operator_subject_id` + deployment capability'yi fail-closed doğrular. Required audit sink mutation öncesi correlation/subject/target IDs ve command digest'iyle durable `CASH_FLOW_PREREQUISITE_REQUESTED` kaydını kabul etmeden işlem başlamaz; raw document/payload yoktur. Commit/publish sonrası `..._COMPLETED` yazılamazsa canonical mutation geri alınmaz, mandatory operational alert + warning üretilir; pre-audit command digest'i işlemi izlenebilir tutar. Bu private event/port 5.0C/5.0E public enum veya `AuthorizationPort` contract'ını değiştirmez. Production readiness her eligible period metadata row'unu ve referenced document object proof'unu verifies; missing adapter, write-capable verifier credential, unsigned operation veya audit outage readiness=false/fail-closed yapar.

Terminal repository Company namespace lock'u aldıktan sonra her document edge için `financial_documents` row'unu scope/type/status/checksum/size ile tekrar çözer, verifier ile authoritative bytes'ı tekrar okuyup hashler ve row checksum + pre-run proof + immutable storage-key digest dört yönlü exact eşleşmeden binding stage etmez. Store I/O positive bounded timeout/size limitlidir; timeout `PERSISTENCE_UNAVAILABLE`, mismatch `PERSISTENCE_INTEGRITY_FAILURE` ve tüm SAVEPOINT rollback'idir. Aynı verifier load/resume/reuse yolunda rehash eder. Böylece input version A ile hesaplayıp provenance'ı mutated version B'ye bağlamak mümkün değildir; document ID/checksum tek başına content proof sayılmaz.

Portlar framework/ORM bağımsızdır. SQLAlchemy yalnız `RunStorePortV3`, `SnapshotReaderPortV3`, `RunPersistencePortV3`, V3 claim/tenant-scope/source/read adapter implementasyonlarında bulunur. `ApplicationScopeDTO.tenant_id` external tenant key `str | None` olarak donmuş kalır; `TenantScopeResolverPortV3` production'da non-null active key'i authoritative 5.0E tenant UUID'sine çözer, `Company.tenant_id` ile exact karşılaştırır ve trusted subject'i `ApplicationAuditContextDTO.actor_id` ile bağlar. Null, inactive, ambiguous, subject mismatch veya company mismatch `SCOPE_MISMATCH`, retryable false ve fail-closed'dur. V1 scope'a UUID yazılmaz; V3 persistence'a string tenant key geçirilmez. V2 service 5.0E `AuthorizationPort`, audit/observability/clock/active-execution portlarını mevcut semantiğiyle kullanır; public imzalarını değiştirmez. Ayrı V3 claim portu yalnız yeni contract tiplerini kabul eder. Application service transaction açmaz; owner/lineage/terminal atomik transaction'ı V3 persistence adapter'ındadır, V3 scope claim çağrıları mevcut kısa-transaction topolojisini korur.

V2 port exception sözleşmesi exhaustivedir. `AnalysisReadPortV2` yalnız gerçek scope-qualified miss için `None`; timeout/DB outage için `ApplicationV2PortError(UNAVAILABLE)`, digest/duplicate/relational ihlal için `INTEGRITY`, verified tenant/scope farkı için `SCOPE_MISMATCH` üretir. `RunPersistencePortV3` ve source resolver'ların **Cash Flow dışı** unique/fingerprint/store/scope problemleri generic `ApplicationV2PortError` taxonomy'sini kullanır; Cash Flow owner/lineage/document/period/provenance branch'leri Section 28 exact `CashFlowPortError(CashFlowErrorCode)` union'unu kullanır. Application service önce typed Cash Flow port error'unu, sonra generic port error'u normalize eder; bu sıra code kaybını veya generic `INTEGRITY`'ye çökmesini engeller. Tenant/claim/read adapter'ları generic taxonomy'de kalır. Unknown/raw exception service boundary'de `INTERNAL_INVARIANT_BREACH` olur; hiçbir port raw ORM/driver exception'ı, HTTP status'u veya caller-controlled retry flag'i taşımaz. Her port call positive bounded timeout'a tabidir, implicit retry yoktur. Transaction ownership: tenant/read/claim her çağrıda ayrı kısa read/CAS transaction; terminal store tek explicit transaction + nested SAVEPOINT; pure orchestrator ve application service transaction açmaz. Cancellation probe yalnız orchestrator run süresince ileri taşınır, port I/O'yu interrupt veya rollback garantisi vermez.

`RunScopeClaimV3`, 5.0C kararıyla aynı şekilde yalnız immutable run-ownership reservation/CAS projection'ıdır; workflow state, running job, scheduler, durable active-execution registry veya event-sourcing kaydı değildir. `CLAIMED` engine'in çalıştığını, `FINALIZED` background işin bittiğini ifade etmez. Process-local `ActiveExecutionPort` yalnız cancellation/diagnostics içindir ve claim/idempotency correctness kaynağı olamaz.

Exact phased akış:

1. V2 command shape/scope/digest doğrulaması, required security audit, authorization ve durable scope claim/preflight yapılır.
2. Aynı `run_id` V3 persisted ise scope + command digest + request fingerprint doğrulanır; exact replay read/projection'a gider. V2 persisted run veya farklı scope/digest fail-closed conflict'tir.
3. Resume/Retry'da source authorization'dan sonra yalnız V3 snapshot/context yüklenir; V2 source veya corrupt lineage clean-start'a düşmez.
4. Cash Flow requested ise trusted comparable-period/source resolution ile pre-resolved context kurulur; public intent'ten owner/lineage alınmaz.
5. Değişmemiş V3 orchestrator contract'ı `run_orchestration_v3()` ile senkron çalıştırılır.
6. Pre-persistence authorization revalidation yapılır; revoke/deny halinde terminal persistence ve projection yapılmaz.
7. `resolve_financial_ownership_plan()` gerçek execution record/envelope'larını inceler. Envelope taşıyan BS/IS domain outcome'u `result_json=None` olsa bile donmuş 5.0A semantiğiyle owner node üretir; bu durumda canonical-result digest null, owner-content digest zorunludur ve Cash Flow builder usable current snapshot yerine missing diagnostic görür. Non-null BS/IS/Ratio payload için V2 source intent'i, Cash Flow için strict result + trusted context kullanılır. Technical execution `FAILED/SKIPPED`, `record.result is None` veya Cash Flow failure outcome için node yoktur.
8. Owner sırası BS → IS → Cash Flow → Ratio'dur. Plan edge'leri tam bir locator XOR taşır: same-period edge'te `source_document_id XOR existing_source_analysis_result_id XOR same_run_source_engine_code`, Cash Flow edge'te `existing_source_analysis_result_id XOR same_run_source_engine_code`. Terminal adapter her node stage/reuse edildikçe `(engine_code → canonical owner UUID)` map'ini kurar; sonraki node'un same-run locator'ını bu map ile çözüp yalnız bundan sonra low-level `FinancialResultSourceBindingV3`/`CashFlowLineageBindingV3` üretir. Yeni same-run BS/IS owner ID'leri Cash Flow lineage'ına bağlanır. Cash Flow+Ratio requested ve CF owner result-bearing ise planner tek fixed `SUPPORTING_ANALYSIS(CASH_FLOW)` edge'ini kendisi inject eder ve gerçek Cash Flow owner ID'sini Ratio'ya aynı terminal transaction'da çözer; CF owner yoksa bu edge yoktur ve caller edge'iyle fallback yasaktır. Missing/duplicate/wrong-order locator `PERSISTENCE_INTEGRITY_ERROR` ve SAVEPOINT rollback'tir; caller hiçbir FK veya role assembly seçmez.
9. V3 persistence adapter terminal command'ı kurup Section 22.3 SAVEPOINT/atomic transaction kuralıyla yazar. Dönen scope/fingerprint/contract tekrar doğrulanır.
10. Claim finalize edilir; sonra DTO projection yapılır. Projection failure persisted V3 run'ı geri almaz ve V2 recovery hint verir; aynı command tekrarında orchestration çalışmadan persisted run okunur.

5.0B'nin mevcut one-shot `execute_and_persist(...)` yolu bu V3 application service'in entegrasyon yolu değildir. V1/V3 port veya DTO nesnelerini duck-type/cast ederek karıştırmak yasaktır ve contract golden testinde fail-closed doğrulanır.

Cancel ve query davranışı da kapalıdır. `cancel()` önce tenant/scope mapping, required audit ve `authorize_cancel` yapar; yalnız process-local `ActiveExecutionPort.request_cancel` sonucunu `ACCEPTED|ALREADY_REQUESTED|NOT_ACTIVE` normal `CancellationResultDTOV2` olarak döndürür. Durable terminal run varsa `ALREADY_TERMINAL`, scope-qualified read gerçekten yoksa `NOT_FOUND` normal result'tır. Cancellation idempotency/owner persistence kaynağı değildir. Dört query method'u sırasıyla tenant mapping → required audit → `authorize_read` → scope-qualified V3 read → DTO projection yapar; wrong-scope/subject result hiçbir DTO'ya map edilmez. History gerçek `HISTORY_READ`, diğerleri `RESULT_READ` audit event'ini kullanır.

Application-v2 closed error/port decision table:

| Source/port durumu | `AnalysisErrorCode` | retryable | Davranış |
|---|---|---:|---|
| command/query shape veya V2 manifest ihlali | `INVALID_COMMAND` / `INVALID_QUERY` | false | başlamadan fail-closed |
| tenant key missing/inactive/ambiguous, company/period/subject mismatch | `SCOPE_MISMATCH` | false | hiçbir read/execution/persistence yok |
| authorization deny / pre-persist revoke | `UNAUTHORIZED` / `AUTHORIZATION_REVOKED` | false | required audit; payload dışarı çıkmaz |
| `authorize_resume_source` deny | `RESUME_SOURCE_UNAUTHORIZED` | false | source materialize edilmez; clean-start yok; required audit |
| authorization provider timeout/outage | `AUTHORIZATION_PROVIDER_UNAVAILABLE` | true | fail-closed |
| required pre-event audit outage | `SECURITY_AUDIT_FAILED` | true | use-case başlamaz |
| V2/unknown-major resume source | `RESUME_SOURCE_INVALID` | false | clean-start yok |
| source owner/lineage/period proof/digest corruption | `RESUME_SOURCE_CORRUPTED` | false | clean-start yok |
| source-read/period-resolver DB timeout, unavailable, pool exhaustion | `PERSISTENCE_UNAVAILABLE` | true | engine çağrılmaz |
| same run/scope fakat farklı fingerprint | `FINGERPRINT_CONFLICT` | false | fail-closed |
| same run farklı tenant/company/period/subject | `RUN_ID_CONFLICT` | false | wrong-scope result gizlenir |
| claim CAS/uniqueness conflict | `SCOPE_CLAIM_CONFLICT` | false | execution correctness claim'e bağlanmaz; sonuç yok |
| claim store timeout/outage | `SCOPE_CLAIM_UNAVAILABLE` | true | execution başlamaz |
| pure orchestrator typed Cash Flow failure taşıyan valid terminal result | application error yok | code manifestine göre | owner yok; algorithm-derived run status ile persist/finalize ve success command DTO |
| orchestrator port unexpected exception/invalid return | `EXECUTION_FAILED` | false | raw exception redacted; terminal result/persistence yok |
| terminal unique/fingerprint conflict | `PERSISTENCE_CONFLICT` | false | exact winner değilse ret |
| owner/lineage/period proof/constraint integrity ihlali | `PERSISTENCE_INTEGRITY_ERROR` | false | SAVEPOINT + terminal transaction rollback |
| terminal/read store timeout/outage | `PERSISTENCE_UNAVAILABLE` | true | fail-closed |
| true scope-qualified read miss | `NOT_FOUND` | false | outage ile karıştırılmaz |
| terminal commit sonrası DTO projection/serialization | `DTO_PROJECTION_FAILED` | false | persisted run korunur; safe run-id recovery hint |
| claim finalize failure after commit | `SCOPE_FINALIZATION_FAILED` | true | persisted run korunur; projection yapılmaz |
| programmer invariant breach | `INTERNAL_INVARIANT_BREACH` | false | safe generic envelope; raw cause yok |

Portların hiçbiri implicit retry yapmaz. `retryable` yalnız bu tablodan türetilir. Authorization/audit/scope/integrity portları fail-closed; observability fail-open best-effort'tur. Post-commit security-audit outage canonical run'ı geri almaz ve mevcut `SECURITY_AUDIT_POST_COMMIT_FAILED` warning'iyle success'i korur. Port timeout'ları pozitif bounded config'dir; timeout exception'ı public boundary'ye çıkmaz. `ApplicationPayloadReferenceDTOV2.canonical_digest`, donmuş 5.0C public semantiğini korur: financial owner için execution'ın full-semantic `owner_content_digest` değeridir; yalnız `FinancialAnalysisResult.canonical_result_digest` değildir. Böylece BS/IS `result_json=None` domain outcome'u da doğrulanabilir reference alabilir. Cash Flow read adapter önce strict result payload'ını `canonical_result_digest` ile, sonra execution/owner semantic projection'ını `owner_content_digest` ile doğrular ve DTO alanına ikincisini koyar. Artifact branch'inde alan artifact content digest'idir. İki financial digest birbirinin yerine doğrulanmaz.

## 26. Ratio Integration

Mevcut altı formül ve metadata yeniden yazılmaz:

- operating cash-flow margin;
- free cash-flow margin;
- cash flow to debt;
- cash return on assets;
- cash interest coverage;
- operating cash-flow ratio.

Mevcut `analyze_financial_ratios(...)` fonksiyonu ve 5.0A dispatch imzası byte/source compatible kalır; bu fonksiyona `cash_flow_result` parametresi eklenmez. Additive V3 yolu ayrı adapter'dır:

```python
def analyze_financial_ratios_v3(
    *,
    balance_sheet_result: OrchestrationJsonObjectV3 | None,
    income_statement_result: OrchestrationJsonObjectV3 | None,
    prior_period_balance_sheet_result: OrchestrationJsonObjectV3 | None = None,
    prior_period_income_statement_result: OrchestrationJsonObjectV3 | None = None,
    period_start_date: date | None = None,
    period_end_date: date | None = None,
    period_months_covered: int | None = None,
    cash_flow_result: CashFlowResult | None = None,
) -> OrchestrationJsonObjectV3: ...
```

Adapter önce strict V3 objects'i frozen legacy input projection'ına map edip mevcut `analyze_financial_ratios(...)` fonksiyonunu değişmeden çağırır. `cash_flow_result is None` ise dönen legacy projection byte-for-byte korunur. Result varsa exact frozen overlay contract'ı şudur:

```python
@dataclass(frozen=True)
class CashFlowRatioFactsV1:
    operating_cash_flow: Decimal | None
    free_cash_flow: Decimal | None
    net_sales: Decimal | None
    total_liabilities: Decimal | None
    average_total_assets: Decimal | None
    financing_expenses: Decimal | None
    short_term_liabilities: Decimal | None
```

İlk iki alan yalnız strict `CashFlowResult` özet projection'ından gelir. Diğer beş alan adapter'ın mevcut `_build_facts_dict(...)` yolunu aynı current/prior BS, current IS ve period metadata ile bir kez çalıştırmasından alınır; wrapper `total_liabilities` veya `average_total_assets` formülünü yeniden üretmez. Bu exact key seti mevcut registry ile birebirdir: margin'ler `net_sales`, debt `total_liabilities`, return-on-assets `average_total_assets`, interest coverage mevcut accrual-basis `financing_expenses`, OCF ratio `short_term_liabilities` kullanır. `authoritative_interest_paid`, `current_liabilities`, `total_debt` veya raw `total_assets` adında alias/fallback yoktur; cash-interest-coverage formülünün mevcut accrual denominator semantiği bu milestone'da değiştirilmez.

Adapter yalnız existing six cash-flow keys için bu yedi fact'i mevcut `RATIO_REGISTRY`/`compute_registered_ratio()` fonksiyonuna verir ve legacy `cash_flow` category projection'ını replace eder; formül kopyalanmaz, diğer kategori/metadata/score digest'i değişmez. Strict result-bearing status, TRY/scale-2 ve OCF/FCF field-evidence parity guard'ı geçmeden overlay kurulmaz. V3 orchestrator yalnız bu wrapper'ı V3 Ratio node'unda çağırır; V2 node legacy fonksiyonu çağırmaya devam eder.

Additive v3 mapping:

| Durum | Davranış |
|---|---|
| Cash-flow execution yok | mevcut `ENGINE_DEPENDENCY_NOT_AVAILABLE` |
| Cash-flow sonucu var, gereken field `None` | normal `MISSING_INPUT/NOT_CALCULABLE` |
| Field kanıtlı | mevcut formula registry normal çalışır |

Formüller cash-flow engine içine kopyalanmaz. `cash_interest_coverage` mevcut contract gereği denominator olarak accrual `financing_expenses` kullanır; bu oran gerçek cash-interest-paid coverage diye sunulmaz ve provenance bunu açıkça belirtir.

Cash-flow category/ratio entry'leri health/credit score registry'lerine hiç eklenmez; dolayısıyla “%0 ağırlıklı yeni kategori” de yaratılmaz. Mevcut score/benchmark/threshold manifests ve digest'leri byte-for-byte değişmeden kalır. Score entegrasyonu ayrı onaylı future milestone'dur.

Ratio financial owner lineage'ına Cash Flow yalnız gerçek payload owner üretmişse supporting same-run source olarak eklenir.

## 27. Executive Report Integration

Yeni section eklenmez. Mevcut `SEC_FINANCIAL_STATEMENTS_SUMMARY`, cash-flow mevcutsa optional projection alır. Registry'nin 18 section şekli korunur.

Projection yalnız upstream `CashFlowResult`'tan şunları okur:

- operating/investing/financing cash flow;
- free cash flow;
- opening/closing cash;
- reconciliation status/difference;
- evidence kind ve completeness;
- warning inventory.
- opening/closing restricted-cash availability observations.

Report hiçbir cash-flow hesabını yeniden yapmaz. `PARTIAL_*` veya `INSUFFICIENT_DATA` complete gibi sunulmaz.

Registry/version selection iki ayrı immutable path'tir. `REPORT_REGISTRY_V1` mevcut constants, 18-section registry, source inventory, schema/model `1.0.0` ve fingerprint projection'ını byte-for-byte korur; Cash Flow requested değilse yalnız bu path kullanılır. `REPORT_REGISTRY_V1_1_CASH_FLOW` ayrı literal 18-section manifestidir; Cash Flow requested olduğunda (payload result, insufficient veya no-result sentinel fark etmeksizin) seçilir, mevcut summary section'a optional cash-flow projection/status ekler ve schema/model `1.1.0` üretir. Global registry veya v1 source-engine inventory runtime'da mutate edilmez. V1 ve v1.1 fingerprints Section 24.5 branch kurallarını izler; absent Cash Flow v1 payload'a null/default field eklemez.

## 28. Port ve Katman Sınırları

```python
class ComparablePeriodResolutionStatus(str, Enum):
    EXACT_MATCH = "exact_match"
    NO_MATCH = "no_match"

@dataclass(frozen=True)
class ComparablePeriodResolution:
    status: ComparablePeriodResolutionStatus
    current_period: CashFlowPeriodDescriptor
    prior_period: CashFlowPeriodDescriptor | None
    comparability_proof_digest: str | None
    candidate_count: int

@dataclass(frozen=True)
class ResolvedCashFlowPreRunSources:
    prior_balance_sheet: CashFlowSourceSnapshot | None
    current_trial_balance: CashFlowSourceSnapshot | None
    prior_trial_balance: CashFlowSourceSnapshot | None
    account_evidence: tuple[CashFlowAccountEvidence, ...]
    noncash_bridge_components: tuple[CashFlowNonCashBridgeComponent, ...]
    pre_resolved_evidence_bundle_digest: str
    source_candidate_set_digest: str
    opening_account_coverage_complete: bool
    closing_account_coverage_complete: bool

@dataclass(frozen=True)
class ResolvedCashFlowLineageEdge:
    source_role: CashFlowSourceRole
    source_analysis_result_id: UUID
    source_period_id: UUID
    source_canonical_digest: str
    source_provenance_digest: str
    source_analysis_type: AnalysisType
    source_engine_version: str
    current_period_descriptor_digest: str
    prior_period_descriptor_digest: str | None
    comparability_proof_digest: str | None

@final
class CashFlowPortError(Exception):
    __slots__ = ("_code",)
    def __init__(self, code: CashFlowErrorCode) -> None: ...
    @property
    def code(self) -> CashFlowErrorCode: ...
    @property
    def safe_message(self) -> str: ...
    @property
    def retryable(self) -> bool: ...
    def __str__(self) -> str: ...
    def __repr__(self) -> str: ...

# Constructor manifest: resolver timeout/DB unavailable/pool exhaustion ->
# SOURCE_RESOLUTION_UNAVAILABLE, retryable=True; terminal store equivalents ->
# PERSISTENCE_UNAVAILABLE, retryable=True; integrity/contract codes -> retryable=False.
# __init__ yalnız code kabul eder. Safe message/code/retryable closed manifestten
# türetilir; raw cause, SQL, DSN, payload ve identifier str/repr/state'e alınmaz.

class ComparablePeriodResolverPort(Protocol):
    def resolve_exact_prior_period(
        self,
        *,
        tenant_id: UUID,
        company_id: UUID,
        current_period_id: UUID,
        required_currency_code: str,
        accounting_basis_code: str,
        accounting_policy_version: str,
    ) -> ComparablePeriodResolution: ...

class CashFlowSourceResolverPort(Protocol):
    def resolve_pre_run_sources(
        self,
        *,
        tenant_id: UUID,
        company_id: UUID,
        current_period_id: UUID,
        prior_period_id: UUID | None,
    ) -> ResolvedCashFlowPreRunSources: ...

# Production source selection is repository-owned; caller source owner seçmez.
# Her role için candidate cardinality aşağıdaki exact manifestle çözülür.

class CashFlowLineageRepositoryPort(Protocol):
    def stage_exact_lineage(
        self,
        *,
        cash_flow_owner_id: UUID,
        tenant_id: UUID,
        company_id: UUID,
        current_period_id: UUID,
        prior_period_id: UUID | None,
        cash_flow_status: CashFlowResultBearingStatus,
        lineage: tuple[ResolvedCashFlowLineageEdge, ...],
    ) -> None: ...

class CashFlowEnginePort(Protocol):
    def analyze(
        self,
        *,
        inputs: IndirectCashFlowInput,
    ) -> CashFlowEngineOutcome: ...

def build_indirect_cash_flow_input(
    *,
    pre_resolved: CashFlowPreResolvedContext,
    current_balance_sheet_envelope: "EngineResultEnvelopeV3 | None",
    current_income_statement_envelope: "EngineResultEnvelopeV3 | None",
) -> IndirectCashFlowInput: ...
```

Port exception ownership manifesti kapalıdır; “aynı taxonomy” ifadesi exact Cash Flow code'unu düşürme yetkisi vermez:

| Port/method | Typed expected exceptions |
|---|---|
| `ComparablePeriodResolverPort.resolve_exact_prior_period` | resolver-origin `CashFlowPortError(PERIOD_NOT_COMPARABLE|PERIOD_SELECTION_AMBIGUOUS|POLICY_VERSION_UNSUPPORTED|SOURCE_RESOLUTION_UNAVAILABLE)` |
| `CashFlowSourceResolverPort.resolve_pre_run_sources` | resolver-origin `CashFlowPortError(SOURCE_NOT_FOUND|SOURCE_SCOPE_MISMATCH|SOURCE_STATUS_INVALID|SOURCE_DIGEST_MISMATCH|SOURCE_CURRENCY_MISMATCH|SOURCE_EVIDENCE_CONFLICT|POLICY_VERSION_UNSUPPORTED|SOURCE_RESOLUTION_UNAVAILABLE)` |
| `CashFlowLineageRepositoryPort.stage_exact_lineage` | `CashFlowPortError(PERSISTENCE_INTEGRITY_FAILURE|PERSISTENCE_UNAVAILABLE)`; commit/rollback yapmaz |
| `RunPersistencePortV3.resolve_financial_ownership_plan` | Cash Flow branch'inde resolver/validation-origin `CashFlowPortError`; Cash Flow dışı generic problemde `ApplicationV2PortError` |
| `RunPersistencePortV3.persist_terminal_run` | Cash Flow owner/lineage/document branch'inde `CashFlowPortError(PERSISTENCE_INTEGRITY_FAILURE|PERSISTENCE_UNAVAILABLE)`; run-id/scope/generic store probleminde `ApplicationV2PortError` |
| `RunPersistencePortV3.build_previous_execution_snapshot/resolve_payload_references` | Cash Flow payload/lineage/proof corruption'da `CashFlowPortError(PERSISTENCE_INTEGRITY_FAILURE)`; Cash Flow store outage'da `PERSISTENCE_UNAVAILABLE`; unrelated generic problemde `ApplicationV2PortError` |

Application service önce `CashFlowPortError`'ı catch eder ve exact enum value'yu `ApplicationCashFlowErrorCodeV2`'ye map ederek `AnalysisErrorDTOV2.cash_flow_error_code` alanına yazar; sonra generic `ApplicationV2PortError`'ı işler. Unknown exception iki taxonomy'den birine cast edilmez ve `INTERNAL_INVARIANT_BREACH` olur. Aynı failure iki exception olarak wrap edilmez; raw `__cause__` public error state'e taşınmaz.

Pre-run source selection caller-controlled değildir. `CASH_FLOW_SOURCE_CANDIDATE_MANIFEST_V1` üç exact row taşır: `PRIOR_BALANCE_SHEET → (prior_period_id, AnalysisType.BALANCE_SHEET, {DIRECT_DOCUMENT, TRIAL_BALANCE_DERIVED})`; `CURRENT_TRIAL_BALANCE → (current_period_id, AnalysisType.TRIAL_BALANCE, {DIRECT_DOCUMENT, MULTI_SOURCE_DERIVED})`; `PRIOR_TRIAL_BALANCE → (prior_period_id, AnalysisType.TRIAL_BALANCE, {DIRECT_DOCUMENT, MULTI_SOURCE_DERIVED})`. Eligible candidate aynı tenant/company/exact period'da, `status=COMPLETED`, non-null result payload, null error, supported engine version/source mode ve strict payload/provenance rehash'i geçen owner'dır; quarantined document, wrong basis/currency/unit veya incomplete account coverage eligible değildir. Her role için candidate tuple `(analysis_result_id, canonical_result_digest, source_provenance_digest, engine_version, source_mode.value)` UUID sırasına konur. `source_candidate_set_digest = sha256(b"cash-flow/source-candidate-set/v1\0" + canonical_bytes(cf.source_candidate_set.v1(exact role-order candidate tuples))).hexdigest()` olur. Cardinality 0 selected source'u null yapar ve minimum-data yolu `INSUFFICIENT_DATA` üretir; 1 exact owner'ı seçer; >1 latest/first/timestamp tie-break uygulamadan `SOURCE_EVIDENCE_CONFLICT` ile pre-run fail-closed olur. `SOURCE_NOT_FOUND` yalnız daha önce proof'a bağlanmış explicit source/document locator terminal/read aşamasında artık çözülemiyorsa kullanılır; candidate-set 0 ile karıştırılmaz. Prior period yoksa iki prior role'ün candidate tuple'ı exact empty'dir. Terminal transaction Company namespace lock'u altında bütün role candidate query'lerini yeniden çalıştırır; IDs/digest ve candidate-set digest pre-run snapshot'la exact eşleşmeden owner stage edilmez. Candidate insert/delete/update phantom'ı namespace trigger'larıyla serialize olur.

`CURRENT_FS_PROJECTION_MANIFEST_V1` gerçek 5.0A outcome field'lerine pinlenir. BS `result_json` içinden yalnız `cash_and_equivalents, inventory, trade_receivables, trade_payables` ve mevcut aggregate balance fields; IS içinden yalnız `net_profit, depreciation_and_amortization` doğrudan okunabilir. `financing_expenses` dedicated interest değildir; `profit_before_tax-net_profit` current tax değildir; interest/tax/dividend/disposal/revaluation/FX/lease component'i bu alanlardan türetilemez. Missing/null field `UNKNOWN/None` olur, sıfır olmaz. `net_profit` statement line evidence'ına, aggregate depreciation OCF non-cash adjustment evidence'ına dönüşebilir. Aggregate depreciation account-family allocation kanıtı taşımadığı için tek başına investing residual bridge component'i üretmez.

Builder merge algoritması exact'tir:

1. Her envelope için `engine_code`, `result_kind`, outcome status/source mode, `result_json`, trial-balance usage, engine schema/model version ve owner-codec digest domain'i doğrulanır.
2. Manifestteki supported fields field-by-field immutable snapshot/line evidence'ına çevrilir; raw mapping veya ad/name heuristic kullanılmaz.
3. Her selected account observation'ının exact disposition'ı ve varsa family code/member/reference digest'i mapping registry + authoritative proof ile doğrulanır. Missing/duplicate disposition, cross-period family mismatch veya non-zero unresolved davranışı Section 10 fail-closed kurallarına bağlanır.
4. Current TB/equivalent trusted pre-resolved `noncash_bridge_components` canonical tuple'ı korunur. Same-run outcome'dan ancak manifestte account-family-attributed explicit component varsa aynı DTO formunda yeni component yaratılabilir; V1 mevcut FS manifestinde böyle bir field yoktur, dolayısıyla aggregate değerden family component fabrication yoktur.
5. Pre-resolved ve varsa future version-pinned same-run tuple'ları `(domain, account_family_code, account_family_reference_digest, bridge_kind)` anahtarıyla canonical merge edilir. Duplicate, overwrite veya farklı basis/amount/digest/proof `SOURCE_EVIDENCE_CONFLICT` failure'dır; “son yazan kazanır” yoktur.
6. Her closed bridge category için eksik component explicit `UNKNOWN/None/UNAVAILABLE` component'e tamamlanır. Transfer/disposal proof ve exact-one dedup invariant'ları çalıştırılır; family residual yalnız Section 10 complete family balance'ından üretilebilir.
7. Strict cash policy current/prior account evidence'dan iki endpoint'i üretir; prior/current BS frozen `cash_and_equivalents` projection'larıyla Section 8 exact parity kapısı uygulanır. Non-null mismatch result'a/reconciliation'a taşınmaz, `SOURCE_EVIDENCE_CONFLICT` olur.
8. Final account evidence + bridge component tuple'ı canonical sıraya konur ve ortak `account_evidence_bundle_digest` yeniden hesaplanır; pre-run digest bu final digest yerine kullanılamaz. Endpoint records final result codec'ine ayrı exact projection olarak girer.

Golden tests supported same-run field projection'ını, aggregate depreciation'ın OCF'ye girip investing family bridge'i yaratmamasını, trusted family component preservation'ını, gross/contra family balance'ını, exhaustive account disposition'ı, BS↔policy endpoint parity'sini, missing→UNKNOWN davranışını, duplicate/conflict rejection'ı ve final bundle digest'i kilitler.

- Resolver/repository SQLAlchemy adapter'ları application/persistence boundary'de kalır.
- Engine port implementation saf ve senkrondur.
- Source resolver her row'u authoritative source payload ve digest'ten üretir; caller-supplied account evidence kabul edilmez.
- Source resolver current same-run BS/IS üretmez ve taklit etmez; yalnız pre-run prior/TB/evidence çözer. Saf builder envelope'lardaki gerçek `EngineResultEnvelopeV3.result` alanını authoritative v3 codec ile snapshot'a dönüştürür; raw mapping/locator alias kullanmaz.
- Comparable/source adapter DB timeout, connection unavailable veya pool exhaustion durumunu exact `CashFlowPortError(SOURCE_RESOLUTION_UNAVAILABLE, retryable=True)` olarak normalize eder. Terminal persistence adapter aynı infrastructure sınıfını `PERSISTENCE_UNAVAILABLE, retryable=True` yapar. Constraint/digest/relational ihlal `PERSISTENCE_INTEGRITY_FAILURE, retryable=False`; invalid source content kendi kapalı source code'u ve `retryable=False` ile döner. Raw exception/cause/SQL/DSN dışarı çıkmaz; port implementasyonu sınırsız veya implicit retry yapmaz.
- Application/orchestration boundary typed port error'u fake result veya synthetic terminal run'a çevirmez: source-resolution outage Cash Flow/orchestrator çalıştırılmadan exact `SOURCE_RESOLUTION_UNAVAILABLE` taşıyan application failure outcome; terminal-store outage commit olmadan exact `PERSISTENCE_UNAVAILABLE` application failure outcome olur. Yalnız saf engine/builder typed failure'ı FAILED execution'lı valid terminal run üretir. Retryability yalnız kapalı origin manifestinden türetilir, caller tarafından değiştirilemez.
- Transaction ownership terminal persistence service'indedir; pure engine transaction açmaz.
- `ComparablePeriodResolution.EXACT_MATCH` için `candidate_count=1`, prior/proof zorunlu; `NO_MATCH` için `candidate_count=0`, prior/proof null. Birden fazla aday result olarak dönmez, typed `PERIOD_SELECTION_AMBIGUOUS` error'dur.
- `stage_exact_lineage` commit/rollback yapmaz; caller'ın açık terminal transaction'ı ve nested SAVEPOINT'i içinde çalışır. COMPLETE/PARTIAL status'ta exact base role setini, INSUFFICIENT'da yalnız doğrulanmış subset/empty set'i kabul eder. Scope/role/type/period/digest/version mismatch `PERSISTENCE_INTEGRITY_FAILURE` olur ve hiçbir row stage edilmez.

## 29. Determinizm, Decimal ve Monetary Normalization

- V1 closed monetary manifesti `CASH_FLOW_CURRENCY_SCALE_REGISTRY_V1 = {"TRY": 2}` ve `CASH_FLOW_MONETARY_UNIT_MULTIPLIER_V1 = Decimal("1")` değerleridir. Currency authority locked `Company.currency`, unit authority bu policy sabitidir. Company currency başka bir değer, source currency başka bir değer veya multiplier `Decimal("1")` dışında ise `POLICY_VERSION_UNSUPPORTED`/`SOURCE_CURRENCY_MISMATCH` ile fail-closed olur; caller/payload override ve sessiz default yoktur.
- Input ve output `currency_code` taşır.
- Bütün arithmetic yalnız normalized functional-currency monetary leaf'lerden yapılır: account evidence'ın `normalized_functional_currency_*` alanları, bridge component'ın normalized `signed_residual_adjustment` alanı ve same-run FS için `CURRENT_FS_MONETARY_PROJECTION_V1.normalized_amount`. Trusted resolver/builder `Decimal("1")` sabitini materialize eder; current/prior/same-run source multiplier semantics birebir aynıdır. Source-side `source_*` alanları yalnız audit/integrity karşılaştırmasıdır ve formüle doğrudan giremez.
- TRY source'ta normalized alanlar source amount'a exact eşittir ve translation proof null'dır. Foreign-currency source, translation proof veya presentation-unit scaling V1'de kabul edilmez; sonraki schema/model version olmadan engine amount çeviremez.
- Engine ambient Decimal context'e güvenmez; intermediate monetary arithmetic local context'i `precision=64`, `ROUND_HALF_EVEN`, finite-only ve `InvalidOperation/Overflow/Inexact/Rounded` trap'leriyle kullanılır. Böylece çok-satırlı aggregation sessiz precision kaybetmez. Yalnız iki explicit finalization context'i beklenen `Inexact/Rounded` sinyallerine izin verir: TRY monetary leaf'leri için scale-2 quantize ve completeness ratio için scale-4 quantize; bu context'lerde de `InvalidOperation/Overflow` trap'leri açık kalır.
- Kabul edilen canonical amount magnitude `abs(value) < 10**28`, scale en fazla 8 decimal'dır; aşımı `DECIMAL_NON_FINITE_OR_SCALE_INVALID`.
- Intermediate hesaplarda quantize yapılmaz. Finalization'da canonical monetary leaves TRY minor-unit scale 2'ye `ROUND_HALF_EVEN` ile tam bir kez quantize edilir. Presentation contributor için canonical leaves activity allocation amount'larıdır: her authoritative allocation ayrı quantize edilir, `CashFlowLineItem.canonical_amount` bu quantized allocation'ların exact toplamıdır ve ayrıca quantize edilmez. Tek-activity contributor aynı kuralın tek elemanlı halidir. Bir authoritative pre-quantize total verilmişse allocation raw toplamıyla exact eşleşmek zorundadır; mismatch integrity failure'dır. Quantized total ayrı hesaplanıp residual cent dağıtılmaz. Allocation'sız opening/closing/component leaf'leri doğrudan quantize edilir. Sonra bütün subtotals, FCF, balance-sheet delta, calculated net change, tolerance ve reconciliation difference yalnız bu quantized leaves'den yeniden hesaplanır; hiçbir aggregate bağımsız quantize edilmez.
- Persisted result'taki bütün parasal alanlar scale 2'dir. Constructor ve strict codec, serialization round-trip sonrasında `closing-opening`, allocation sum, subtotal ve reconciliation identity'lerini exact doğrular; presentation-only ayrıca yuvarlama yapamaz.
- Completeness ratio 4 decimal scale'dır.
- JSON float'tan gelen kaynak değer yalnız canonical source codec'in exact decimal text representation'ı üzerinden `Decimal`'a çevrilir; binary float arithmetic yapılmaz.
- Mevcut reconciliation helper'ın threshold sabitleri yeniden kullanılabilir; Decimal→float serializer'ı cash-flow contract'ında kullanılamaz.

## 30. Güvenlik ve Hassas Veri

- Tenant/company/period/source scope her resolver ve persistence aşamasında doğrulanır.
- Source digest constant-time karşılaştırılır.
- Raw document, account name, bank account number, customer/vendor identity, token/claim veya SQL public DTO'ya taşınmaz.
- Account code yalnız gerekli provenance alanında taşınır; presentation katmanı gerektiğinde maskeler.
- Structured error message sabit ve güvenlidir; raw exception message/stack trace yoktur.
- Security authorization 5.0E tarafından sağlanır; engine authorization kararı üretmez.
- Audit intent ile observability ayrımı korunur; engine audit sink çağırmaz.

## 31. Test Stratejisi

### 31.1 Contract/golden tests

- exact enum manifests;
- frozen dataclass/tuple/map invariants;
- engine-local immutable JSON cebiri ve 5.0C import yasağı;
- strict UUID/Decimal/Enum/date/tuple/object/record codec primitive vectors ile full CashFlowResult round-trip/digest;
- exact auxiliary record/tag/projection vectors: account evidence, bridge, evidence bundle, pre-context, mapping registry, policy bundle, component reference ve source provenance; self-field exclusion, sort-key duplicate ve every one-field mutation;
- exact account-family/disposition/endpoint-reconciliation/root-semantics logical tags ve golden vectors; every one-field mutation, missing proof ve cross-record digest mismatch rejection;
- provider-neutral `cf.document_storage_key.v1` golden/one-field mutation, physical-provider locator equivalence ve tamper rejection;
- exact `engine_inputs_v3_digest`, `run_options_v3_digest`, BS/IS/Ratio/Cash Flow `owner_content_digest` golden vectors; raw bytes yerine digest ve unknown/repr fallback rejection;
- exact `orchestration/terminal-content/v3` root/record/error/financial-lineage golden vectors; DB-generated ID/timestamp/physical-locator exclusion, pre-existing source-ID inclusion, every one-field mutation ve create-vs-reuse semantic equality;
- execution provenance'in durable records'dan exact reconstruction'ı; mutated call/reused/skipped tuple with identical records rejection ve restart terminal-digest equality;
- same-period source locator canonical branch: same-run owner ID'nin existing olarak sunulması rejection, external owner'ın same-run sunulması rejection ve restart tag/engine-code reconstruction;
- exact recursive `OrchestrationJsonObjectV3` scalar/value algebra, sorted-key/immutability, float/list/dict/Enum/datetime/unknown-type negatives;
- application v1/v2 separate type/enum/field manifests, v1 bytes unchanged, v2 unknown/missing rejection;
- V1/V3 persistence command/binding/snapshot/registry/port type-identity separation, cross-type rejection ve exact 4/7 owner counts;
- exact Orchestrator V3 enum/request/options/result/envelope/error/snapshot/telemetry ve `AnalysisOrchestratorPortV3` field/signature manifests; V3 result kind→runtime type golden matrix;
- exact Application-v2 command/query/result/envelope/outcome field manifests, financial-vs-artifact XOR, Cash Flow typed payload discriminator ve exact fake port implementations;
- Cash Flow requested BS/IS nested same-run `source_engine_code` preflight rejection; document/existing-owner pre-resolvable provenance digest ve Ratio-only same-run locator acceptance;
- exact V3 tenant-scope/claim/finalize types, nullable BS/IS canonical-result digest invariant, five-member result-bearing type aliases ve 16-code failure/retryability reachability;
- exact 16-code origin/lifecycle reachability: resolver-only no run, engine typed failed execution + algorithm-derived terminal run (`PARTIALLY_COMPLETED`/`FAILED` literal vectors) + success command DTO, persistence-only no commit, unexpected orchestrator exception no terminal persistence;
- exact Cash Flow code/safe-metadata/retryable round-trip through `StructuredErrorV3`, durable error columns, `ApplicationProjectedErrorDTOV2`/`AnalysisErrorDTOV2`; raw cause redaction;
- durable error extension partial-null, wrong run/execution/engine/status/version/category, resolver/persistence-only code, retry spoof, wrong safe message, non-null exception type ve scalar/array/non-empty JSON metadata rejection; generic Cash Flow dependency/cancel extension-all-null allowance;
- generic six-category exact message/empty-metadata/false-retry/normalized-exception manifest; durable row→restart projection→identical `StructuredErrorV3`/terminal digest round-trip ve generic spoof negatives;
- Decimal-only recursive contract;
- status/evidence reachability;
- exact supported accounting-basis/policy manifest; unknown/missing/inflation-adjusted rejection ve full presentation-policy row mutation tests;
- full line-item manifest exact-once/order ve duplicate/missing/extra/reorder rejection;
- exhaustive fixed/either-sign manifest ve wrong-sign strict decode rejection;
- monetary scale/magnitude/non-finite negatives;
- same input → same canonical bytes/digest;
- no SQLAlchemy/FastAPI/Pydantic transitive import.

### 31.2 Accounting/property tests

- asset/liability working-capital sign properties;
- debit/credit-normal economic-balance ve abnormal-negative sign preservation;
- cash exclusion from working capital;
- opening/closing/net-change identities;
- prior/current reported BS cash-and-equivalents ↔ policy-defined TB endpoint exact MATCHED records; missing endpoint→INSUFFICIENT ve non-null mismatch→SOURCE_EVIDENCE_CONFLICT/no owner;
- no missing→zero conversion;
- no residual→FX/other plug;
- no gross capex/debt/dividend fabrication;
- exact asset residual vectors: pure depreciation→estimated investing zero, acquisition+depreciation, revaluation-only→zero, disposal carrying amount+gain/loss bridge, paired transfer and FX;
- exact account-family vectors: PPE/intangible/financial-investment net-carrying gross-minus-contra, borrowing gross obligation, current/prior family membership parity, wrong/null family reference, contra double-count ve incomplete family coverage rejection;
- exact debt residual vectors: lease-recognition-only→zero, debt-to-equity conversion→zero, FX-only→zero, cash borrowing+non-cash component and partial/unknown bridge→UNAVAILABLE;
- capitalized-interest vectors: paid capitalization asset correction + single interest cash contributor; accrued capitalization paired asset/debt correction + zero cash; no cross-domain duplicate contributor;
- bridge temporal provenance: valid exact current FLOW_INTERVAL; PRIOR role, AS_OF, gap, overlap ve partial-window rejection;
- gross-line XOR estimated-residual and source-component exact-one dedup across OCF/investing/financing;
- FCF exact PPE+intangible acquisition operand, excluded financial investments/disposals ve applicability matrix;
- accrual-to-cash payable/receivable bridge, dedicated component requirement ve no double count;
- direct-cash-without-accrual reversal contributor rejection; current + deferred-tax separation;
- known direct cash + missing embedded accrual → amount None/allocation empty/evidence-only literal case;
- tax all-operating ve multi-activity allocation sum/sign/duplicate guards;
- aggregation-role exhaustive manifest; detail/subtotal/FCF/reconciliation no-double-count;
- restricted cash opening→closing classification changes ve report preservation;
- unclassified non-zero no-silent-omission behavior for cash/WC/investing/financing;
- exhaustive account disposition: every selected account exact one class; P&L-in-net-profit/non-cash/not-relevant proof; non-zero unresolved cash→INSUFFICIENT, other non-zero unresolved→all activity subtotals unavailable/PARTIAL_UNRECONCILED, no COMPLETE reachability;
- EXACT/DERIVED/ESTIMATED/UNAVAILABLE propagation;
- yedi `CashFlowResultStatus` reachable; ilk beş result-bearing status ve iki failure group altında bütün kapalı error code'ları reachable;
- tolerance boundaries: below/equal/above rounding and material;
- zero reference behavior.
- quantized persisted identity after strict serialization round-trip;
- TRY scale, exact `Decimal("1")` unit authority, locked Company currency, 64-digit aggregate boundary ve precision trap tests.
- source-vs-normalized monetary fields: TRY source=normalized exact vectors, caller/payload multiplier override, multiplier double-application, foreign-currency/translation-proof, normalized movement/balance mismatch ve missing→zero rejection.
- bridge source-vs-normalized signed adjustment, same-run FS net-profit/depreciation fixed-unit projection, foreign same-run/persisted fail-closed ve source/normalized one-field mismatch vectors.
- fractional-cent leaf `Decimal("1.005")` HALF_EVEN scale-2 finalization success ve intermediate inexact operation failure.
- adversarial iki/üç-activity half-cent tax allocation: allocation-leaf quantize → canonical line sum → subtotal/reconciliation exact identity; independently-rounded line total ve residual-cent distribution yasağı; strict codec round-trip.

### 31.3 Registry tests

- exact ordered code-role and role-behavior literal manifests; every role covered;
- exact four-row account-family/member manifest, mapping-row family field parity, family/disposition digests ve duplicate member rejection;
- account-code exact ASCII grammar: every allowed separator, leading-zero preservation, outer/repeated separator, Unicode digit/space, sign/letter/punctuation/length negatives;
- every readable candidate shorthand → exact named line-code tuple, code-specific normal-balance preservation, role-normal parity/source-proof branch ve no runtime free string;
- known contra-account longer-prefix overrides (119/241/243/244/246/247/249/322), sign ve no-gross-fabrication;
- financing contra 302/308/402/408 conservative UNCLASSIFIED/fail-closed behavior;
- 243/246 investment commitment delta does not affect OCF or fabricate investing cash;
- long-term financial investments kesin investing/excluded-from-cash; missing maturity evidence cash ground'u bozmaz;
- cf110 equity instrument eligibility flags true olsa bile cash-equivalent olamaz;
- received check/POS operating-asset WC effect, issued check role ayrımı ve no-cash inclusion;
- conditional cash-equivalent/investing branch exact-one selection;
- PPE/intangible/borrowing multi-candidate line selection only with gross evidence;
- exact > longest prefix > role > unclassified;
- longest-prefix tie/conflict rejection;
- duplicate account mapping rejection;
- account-name-only rejection;
- cash allowlist and eligibility evidence;
- non-zero eligibility-unresolved → INSUFFICIENT_DATA ve short-term-cash-commitment-purpose negatives;
- term/restricted/overdraft/POS/check negative cases; blocked/restricted transfer'ın yalnız restriction nedeniyle investing/operating'e map edilmediği, balance delta'dan reclassification üretilmediği ve yalnız authoritative reclassification event'in tek contributor olduğu literal vakalar;
- restricted demand-deposit üçlüsü: preserves=true → `RESTRICTED_INCLUDED`, preserves=false → `RESTRICTED_BANK_ASSET`, preserves=None → `ELIGIBILITY_UNRESOLVED`;
- negative 100, negative 102 with/without overdraft evidence ve mixed positive-deposit/negative-overdraft no-netting cases;
- parent/leaf double-count rejection;
- registry digest/golden manifest.
- per-period TB-over-equivalent source precedence, duplicate/conflict rejection ve no-merge behavior.

### 31.4 Comparable-period tests

- same tenant/company/currency/basis;
- exact adjacent interval;
- calendar January/Q1 örnekleriyle birlikte 1 Temmuz fiscal-year ilk ay/ilk çeyrek/annual-YTD opening prior YEAR_END literal cases;
- first-fiscal MONTHLY/QUARTER ile generic candidate aynı scope'ta birlikte bulunduğunda generic row ineligible ve annual YEAR_END exact seçilir; first-fiscal olmayan interval'da annual row ineligible;
- period type/duration/coverage compatibility;
- annual reporting-period boundary containment ve IFRS 18 cutoff literal vakaları: calendar annual/Q1-2027 reject, 2026-07-01 mali yılı içindeki 2027 interim allow, 2027-07-01 mali yılı reject, early-adoption reject;
- overlap, gap, missing and ambiguous candidate;
- latest-fallback prohibition;
- cumulative/discrete coverage mismatch;
- source status/digest corruption;
- current/prior policy mismatch.
- period metadata all-null/all-set, annual containment, unsupported basis/policy ve caller/filename override rejection.
- period-descriptor canonical vectors, comparability-proof exact field manifest ve one-field mutation rejection.
- prior-BS/current-TB/prior-TB candidate predicate manifest; 0→missing/INSUFFICIENT, 1→exact select, >1→`SOURCE_EVIDENCE_CONFLICT`; canonical candidate-set digest one-field mutation ve latest/first fallback prohibition.

### 31.5 PostgreSQL lineage tests

- valid exact three-base-role graph ve optional four/five-role graph;
- `INSUFFICIENT_DATA` current-only ve zero-lineage owner;
- each role/type/period matrix;
- duplicate role/source;
- mixed prior periods;
- wrong tenant/company/current/prior period;
- unbound/quarantined company;
- source status/null payload/type/source-mode failures;
- zero-lineage owner BEFORE INSERT tenant/source-mode/document/status/payload/digest yanında exact engine-version, null error-message, started/completed presence/order negatif guards;
- orchestration error extension real SQL: all-null/all-set, partial-null, wrong run/execution/engine/status/version/category, resolver/persistence-only code, retry/message spoof, original exception ve scalar/array/non-empty JSON rejection; exact V3 generic Cash Flow dependency/cancel all-null acceptance ve message/normalized-label spoof rejection; exact V2 all-null legacy error'ın V3 generic manifestine tabi olmadan mevcut 5.0B davranışıyla kabulü;
- source analysis-type ve engine-version snapshot mismatch;
- malformed/wrong/corrupt payload/provenance/period SHA-256;
- malformed digest DB CHECK rejection; well-formed wrong payload/provenance/period digest repository-stage rejection; load/resume corruption rehash rejection;
- real no-op UPDATE/DELETE immutability; OLD/NEW noncash→cash-flow UPDATE guard bypass rejection;
- all Cash Flow owner (zero-lineage dahil) ve referenced source semantic mutation rejection;
- no-Cash-Flow V3 BS/IS/Ratio owner full-column UPDATE/DELETE, outbound source append/update/delete ve referenced document mutation rejection; V2 behavior regression; Cash-Flow-aware Ratio→Cash-Flow lineage append/update/delete rejection;
- referenced `financial_analysis_result_sources` protected-parent outbound INSERT/UPDATE/DELETE rejection; unrelated parent→protected target incoming edge allowance; concurrent provenance mutation versus lineage insert serialization ve stale `source_provenance_digest` rejection;
- recursive provenance root-depth 0, direct depth 1, depth 16 accept, depth 17 reject, document-edge no-increment ve cycle-at-depth-16 rejection parity'si (Python resolver/codec + PostgreSQL CTE);
- `cf.provenance_closure.v1` root/descendant set membership: exact root semantics, root-edge no-parent-ID/no-duplication, descendant nodes/edges only, root+descendant document union ve persisted-root/same-run-root identical semantic bytes golden; root UUID/timestamps excluded fakat primary document/source-mode/type/version/status/payload digest mutation digest'i değiştirir; A/B document'ları union'da zaten varken primary A↔B değişimi terminalde reddedilir;
- every Cash Flow owner için legacy `financial_analysis_result_sources` count=0; raw INSERT ve UPDATE reparent-to-Cash-Flow rejection;
- direct Cash Flow owner orphan INSERT deferred-commit rejection; zero/inconsistent sealed V3 execution reference existing-owner reuse rejection ve one-or-more all-consistent immutable reference allowance;
- V3 owner-bearing execution raw SQL manifesti: dört exact engine→`(analysis_type,result_kind)` eşleşmesinin olumlu vakaları ve Ratio için storage literal'inin exact `financial_ratios` golden değeri; BS↔IS/Ratio/Cash Flow owner permütasyonlarının, kısaltılmış `ratio` literal'inin, her engine için wrong result-kind'in ve scope/version/digest/XOR ihlallerinin reddi; aynı legacy V2 fixture'larının additive V3 guard'a girmediği regresyonu;
- same-period locator ambiguity: aynı-run owner ID'sini caller existing-analysis gösterdiğinde pre-persist rejection, external owner için ters spoof rejection ve DB restart terminal-digest round-trip;
- later Cash Flow execution/reuse raw INSERT wrong run scope/current period, wrong-engine→Cash-Flow-owner, Cash-Flow-engine→wrong-owner, result kind/status, V3 version, digest, reuse source/input fingerprint, source-run≠new-run.previous_run arbitrary-old-run ve sealed lineage graph rejection; null/unknown/failure `inner_status`, complete/degraded mapping mismatch, `insufficient_data` ile complete-role spoof ve reused-source inner-status mismatch rejection; repository payload-status/inner-status/lineage-set parity negative'leri; forged REUSED-only origin seal rejection;
- Company namespace trigger catalog/order parity; Period/Document/FAR/FAR-source INSERT phantom, non-key UPDATE, key/company UPDATE ve DELETE yarışları; source-binding trigger'ın parent pre-read yapmadığı ve OLD/NEW denormalized company union'unu kullandığı parent key-update/delete yarışları; OLD/NEW multi-company canonical order, `55P03` immediate rollback/no retry, bounded lock-timeout ve RI KEY SHARE deadlock-free completion;
- financial-owner execution namespace trigger'ının owner pre-read yapmadan NEW.run parent company'yi kilitlemesi; noncash-engine→Cash-Flow-owner raw race/validation rejection;
- exact pre-run source candidate IDs/digest terminal revalidation; duplicate eligible source rejection ve candidate INSERT/DELETE/UPDATE phantom yarışları;
- trusted document input bytes ile row checksum/size/sealed storage key exact proof; different bytes/same ID, referenced primary/binding document no-op UPDATE/DELETE, checksum/size/type/status/company/period/id mutation/reparent, external content overwrite/delete attempt, terminal re-read mismatch ve load/resume/reuse rehash rejection;
- trusted prerequisite administration: period all-null→atomic write, exact idempotent replay, partial/different overwrite rejection; document stage→verify→publish exact replay, legacy-byte/checksum/size mismatch ve provider collision; pre-audit failure no mutation, post-audit failure warning/alert, production missing/fake/write-capable verifier readiness=false;
- company tenant/currency, period status/date/type/months/basis ve source monetary-unit drift during terminal-write race rejection;
- Company tenant mutation real SQL rejection; post-commit Company currency ve FinancialPeriod policy/date/status metadata drift'lerinde historical read allowed fakat V3 snapshot/resume/reuse/source-for-new-run rejected; external source/document corruption her iki modda rejected;
- named Company composite unique, every FK `ON DELETE RESTRICT`/non-deferrable, no delete cascade, explicit source index ve safe repr ORM/DDL parity;
- atomic commit and injected rollback;
- SAVEPOINT early-return discard;
- concurrent loser orphan=0;
- concurrent winner/loser exact terminal-content digest equality; structured error Cash Flow extension/lineage mutation conflict; early-return SAVEPOINT rollback/discard before winner projection;
- same terminal payload fakat Start-vs-Resume/Retry, different previous run, wrong durable previous-run FK/request-fingerprint/terminal-digest winner rejection;
- same run/different request fingerprint; same fingerprint fakat farklı terminal digest, verified owner content/canonical semantics, lineage/provenance/period proof winner rejection; generated loser owner UUID'sinin rollback edilip winner FK'siyle karşılaştırılmaması;
- V2 command/snapshot/binding supplied to V3 store and V3 supplied to V1 store fail before write;
- exact payload+exact lineage existing-owner 0→create, 1→reuse, >1→integrity failure; same payload with missing/extra/different role/source/period/version/digest rejection;
- BS/IS domain owner `AnalysisStatus.FAILED`, `result_json=None`, nullable canonical-result digest ve non-null owner-content digest create/existing/resume vectors;
- resume transitive corruption/missing-source failure.

### 31.6 Orchestrator/application tests

- exact V2 and V3 graph manifests;
- distinct V2/V3 entrypoint/type discriminator rejection;
- pre-run context + same-run `EngineResultEnvelopeV3.result` assembly, version-pinned FS projection ve bridge merge/digest conflicts;
- domain FS result_json=None → persisted diagnostic INSUFFICIENT_DATA; technical FS FAILED/SKIPPED → no Cash Flow owner;
- legacy execution plan readability;
- legacy fingerprint golden vectors unchanged;
- conditional Cash Flow downstream fingerprint;
- V2 request fingerprint byte identity ve V3 result/no-result/absent three-branch sentinels;
- current-version compatibility gate;
- V2 source→V3 resume/retry rejection; no cross-major node reuse or clean-start fallback;
- exact 11-engine schema/model compatibility manifest, including report dual branch;
- optional-dependency reuse invalidation;
- strict Cash Flow snapshot codec;
- four financial/seven artifact ownership count;
- owner ordering BS→IS→CF→Ratio;
- planned persisted-vs-same-run locator XOR; same-run BS/IS→Cash Flow ve Cash Flow→Ratio UUID resolution inside terminal transaction; missing/wrong-order locator rollback;
- caller-supplied Cash Flow→Ratio edge rejection; result-bearing CF owner'da fixed single `SUPPORTING_ANALYSIS(CASH_FLOW)` auto-injection, CF owner yoksa edge yok;
- v1/v2 application DTO readers;
- `ApplicationPayloadEnvelopeDTOV2` generic/financial-artifact/Cash Flow XOR vectors; financial Cash Flow serializer version null;
- V2 service/ports phased coordination, post-result owner planning, projection-failure recovery ve idempotent persisted-read replay;
- wrong-scope result never projected.
- Application-v2 port error/timeout/retryability table, cancel normal-result matrix, dört authorized/audited query method'u, tenant-key→UUID fail-closed mapping ve V3 claim finalize type tests.
- `authorize_resume_source` deny → exact `RESUME_SOURCE_UNAUTHORIZED`, no materialization/no clean-start.

### 31.7 Ratio/report regression

- six formulas unchanged;
- legacy `analyze_financial_ratios` signature/behavior byte identity; V3 wrapper no-CF byte identity ve six-key Cash Flow category-only replacement;
- missing engine versus missing field;
- no health/credit weight change;
- cash-interest provenance warning;
- report projection no recompute;
- report v1/v1.1 dual immutable registry, no-CF byte-identical shape/fingerprint;
- partial/insufficient not shown as complete;
- legacy report shape when Cash Flow absent.

### 31.8 Migration/Docker gates

- current head → migration1 → migration2 single head;
- both revision AST/import allowlist (stdlib + Alembic/SQLAlchemy only), no `app.*`, literal enum/CHECK/trigger manifest ve generated DDL golden;
- empty full upgrade→stepwise downgrade→upgrade;
- populated period-metadata downgrade1 ve populated Cash Flow/lineage downgrade2 fail-closed;
- namespace triggers upgrade/downgrade/order, nullable Cash Flow error-extension columns and populated-error downgrade2 rejection;
- Cash Flow içermeyen durable V3, sentetik V4+ contract discriminator ve V2 schema/model/plan taşıyıp future fingerprint discriminator kullanan run'ın migration2 downgrade'ını exact legacy allowlist ile fail-closed durdurması;
- migration2 upgrade preflight'ın pre-existing no-CF `3.x`, `4.x`, unknown schema/model/plan/fingerprint discriminator row'larını backfill etmeden reddetmesi;
- `ix_orchestration_engine_executions_financial_analysis_result_id` ORM/DDL/catalog parity, upgrade/downgrade lifecycle ve owner-seal/protected-root lookup'unda EXPLAIN'in bu index'i kullanabildiğini doğrulayan bounded PostgreSQL plan testi;
- full Docker suite, 0 failed, 0 skipped;
- PostgreSQL integration/concurrency suite;
- `git diff --check` clean.

## 32. Performance Targets

- Pure engine complexity: `O(account_count + mapping_count)`; per-account full-registry scan yasak, prefix index kullanılır.
- 10,000 leaf account için p95 pure calculation hedefi ≤ 250 ms, warmed process, I/O hariç.
- Source resolution ve persistence timeout'ları caller/config tarafından pozitif ve bounded sağlanır.
- Result line/evidence sırası canonical code ve source role ile deterministik sıralanır.
- Positive authorization veya source-integrity cache kullanılmaz; immutable mapping registry process-local olabilir.

## 33. Riskler ve Reddedilen Alternatifler

| Risk | Kontrol |
|---|---|
| Net balance'dan brüt hareket uydurma | Evidence-gated gross lines; estimated net ayrı |
| Yanlış prior period | Exact comparable resolver, no latest fallback |
| Cash-equivalent over-inclusion | Strict eligibility evidence |
| Cross-period lineage corruption | Immutable table + digest/type/scope triggers |
| Company namespace lock contention | Tek company row, bounded terminal transaction/I/O timeout, mutation `NOWAIT`; implicit retry yok |
| Mutable/legacy document object | Content-addressed write-once seal + terminal/load/resume rehash; unsealed source readiness fail-closed |
| Legacy contract kırılması | Major versioned path + golden legacy vectors |
| Reuse stale dependency | Current-version and optional-dependency gate |
| Partial'ın complete sunulması | Closed status/projection rules |
| Profile ile double count | Accrual reversal + actual cash bridge |

Reddedilen alternatifler:

- doğrudan yöntem veya direct-statement parsing;
- result JSON içinde tek başına prior source ID saklamak;
- mevcut same-period lineage tablosunun FK'sini gevşetmek;
- previous cash'i zero kabul etmek;
- latest period fallback;
- account-name heuristic mapping;
- reconciliation residual'ını FX/other yapmak;
- net debt/PPE movement'ı brüt flow saymak;
- tek opaque confidence score;
- score ağırlığını cash-flow geldiği için otomatik değiştirmek;
- event sourcing;
- cash-flow owner payload'ını artifact tablosunda da tutmak.

## 34. Açık Kararlar ve Blocking Durumu

Bağlayıcı kullanıcı kararları ve bu dokümandaki fail-closed teknik seçimlerle bütün implementation kararları kapanmıştır.

- Açık kullanıcı kararı: **0**
- Kritik blocking: **0**
- Yüksek blocking: **0**
- Future hardening: direct method, transaction/bank integration, company-specific mappings, IFRS 18 sonrası statutory profile, multi-period trend (4.6), consolidation/intercompany (4.7), score/benchmark integration.

Future hardening maddeleri 4.5 v1 implementasyonuna dahil edilmez.

## 35. Test-Gated Implementasyon Aşamaları

Her aşama kendi hedefli testleri, ilgili regresyon paketi ve `git diff --check` temiz olmadan kapanmaz. Bir gate failure sonraki aşamayı durdurur.

### 35.1 4.5A — Contract and Accounting Policy Foundation

| Alan | Plan |
|---|---|
| Production dosyaları | yeni `app/engines/common/cash_flow_types.py`, `cash_flow_policy.py`, strict codec/version manifesti; yalnız data/Protocol içeren `analysis_orchestrator_v3/types.py`, `orchestration_persistence_v3/types.py`, `analysis_application_v2/contracts.py` ve V3 scope/claim contract modülleri |
| Testler | contract, enum golden, frozen/Decimal, status/evidence/applicability, source-mode, account-disposition/family, endpoint-reconciliation ve provenance-root semantics, policy cutoff, monetary normalization; exact V3 request/result/envelope/snapshot/telemetry, persistence V3 binding, Application-v2 command/query/DTO/outcome ve V3 claim type manifests; V1 identity ve no-framework-import tests |
| PostgreSQL | Hayır |
| Migration | Hayır |
| Public contract | Ayrı additive Orchestrator V3/Application V2/Persistence V3 data contract'ları kilitlenir; 5.0A–5.0C mevcut tip/imzaları değişmez |
| Blocking kabul | Sonraki aşamaların kullandığı bütün exact type/enum/field manifests önceden mevcut; net-profit bridge, exhaustive account disposition/family proof'u, iki endpoint reconciliation kaydı ve result-bearing/failure ayrımı; TMS/TFRS-2024 profile cutoff; 0 failed/skipped |

### 35.2 4.5B — Account Mapping Registry

| Alan | Plan |
|---|---|
| Production dosyaları | yeni `app/engines/cash_flow/registry.py`, `mapping.py`; cash-equivalent, account-family ve exhaustive disposition policy manifestleri |
| Testler | precedence, duplicate/conflict, name-only rejection, cash eligibility, restricted/vadeli/POS/çek/overdraft; account-family member/netting/residual kuralları; her authoritative account row için tek disposition ve P&L-in-net-profit proof'u; registry digest/property tests |
| PostgreSQL | Hayır |
| Migration | Hayır |
| Public contract | Yok |
| Blocking kabul | Exact code-role/role-behavior/family/disposition manifests ve golden digest; her account tek role ve tek exhaustive disposition; eligibility, family ve disposition evidence fail-closed; generic real mizan regression; 0 failed/skipped |

### 35.3 4.5C — Multi-period Input Resolution

| Alan | Plan |
|---|---|
| Production dosyaları | `FinancialPeriod` additive policy metadata fields; application/integration boundary'de `cash_flow_inputs.py`, comparable-period/source resolver port ve SQLAlchemy adapter'ları; internal-only `cash_flow_prerequisites.py`, `CashFlowPrerequisiteAdministrationService`, SQLAlchemy period-policy repository, content-addressed document sealer/verifier ve production readiness binding; ilk Alembic migration |
| Testler | exact flow-window, period compatibility, ambiguous/missing/gap/overlap, source status/digest/scope, TB-or-equivalent evidence; canonical existing/same-run source locator reconstruction, persisted-vs-recomputed provenance-root parity ve BS/policy cash endpoint girdileri; period all-null→write/exact replay/conflicting overwrite; document seal exact replay/checksum-size mismatch/collision; required pre-audit, post-audit warning, adapter/profile readiness ve no-manual-SQL/public-route tests |
| PostgreSQL | Evet, gerçek period/source resolution |
| Migration | **Evet — migration 1/2: nullable authoritative period policy metadata** |
| Public contract | Henüz 5.0A dispatch'e bağlanmaz; yeni internal trusted DTO |
| Blocking kabul | Latest fallback yok; caller evidence spoof edemez; current/prior canonical digest rehash ve source-root equality; source locator ile BS/policy endpoint kanıtı deterministik; period metadata ve legacy document için tek-record trusted/audited/idempotent supported onboarding yolu hazır; unsealed object/readiness fail-closed; 0 failed/skipped |

### 35.4 4.5D — Indirect Cash Flow Core

| Alan | Plan |
|---|---|
| Production dosyaları | yeni `app/engines/cash_flow/analyzer.py`, `calculation.py`; family balance/netting ve disposition proof assembly dahil 4.5A `CashFlowComputationDraft` internal contract'ına leaf/contributor üretimi |
| Testler | net-profit bridge, non-cash, WC signs, family debit/credit netting ve residual kapanışı, exhaustive disposition/double-count yasağı, investing/financing safeguards, FCF, deterministic draft golden/property tests |
| PostgreSQL | Hayır |
| Migration | Hayır |
| Public contract | Persisted/public result veya `EngineAdapter` registration yok; draft store'a verilemez |
| Blocking kabul | Double-count/fabrication veya disposition dışı authoritative row yok; family member/residual kanıtları kapalı; canonical line manifest leaf'leri deterministic draft'ta; same input same draft bytes; 0 failed/skipped |

### 35.5 4.5E — Reconciliation and Data Quality

| Alan | Plan |
|---|---|
| Production dosyaları | `app/engines/cash_flow/reconciliation.py`, completeness/evidence/result builder'ları, `service.py`, `adapter.py`; draft→tek `CashFlowResult/CashFlowEngineOutcome` finalization |
| Testler | exact/equal/boundary thresholds, missing→None, applicability, partial/complete matrix, residual plug prohibition; opening/current BS endpoint ile policy-classified cash endpoint parity, iki endpoint record'un status/evidence reachability'si |
| PostgreSQL | Hayır |
| Migration | Hayır |
| Public contract | 4.5A'da kilitlenen `CashFlowResult` v1 shape/status contract'ı değişmez; yalnız reconciliation/completeness implement edilir |
| Blocking kabul | 13-line statement manifest ve optional FCF ayrımı; yedi outcome status / beş persisted result status ayrımı; BS↔policy opening/closing endpoint mismatch fail-closed ve plug yasağı; bütün status/error/endpoint-status reachability; Decimal-only output; 0 failed/skipped |

### 35.6 4.5F — Persistence and Cross-period Lineage

| Alan | Plan |
|---|---|
| Production dosyaları | 4.5A'da kilitlenen V3 persistence contracts'a karşı yeni lineage model/repository adapter, ownership/repository/snapshot adapter'ları; orchestration persistence CHECK/owner staging güncellemeleri; ikinci Alembic migration |
| Testler | full PostgreSQL matrix, immutability, atomic rollback, SAVEPOINT loser, concurrency, resume corruption, migration cycle |
| PostgreSQL | Zorunlu |
| Migration | **Evet — migration 2/2: lineage/trigger/Cash Flow CHECK widening** |
| Public contract | 5.0B V1 port/type imzaları değiştirilmez; additive `RunStorePortV3`/`SnapshotReaderPortV3` ve V3 command/binding ailesi kullanılır |
| Blocking kabul | V1↔V3 cross-type fail-closed; exact 4/7 registry; tek lineage source; no duplicate payload; no orphan; populated downgrade fail-closed; single head; 0 failed/skipped |

### 35.7 4.5G — Orchestrator/Application Integration

| Alan | Plan |
|---|---|
| Production dosyaları | 4.5A'da kilitlenen contract'lara karşı orchestrator-v3 registry/dispatch/fingerprint/service/accessors; Application-v2 ports/service/query/mapping/ownership/projection; V3 snapshot integration |
| Testler | V2/V3 graph, legacy golden fingerprints, no cross-major reuse, V3-only compatibility, optional reuse invalidation, owner ordering, exact v1/v2 DTO/port replay |
| PostgreSQL | Evet, terminal owner/lineage/application persistence |
| Migration | Hayır; 4.5C + 4.5F iki-migration head'i kullanılır |
| Public contract | Explicit major-version evolution: Orchestrator v3, Application DTO v2; legacy readers korunur |
| Blocking kabul | 11/23/2/3/28 exact graph; exact Application-v2 payload envelope; legacy run backfill/upcast/reuse yok; clean-start fallback yok; 0 failed/skipped |

### 35.8 4.5H — Ratio Integration

| Alan | Plan |
|---|---|
| Production dosyaları | ratio service/adapter ve orchestrator invocation mapping; formula registry değişmez |
| Testler | six existing formula golden, missing-engine/field split, Cash Flow lineage, no score/weight change |
| PostgreSQL | Financial owner lineage integration için Evet |
| Migration | Hayır |
| Public contract | Additive cash-flow input yalnız v3 path |
| Blocking kabul | Formül metadata/digest değişmez; health/credit weights unchanged; 0 failed/skipped |

### 35.9 4.5I — Executive Report Integration

| Alan | Plan |
|---|---|
| Production dosyaları | report types/service/registry compatibility ve orchestrator mapping |
| Testler | optional projection, no recompute, partial display, evidence preservation, legacy no-CF shape |
| PostgreSQL | Hayır; application read integration hedefli olabilir |
| Migration | Hayır |
| Public contract | Report schema/model 1.1 yalnız cash-flow-aware projection; 18-section registry korunur |
| Blocking kabul | Complete/partial ayrımı doğru; legacy fingerprints/sections unchanged; 0 failed/skipped |

### 35.10 4.5J — Production Closure

| Alan | Plan |
|---|---|
| Production dosyaları | Yeni özellik yok; yalnız blocking fix ve kullanıcı onayıyla Architecture Book sync |
| Testler | tüm 4.5 gates, 5.0A–5.0E regressions, PostgreSQL, concurrency, migration cycle, full Docker |
| PostgreSQL | Evet |
| Migration | Yeni migration yasak; iki sıralı 4.5 migration doğrulanır |
| Public contract | Freeze/golden audit |
| Blocking kabul | 0 failed, 0 skipped, `git diff --check` clean, backend/db healthy, single Alembic head, design sapması yok |

## 36. Production Readiness Kriterleri

Milestone ancak aşağıdakilerin tamamı sağlanınca runtime Production Ready sayılır:

- bütün 4.5A–4.5J kapıları yeşil;
- gerçek PostgreSQL lineage/immutability/concurrency testleri yeşil;
- exact migration upgrade→downgrade→upgrade ve populated downgrade rejection yeşil;
- legacy 5.0A–5.0E golden/regression testleri yeşil;
- 0 failed, 0 skipped;
- no float/no fabricated-zero/no residual-plug property tests yeşil;
- DAG/ownership/version manifests exact;
- Architecture Book yalnız kapanış onayıyla güncel;
- `git diff --check` temiz;
- backend ve PostgreSQL healthy;
- kullanıcı onayı olmadan commit/push yok.

Tasarım readiness ve runtime readiness farklıdır:

- **Design Readiness:** %100
- **Runtime/Implementation Readiness:** %0 — kod henüz yazılmadı

## 37. Bağımsız Finansal ve Mimari Denetim Raporu

Bu tasarım aynı çalışma içinde altı bağımsız bakışla audit → fix → audit döngüsünden geçirilmiştir.

| Denetim rolü | İlk bulgu | Tasarımdaki kök düzeltme | Son durum |
|---|---|---|---|
| TMS/TFRS cash-flow accounting architect | Net-profit bridge double-count; zaman-bağımsız standard iddiası; FX applicability | Closed accrual reversal bridge, 2024-edition profile cutoff, applicability taxonomy | Kapalı |
| Bank credit analysis specialist | Restricted/term/POS/overdraft ve partial sonuçların yanlış likidite sunumu riski | Strict eligibility evidence, no automatic netting, evidence-preserving projection | Kapalı |
| Financial systems architect | V2 contract digest ve DAG backward-compatibility riski | Orchestrator v3/Application v2, legacy golden projection, exact 11-node DAG | Kapalı |
| Data lineage and audit architect | Same-period FK prior source'u reddediyor; çift lineage riski | Tek immutable cross-period lineage store, role/type/digest/scope guards | Kapalı |
| PostgreSQL migration reviewer | Execution CHECK'leri Cash Flow'u reddeder; destructive downgrade ve mutation riski | İki sıralı additive migration, literal CHECK/guard trigger manifests ve populated downgrade preflight | Kapalı |
| Deterministic calculation/test architect | Estimated→complete, missing→zero, ambient Decimal ve optional reuse riski | 13-line manifest, applicability/None propagation, local Decimal context, version/reuse gates | Kapalı |

### 37.1 Son bağımsız bütünlük denetimi

- Kritik blocking: **0**
- Yüksek blocking: **0**
- Açık kullanıcı kararı: **0**
- Contract, accounting, persistence, migration ve test akışları executable seviyededir.
- 5.0A–5.0C mevcut public contract'ları sessizce değiştirilmez; versioned evolution açıkça tanımlıdır.
- Direct method, 4.6 ve 4.7 kapsamı içeri alınmamıştır.
- Event sourcing, duplicate payload owner, API/queue/worker/UI eklenmemiştir.

## 38. Kullanıcı Onay Kapısı

Bu dokümanın FINAL onayı production implementasyonuna otomatik izin vermez. Implementasyon ancak ayrıca açık kullanıcı onayıyla, 4.5A'dan başlayarak test-gated sırada yapılabilir. 4.5 tamamen kapanmadan 4.6 veya 4.7'ye geçilemez.

**Final verdict:** Milestone 4.5 — Cash Flow Engine tasarımı FINAL olarak onaylanabilir ve implementasyona hazırdır.
