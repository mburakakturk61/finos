"""
app.engines.protocol/app.engines.registry için gerçek, çalıştırılabilir
birim testleri (Milestone 4.1 -- Analysis Foundation).

Bu dosya yalnızca pandas'a (TrialBalanceEngineAdapter'ın sarmaladığı
analyze_trial_balance dolayısıyla) ve stdlib'e bağımlıdır -- sqlalchemy/
fastapi/pydantic'e DEĞİL, bu yüzden app/trial_balance/** ve app/classification/**
testleri gibi kısıtlı ortamlarda da çalıştırılabilir.

app/trial_balance/**'e bu dosyada hiçbir şekilde dokunulmadı/değiştirilmedi
-- yalnızca mevcut PUBLIC analyze_trial_balance fonksiyonu, TrialBalanceEngineAdapter
üzerinden çağrılıyor (app/services/bulk_upload.py ve
app/services/trial_balance_upload.py'nin bugün zaten yaptığı gibi).
"""

import uuid
from decimal import Decimal
from io import BytesIO

import pandas as pd

from app.engines.protocol import EngineAdapter, EngineRunContext, EngineSourceRef
from app.engines.registry import (
    TrialBalanceEngineAdapter,
    get_engine_for_analysis_type,
    get_engine_for_detected_type,
    get_engine_for_document_type,
)
from app.models.enums import (
    AnalysisSourceRole,
    AnalysisStatus,
    AnalysisType,
    DetectedDocumentType,
    DocumentType,
    SourceMode,
)


def _build_synthetic_trial_balance_bytes() -> bytes:
    """test_trial_balance_regression.py'deki AYNI sentetik, tamamen
    kurgusal, denk mizan üretimi -- gerçek veri asla yok."""

    rows = [
        {"Hesap Kodu": "100", "Hesap Adı": "KASA", "Borç Tutarı": 50000, "Alacak Tutarı": 0},
        {"Hesap Kodu": "120", "Hesap Adı": "ALICILAR", "Borç Tutarı": 30000, "Alacak Tutarı": 0},
        {"Hesap Kodu": "320", "Hesap Adı": "SATICILAR", "Borç Tutarı": 0, "Alacak Tutarı": 30000},
        {"Hesap Kodu": "500", "Hesap Adı": "SERMAYE", "Borç Tutarı": 0, "Alacak Tutarı": 50000},
    ]

    dataframe = pd.DataFrame(rows)
    buffer = BytesIO()
    dataframe.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()


def _build_context() -> EngineRunContext:
    return EngineRunContext(company_id=uuid.uuid4(), period_id=uuid.uuid4())


# --- EngineSourceRef: XOR kuralı (Python seviyesinde erken doğrulama) -----


def test_engine_source_ref_accepts_document_only():
    ref = EngineSourceRef(role=AnalysisSourceRole.PRIMARY_DOCUMENT, document_id=uuid.uuid4())
    assert ref.document_id is not None
    assert ref.analysis_result_id is None


def test_engine_source_ref_accepts_analysis_only():
    ref = EngineSourceRef(
        role=AnalysisSourceRole.TRIAL_BALANCE_FALLBACK, analysis_result_id=uuid.uuid4()
    )
    assert ref.analysis_result_id is not None
    assert ref.document_id is None


