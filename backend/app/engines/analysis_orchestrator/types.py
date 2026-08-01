"""
Milestone 5.0A -- Analysis Orchestrator: enum/dataclass sozlesmeleri.

Bkz. docs/FINOS_MILESTONE_5_0A_ANALYSIS_ORCHESTRATOR_DESIGN.md (v2, FINAL)
Bolum 20-25, 40-45. Bu dosya TAMAMEN sqlalchemy/fastapi/pydantic'ten
bagimsizdir -- diger app.engines.** paketleriyle ayni disiplin.

Onemli tasarim kurallari (bu dosyanin ihlal ETMEMESI gereken):
  - TUM veri yapilari `@dataclass(frozen=True)`, koleksiyonlar `tuple`
    (Architecture Book Sec.7).
  - `OrchestrationRunRequest` HICBIR Callable alan tasimaz -- tamamen
    JSON-serilestirilebilir olmalidir (Bolum 19). `cancellation_probe`/
    `timing_probe`, `run_orchestration()`'in AYRI cagri parametreleridir
    (Bolum 15/45), bu dosyada TANIMLANMAZ.
  - `OrchestrationRunResult` iki ayri "source of truth" TASIMAZ --
    `engine_records` TEK kaynaktir; adlandirilmis motor-sonucu alanlari
    (health_score_result vb.) BILEREK YOKTUR, bunun yerine asagidaki
    typed accessor fonksiyonlari kullanilir (Bolum 23/30).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

# --- Versiyon sabitleri (Bolum 38/40) --------------------------------------

ORCHESTRATION_SCHEMA_VERSION = "2.0.0"
ORCHESTRATION_MODEL_VERSION = "2.0.0"
EXECUTION_PLAN_VERSION = "2.0.0"
FINGERPRINT_SCHEMA_VERSION = "1.0.0"


# --- Enum'lar (Bolum 21) ----------------------------------------------------


class EngineCode(str, enum.Enum):
    """DAG'daki 10 dugum (Bolum 4)."""

    FS_BALANCE_SHEET = "fs_balance_sheet"
    FS_INCOME_STATEMENT = "fs_income_statement"
    RATIO = "ratio"
    BENCHMARK = "benchmark"
    HEALTH_SCORE = "health_score"
    CREDIT_SCORE = "credit_score"
    RECOMMENDATION = "recommendation"
    EXECUTIVE_REPORT = "executive_report"
    DASHBOARD = "dashboard"
    RENDER_CONTRACT = "render_contract"


class EngineExecutionStatus(str, enum.Enum):
    """Bolum 9.1 -- tam ic-durum esleme tablosunun hedef degerleri."""

    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"
    REUSED = "reused"


class RunStatus(str, enum.Enum):
    """Bolum 10 -- 5 degerli, kapali, ayrik enum."""

    FULLY_COMPLETED = "fully_completed"
    COMPLETED_WITH_DEGRADATIONS = "completed_with_degradations"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OrchestrationErrorCategory(str, enum.Enum):
    """Bolum 25 -- TIMEOUT_EXCEEDED v1'den KALDIRILDI (Bolum 16)."""

    ENGINE_CONTRACT_VIOLATION = "engine_contract_violation"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    VERSION_INCOMPATIBLE_ON_REUSE = "version_incompatible_on_reuse"
    FINGERPRINT_MISMATCH_ON_REUSE = "fingerprint_mismatch_on_reuse"
    INVALID_RUN_REQUEST = "invalid_run_request"
    CANCELLED = "cancelled"


# --- Bagimlilik modeli (Bolum 3) -------------------------------------------


@dataclass(frozen=True)
class DependencyRequirement:
    """
    all_of : HEPSI COMPLETED/DEGRADED/REUSED olmali.
    any_of : EN AZ BIRI COMPLETED/DEGRADED/REUSED olmali.
    optional: SKIPPED/FAILED olsa bile motor yine de cagrilir (None gecilir).
    """

    all_of: "tuple[EngineCode, ...]" = ()
    any_of: "tuple[EngineCode, ...]" = ()
    optional: "tuple[EngineCode, ...]" = ()


@dataclass(frozen=True)
class EngineInvocationSpec:
    """
    Bolum 18 -- YALNIZCA metadata tasir. Gercek callable referansi
    KESINLIKLE burada DEGIL, dispatch.py::ORCHESTRATOR_ENGINE_DISPATCH'te.
    """

    engine_code: EngineCode
    dependency: DependencyRequirement
    produces: str
    is_critical: bool


# --- Hata modeli (Bolum 25) -------------------------------------------------


@dataclass(frozen=True)
class StructuredError:
    """
    Guvenlik kurallari (Bolum 25, denetim bulgusu):
      - message_tr SABIT, onceden yazilmis bir sablon metindir -- motorun
        ham exception mesaji BIREBIR TASINMAZ.
      - original_exception_type YALNIZCA sinif adini tasir.
      - Stack trace/hassas veri HICBIR ALANDA tasinmaz.
    """

    category: OrchestrationErrorCategory
    engine_code: "EngineCode | None"
    message_tr: str
    original_exception_type: "str | None" = None


