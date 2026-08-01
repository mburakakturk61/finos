"""
Milestone 5.0A -- Input Fingerprint Modeli (Bolum 41).

Denetim bulgusu R1'in tam cozumu: reuse artik YALNIZCA versiyon esitligine
degil, GERCEK girdi esitligine (SHA-256 canonical-JSON fingerprint) bakar.

Hash politikasi (Bolum 41, kesin/baglayici):
  1. Canonical, deterministic JSON temsili.
  2. Key siralamasi ZORUNLU (sort_keys).
  3. Decimal degerleri canonical string olarak (str(Decimal(...))).
  4. Enum degerleri `.value` ile.
  5. Tuple sirasi KORUNUR (siralanmaz).
  6. Set/map insertion-order fingerprint'i ETKILEMEZ (2. maddenin sonucu).
  7. Ham binary icerik (bytes) icin SHA-256 dogrudan bayt dizisi uzerinden.
  8. Hash algoritmasi: SHA-256 (tum fingerprint'ler icin tek, sabit).
  9. fingerprint_schema_version AYRI tutulur.
  10-11. Secrets/hassas ham veri fingerprint'e/digest'e GIRMEZ -- yalnizca
      digest saklanir.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import hashlib
import json
from decimal import Decimal
from typing import Any

from app.engines.analysis_orchestrator.types import (
    FINGERPRINT_SCHEMA_VERSION,
    EngineCode,
    EngineRawInputs,
    OrchestrationRunOptions,
)


def _canonicalize(value: Any) -> Any:
    """Herhangi bir Python degerini, sort_keys=True ile hash'lenebilecek
    JSON-uyumlu bir yapiya (dict/list/str/int/float/bool/None) donusturur.
    Tuple SIRASI korunur (bir listeye cevrilir ama eleman sirasi degismez).
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        # Ham icerik fingerprint'e DOGRUDAN girmez -- yalnizca kendi
        # digest'i tasinir (kural 10/11).
        return {"__bytes_sha256__": hashlib.sha256(value).hexdigest()}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _canonicalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonicalize(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    # Bilinmeyen bir tip -- son care olarak str() ile deterministik bir
    # temsile dusuruluyor (ornegin bir Protocol/callable degil, saf veri
    # oldugu varsayilir; motor girdileri bu tiplerin disina cikmaz).
    return str(value)


def canonical_hash(value: Any) -> str:
    canonical = _canonicalize(value)
    encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compute_engine_input_fingerprint(
    engine_code: EngineCode,
    *,
    raw_inputs: EngineRawInputs,
    run_options: OrchestrationRunOptions,
    upstream_fingerprints: "dict[EngineCode, str]",
) -> str:
    """
    Bolum 41'deki motor-basina girdi tablosunun birebir karsiligi. Her
    motorun fingerprint'i YALNIZCA o motorun GERCEKTEN tukettigi
    girdilerden turetilir -- kullanilmayan bir alanin degismesi o motorun
    fingerprint'ini ETKILEMEZ.
    """

    EC = EngineCode
    up = upstream_fingerprints

    if engine_code is EC.FS_BALANCE_SHEET:
        payload = {
            "content": raw_inputs.balance_sheet_content,
            "filename": raw_inputs.balance_sheet_filename,
            "trial_balance_result": raw_inputs.trial_balance_result,
            "prior_period_facts": raw_inputs.prior_period_balance_sheet_facts,
        }
    elif engine_code is EC.FS_INCOME_STATEMENT:
        payload = {
            "content": raw_inputs.income_statement_content,
            "filename": raw_inputs.income_statement_filename,
            "trial_balance_result": raw_inputs.trial_balance_result,
            "prior_period_facts": raw_inputs.prior_period_income_statement_facts,
        }
    elif engine_code is EC.RATIO:
        payload = {
            "fs_balance_sheet_fingerprint": up.get(EC.FS_BALANCE_SHEET),
            "fs_income_statement_fingerprint": up.get(EC.FS_INCOME_STATEMENT),
            "prior_period_balance_sheet_result": raw_inputs.prior_period_balance_sheet_result,
            "prior_period_income_statement_result": raw_inputs.prior_period_income_statement_result,
            "period_start_date": raw_inputs.period_start_date,
            "period_end_date": raw_inputs.period_end_date,
            "period_months_covered": raw_inputs.period_months_covered,
        }
    elif engine_code is EC.BENCHMARK:
        payload = {
            "ratio_fingerprint": up.get(EC.RATIO),
            "industry_code": run_options.industry_code,
            "company_size_bucket": run_options.company_size_bucket,
        }
    elif engine_code is EC.HEALTH_SCORE:
        payload = {
            "ratio_fingerprint": up.get(EC.RATIO),
            "benchmark_fingerprint": up.get(EC.BENCHMARK),
            "industry_code": run_options.industry_code,
            "company_size_bucket": run_options.company_size_bucket,
            "tenant_id": run_options.tenant_id,
        }
    elif engine_code is EC.CREDIT_SCORE:
        payload = {
            "ratio_fingerprint": up.get(EC.RATIO),
            "benchmark_fingerprint": up.get(EC.BENCHMARK),
            "health_score_fingerprint": up.get(EC.HEALTH_SCORE),
            "industry_code": run_options.industry_code,
            "company_size_bucket": run_options.company_size_bucket,
            "tenant_id": run_options.tenant_id,
        }
    elif engine_code is EC.RECOMMENDATION:
        payload = {
            "ratio_fingerprint": up.get(EC.RATIO),
            "benchmark_fingerprint": up.get(EC.BENCHMARK),
            "health_score_fingerprint": up.get(EC.HEALTH_SCORE),
            "credit_score_fingerprint": up.get(EC.CREDIT_SCORE),
            "industry_code": run_options.industry_code,
            "company_size_bucket": run_options.company_size_bucket,
            "tenant_id": run_options.tenant_id,
        }
    elif engine_code is EC.EXECUTIVE_REPORT:
        payload = {
            "fs_balance_sheet_fingerprint": up.get(EC.FS_BALANCE_SHEET),
            "fs_income_statement_fingerprint": up.get(EC.FS_INCOME_STATEMENT),
            "ratio_fingerprint": up.get(EC.RATIO),
            "benchmark_fingerprint": up.get(EC.BENCHMARK),
            "health_score_fingerprint": up.get(EC.HEALTH_SCORE),
            "credit_score_fingerprint": up.get(EC.CREDIT_SCORE),
            "recommendation_fingerprint": up.get(EC.RECOMMENDATION),
            "report_type": run_options.report_type,
            "optional_sections": run_options.optional_sections,
            "locale": run_options.locale,
            "currency_display_policy": run_options.currency_display_policy,
            "company_metadata": run_options.company_metadata,
            "reporting_period_label_tr": run_options.reporting_period_label_tr,
        }
    elif engine_code is EC.DASHBOARD:
        payload = {
            "health_score_fingerprint": up.get(EC.HEALTH_SCORE),
            "credit_score_fingerprint": up.get(EC.CREDIT_SCORE),
            "recommendation_fingerprint": up.get(EC.RECOMMENDATION),
            "benchmark_fingerprint": up.get(EC.BENCHMARK),
            "dashboard_type": run_options.dashboard_type,
            "company_metadata": run_options.company_metadata,
        }
    elif engine_code is EC.RENDER_CONTRACT:
        payload = {
            "executive_report_fingerprint": up.get(EC.EXECUTIVE_REPORT),
            "render_contract": run_options.render_contract,
        }
    else:  # pragma: no cover -- yeni bir EngineCode eklenirse burada patlar
        raise ValueError(f"Bilinmeyen engine_code: {engine_code!r}")

    return canonical_hash(payload)


__all__ = [
    "FINGERPRINT_SCHEMA_VERSION",
    "canonical_hash",
    "compute_engine_input_fingerprint",
]