def test_engine_source_ref_rejects_both_filled():
    try:
        EngineSourceRef(
            role=AnalysisSourceRole.PRIOR_PERIOD_REFERENCE,
            document_id=uuid.uuid4(),
            analysis_result_id=uuid.uuid4(),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("İkisi de dolu iken ValueError bekleniyordu.")


def test_engine_source_ref_rejects_both_empty():
    try:
        EngineSourceRef(role=AnalysisSourceRole.PRIOR_PERIOD_REFERENCE)
    except ValueError:
        pass
    else:
        raise AssertionError("İkisi de boşken ValueError bekleniyordu.")


# --- TrialBalanceEngineAdapter: gerçek analyze_trial_balance çağrısı ------


def test_trial_balance_adapter_matches_protocol():
    adapter = TrialBalanceEngineAdapter()
    assert isinstance(adapter, EngineAdapter)
    assert adapter.analysis_type == AnalysisType.TRIAL_BALANCE
    assert adapter.requires_content is True


def test_trial_balance_adapter_runs_real_engine_and_succeeds():
    adapter = TrialBalanceEngineAdapter()
    content = _build_synthetic_trial_balance_bytes()

    result = adapter.run(content=content, filename="synthetic.xlsx", context=_build_context())

    assert result.analysis_type == AnalysisType.TRIAL_BALANCE
    assert result.source_mode == SourceMode.DIRECT_DOCUMENT
    assert result.status == AnalysisStatus.COMPLETED
    assert result.error_message is None
    assert result.result_json is not None
    assert result.result_json["status"] == "VALID"

    total_debit = Decimal(str(result.result_json["totals"]["total_debit"]))
    assert total_debit == Decimal("80000.00")


def test_trial_balance_adapter_reports_engine_failure_without_raising():
    adapter = TrialBalanceEngineAdapter()

    # Gecerli bir .xlsx olmayan rastgele baytlar -- motorun ValueError/
    # Exception uretmesini bekliyoruz; adapter bunu YUTMAMALI, FAILED
    # olarak raporlamalı (bkz. app/services/bulk_upload.py'deki ENGINE_FAILED
    # kodunun aynı felsefesi).
    garbage_content = b"bu gecerli bir xlsx dosyasi degil"

    result = adapter.run(content=garbage_content, filename="bozuk.xlsx", context=_build_context())

    assert result.status == AnalysisStatus.FAILED
    assert result.result_json is None
    assert result.error_message is not None


def test_trial_balance_adapter_requires_content():
    adapter = TrialBalanceEngineAdapter()

    try:
        adapter.run(content=None, filename="yok.xlsx", context=_build_context())
    except ValueError:
        pass
    else:
        raise AssertionError("content=None iken ValueError bekleniyordu.")


# --- Registry: iki enum dünyasından da AYNI adaptöre erişim --------------


def test_registry_finds_trial_balance_via_detected_type():
    adapter = get_engine_for_detected_type(DetectedDocumentType.TRIAL_BALANCE)
    assert adapter is not None
    assert adapter.analysis_type == AnalysisType.TRIAL_BALANCE


def test_registry_finds_trial_balance_via_document_type():
    adapter = get_engine_for_document_type(DocumentType.TRIAL_BALANCE)
    assert adapter is not None
    assert adapter.analysis_type == AnalysisType.TRIAL_BALANCE


def test_registry_finds_trial_balance_via_analysis_type_directly():
    adapter = get_engine_for_analysis_type(AnalysisType.TRIAL_BALANCE)
    assert adapter is not None
    assert isinstance(adapter, TrialBalanceEngineAdapter)


def test_registry_returns_none_for_unregistered_detected_types():
    # Milestone 4.1'de trial_balance DIŞINDA hiçbir DetectedDocumentType
    # kayıtlı değil -- 4.2/4.4/4.5 doldurana kadar hepsi güvenle None
    # dönmeli.
    for detected_type in DetectedDocumentType:
        if detected_type == DetectedDocumentType.TRIAL_BALANCE:
            continue
        assert get_engine_for_detected_type(detected_type) is None, detected_type


def test_registry_returns_none_for_unregistered_document_types():
    for document_type in DocumentType:
        if document_type == DocumentType.TRIAL_BALANCE:
            continue
        assert get_engine_for_document_type(document_type) is None, document_type


def test_registry_returns_none_for_unregistered_analysis_types():
    for analysis_type in AnalysisType:
        if analysis_type == AnalysisType.TRIAL_BALANCE:
            continue
        assert get_engine_for_analysis_type(analysis_type) is None, analysis_type


# --- Kapsam sınırı koruması: registry, üretim dispatch'ine BAĞLI DEĞİL ----


def test_registry_not_wired_into_bulk_upload_service():
    """
    Onaylanan Milestone 4.1 kararı #1: registry, bu adımda
    app/services/bulk_upload.py'nin gerçek dispatch akışına BAĞLANMADI.
    Bu test, o kararın gelecekte (4.2 öncesi) yanlışlıkla ihlal
    edilmediğini -- app/services/bulk_upload.py'nin app.engines paketinden
    HİÇBİR ŞEY import etmediğini -- kaynak metni okuyarak doğrular.
    """

    import pathlib

    bulk_upload_path = (
        pathlib.Path(__file__).parent.parent / "app" / "services" / "bulk_upload.py"
    )
    source = bulk_upload_path.read_text(encoding="utf-8")
    assert "app.engines" not in source, (
        "app/services/bulk_upload.py artik app.engines'i import ediyor -- "
        "bu, Milestone 4.1'in 'registry henuz gercek dispatch'e baglanmadi' "
        "kararinin degistigi anlamina gelir. Eger bu kasitliyse (Milestone "
        "4.2), bu testin kendisi de güncellenmeli/kaldirilmali."
    )


def test_trial_balance_upload_service_not_wired_to_registry():
    import pathlib

    path = (
        pathlib.Path(__file__).parent.parent
        / "app"
        / "services"
        / "trial_balance_upload.py"
    )
    source = path.read_text(encoding="utf-8")
    assert "app.engines" not in source