# --- Sonuc sarmalama (Bolum 23 -- tek source of truth) ----------------------


@dataclass(frozen=True)
class EngineResultEnvelope:
    engine_code: EngineCode
    result_kind: str
    result: Any


@dataclass(frozen=True)
class PerEngineExecutionRecord:
    engine_code: EngineCode
    status: EngineExecutionStatus
    result: "EngineResultEnvelope | None"
    inner_status_value: "str | None"
    error: "StructuredError | None"
    dependency_engine_codes: "tuple[EngineCode, ...]"
    engine_schema_version_used: "str | None"
    engine_model_version_used: "str | None"
    input_fingerprint: str
    fingerprint_schema_version: str


@dataclass(frozen=True)
class ExecutionProvenance:
    execution_plan_version: str
    engine_call_sequence: "tuple[EngineCode, ...]"
    reused_engine_codes: "tuple[EngineCode, ...]"
    skipped_engine_codes: "tuple[EngineCode, ...]"


# --- Fingerprint modeli (Bolum 41) ------------------------------------------


@dataclass(frozen=True)
class EngineInputFingerprint:
    engine_code: EngineCode
    fingerprint: str
    fingerprint_schema_version: str


@dataclass(frozen=True)
class RequestFingerprint:
    request_fingerprint: str
    engine_input_fingerprints: "tuple[EngineInputFingerprint, ...]"


# --- Resume/reuse modeli (Bolum 14) -----------------------------------------


@dataclass(frozen=True)
class PreviousEngineSnapshot:
    engine_code: EngineCode
    execution_status: EngineExecutionStatus
    engine_schema_version_used: "str | None"
    engine_model_version_used: "str | None"
    input_fingerprint: str
    fingerprint_schema_version: str
    result_ref: "Any | None" = None


@dataclass(frozen=True)
class PreviousExecutionSnapshot:
    previous_run_id: str
    request_fingerprint: str
    orchestration_schema_version: str
    orchestration_model_version: str
    execution_plan_version: str
    engine_snapshots: "tuple[PreviousEngineSnapshot, ...]"


# --- Girdi/secenek sozlesmeleri ---------------------------------------------


@dataclass(frozen=True)
class EngineRawInputs:
    """
    9 motorun ham girdileri -- Bolum 2.1'deki gercek motor sozlesmelerinin
    birebir karsiligi. Orchestrator bu alanlari degistirmeden ilgili motor
    cagrisina aktarir.
    """

    balance_sheet_content: "bytes | None" = None
    balance_sheet_filename: "str | None" = None
    income_statement_content: "bytes | None" = None
    income_statement_filename: "str | None" = None
    # Financial Statements'in ortak trial-balance-fallback kaynagi (Bolum 2.1.1).
    trial_balance_result: "dict[str, Any] | None" = None
    prior_period_balance_sheet_facts: "Any | None" = None
    prior_period_income_statement_facts: "Any | None" = None
    prior_period_balance_sheet_result: "dict[str, Any] | None" = None
    prior_period_income_statement_result: "dict[str, Any] | None" = None
    period_start_date: "date | None" = None
    period_end_date: "date | None" = None
    period_months_covered: "int | None" = None


@dataclass(frozen=True)
class OrchestrationRunOptions:
    """
    Segmentasyon/rapor secenekleri -- Bolum 2.1.4-2.1.9. `tenant_id`
    YETKILENDIRME DEGILDIR, yalnizca kategori agirlik profili segmentasyon
    anahtaridir (Bolum 61 ile ayni kural).
    """

    industry_code: "str | None" = None
    company_size_bucket: "str | None" = None
    tenant_id: "str | None" = None
    report_type: "Any | None" = None  # ReportType -- yalnizca EXECUTIVE_REPORT istenirse zorunlu
    dashboard_type: "Any | None" = None  # DashboardType -- yalnizca DASHBOARD istenirse zorunlu
    company_metadata: "Any | None" = None  # ReportCompanyMetadata
    reporting_period_label_tr: "str | None" = None
    optional_sections: "tuple[Any, ...] | None" = None  # tuple[ReportSectionCode, ...]
    currency_display_policy: "str | None" = None
    locale: str = "tr-TR"
    render_contract: "Any | None" = None  # RenderContract -- yalnizca RENDER_CONTRACT istenirse zorunlu


# --- Orchestrator giris/cikis sozlesmesi (Bolum 19/23) ----------------------


@dataclass(frozen=True)
class OrchestrationRunRequest:
    """
    TAMAMEN JSON-serilestirilebilir (Bolum 19) -- Callable alan YOK.
    `run_id`/`correlation_id`/`generated_at` CAGIRAN tarafindan saglanir;
    Orchestrator kendi kimligini/saatini URETMEZ (Bolum 32/48).
    """

    run_id: str
    correlation_id: "str | None"
    generated_at: "str | None"
    requested_outputs: "tuple[EngineCode, ...]"
    engine_inputs: EngineRawInputs
    run_options: OrchestrationRunOptions
    previous_execution_snapshot: "PreviousExecutionSnapshot | None" = None


@dataclass(frozen=True)
class OrchestrationRunResult:
    """Bolum 23 -- `engine_records` TEK source of truth."""

    run_id: str
    correlation_id: "str | None"
    generated_at: "str | None"
    status: RunStatus
    engine_records: "tuple[PerEngineExecutionRecord, ...]"
    warnings: "tuple[dict[str, Any], ...]"
    structured_errors: "tuple[StructuredError, ...]"
    execution_provenance: ExecutionProvenance
    input_version_inventory: "dict[str, str]"
    orchestration_schema_version: str
    orchestration_model_version: str
    execution_plan_version: str
    request_fingerprint: str


# --- Timing/telemetry ayrimi (Bolum 45) -------------------------------------


@dataclass(frozen=True)
class PerEngineTelemetry:
    engine_code: EngineCode
    started_at_offset_ms: "float | None"
    duration_ms: "float | None"


@dataclass(frozen=True)
class ExecutionTelemetry:
    per_engine: "tuple[PerEngineTelemetry, ...]"
    total_duration_ms: "float | None"


class TimingProbe(Protocol):
    """Monotonic saat sarmalayicisi -- YALNIZCA cagiran tarafindan enjekte
    edilir (Bolum 47). Orchestrator kendi basina bir saat kutuphanesi
    import edip CAGIRMAZ."""

    def now(self) -> float: ...


# --- Tip guvenli erisim (Bolum 23 -- duplicate state OLMADAN) ---------------


class OrchestratorResultAccessError(TypeError):
    """Bir typed accessor, beklenen `result_kind` ile eslesmeyen bir kayit
    bulduğunda (ya da kayit hic yoksa yanlis kullanildiginda) firlatilir."""


def _get_engine_result(
    run_result: OrchestrationRunResult,
    engine_code: EngineCode,
    expected_result_kind: str,
) -> "Any | None":
    matches = [
        record for record in run_result.engine_records if record.engine_code == engine_code
    ]
    if not matches:
        raise OrchestratorResultAccessError(
            f"OrchestrationRunResult icinde {engine_code.value} icin hicbir "
            f"PerEngineExecutionRecord yok."
        )
    record = matches[0]
    if record.result is None:
        return None
    if record.result.result_kind != expected_result_kind:
        raise OrchestratorResultAccessError(
            f"{engine_code.value} icin beklenen result_kind "
            f"{expected_result_kind!r} ama {record.result.result_kind!r} bulundu."
        )
    return record.result.result


def get_balance_sheet_result(run_result: OrchestrationRunResult) -> "Any | None":
    return _get_engine_result(run_result, EngineCode.FS_BALANCE_SHEET, "BalanceSheetAnalysisOutcome")


def get_income_statement_result(run_result: OrchestrationRunResult) -> "Any | None":
    return _get_engine_result(
        run_result, EngineCode.FS_INCOME_STATEMENT, "IncomeStatementAnalysisOutcome"
    )


def get_ratio_result(run_result: OrchestrationRunResult) -> "dict[str, Any] | None":
    return _get_engine_result(run_result, EngineCode.RATIO, "dict")


def get_benchmark_result(run_result: OrchestrationRunResult) -> "dict[str, Any] | None":
    return _get_engine_result(run_result, EngineCode.BENCHMARK, "dict")


def get_health_score_result(run_result: OrchestrationRunResult) -> "Any | None":
    return _get_engine_result(run_result, EngineCode.HEALTH_SCORE, "HealthScoreResult")


def get_credit_score_result(run_result: OrchestrationRunResult) -> "Any | None":
    return _get_engine_result(run_result, EngineCode.CREDIT_SCORE, "CreditScoreResult")


def get_recommendation_result(run_result: OrchestrationRunResult) -> "Any | None":
    return _get_engine_result(run_result, EngineCode.RECOMMENDATION, "RecommendationResult")


def get_executive_report_result(run_result: OrchestrationRunResult) -> "Any | None":
    return _get_engine_result(run_result, EngineCode.EXECUTIVE_REPORT, "ExecutiveReportResult")


def get_dashboard_snapshot(run_result: OrchestrationRunResult) -> "Any | None":
    return _get_engine_result(run_result, EngineCode.DASHBOARD, "DashboardSnapshot")


def get_render_contract_preview(run_result: OrchestrationRunResult) -> "Any | None":
    return _get_engine_result(run_result, EngineCode.RENDER_CONTRACT, "RenderContractPreview")
