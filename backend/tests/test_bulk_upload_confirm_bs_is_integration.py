"""
Milestone 4.2 (Balance Sheet + Income Statement Engine) -- confirm_bulk_upload
akışının Balance Sheet/Income Statement motorlarıyla GERÇEK entegrasyonu
(SQLite tabanlı API testleri, test_bulk_upload_api.py'deki AYNI konvansiyon
ve fixture'lar).

Bu dosya app.services.bulk_upload'ın FAZ 2 dependency-aware orkestrasyonunu
(trial_balance ÖNCE, aynı-batch Balance Sheet/Income Statement item'larının
context.trial_balance_pending_in_batch=True ile sonucu tüketmesi) ve FAZ
3'ün financial_analysis_result_sources satırlarını (hem DB'den önceden
okunmuş hem aynı-batch ertelenmiş kaynaklar için) doğru yazdığını, onaylanan
Milestone 4.2 kararı #5'teki senaryo listesine göre kapsar:
  - aynı-batch trial_balance + balance_sheet birlikte onaylanır
  - doğrudan belge başarılıysa trial_balance yalnızca supporting_analysis
    olarak eklenir (source_mode=direct_document)
  - gerçek source_analysis_result_id, FAZ 3 sonrası trial_balance'ın
    GERÇEK persisted id'sine işaret eder
  - yalnızca başarısız/tanınmayan BS belgesi + başarılı trial_balance ->
    trial_balance_derived fallback (role=trial_balance_fallback)
  - batch ortasında bir motor başarısız olursa HİÇBİR belge/analiz/kaynak
    satırı yazılmaz (tüm-ya-da-hiçbiri korunur)

SQLAlchemy/FastAPI gerektirdiği için bu sandbox'ta GERÇEKTEN çalıştırılamadı
(bkz. tests/README.md) -- yalnızca `python3 -m py_compile` ile sözdizimi
kontrolünden ve mevcut test_bulk_upload_api.py konvansiyonlarıyla elle
çapraz kontrolden geçirildi. Yerelde çalıştırmak için:
    pytest tests/test_bulk_upload_confirm_bs_is_integration.py -v
"""

import io
import json
from pathlib import Path

import pandas as pd


FIXTURES_DIR = Path(__file__).parent / "data" / "synthetic"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _read_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


# --- test_bulk_upload_api.py'deki AYNI küçük yardımcıların bilinçli kopyası
# -- bu test dosyaları arasında (tests/__init__.py yokken kırılgan olacak
# `tests.` paket importu yerine) mevcut kod tabanı konvansiyonu her test
# dosyasının kendi kendine yeterli (self-contained) olmasıdır (bkz. diğer
# tüm tests/test_*.py dosyaları -- hiçbiri başka bir test dosyasından import
# etmez).


def _upload(client, file_tuples):
    return client.post(
        "/api/v1/bulk-uploads",
        files=[("files", (name, content, mime)) for name, content, mime in file_tuples],
    )


def _item_by_filename(body, filename):
    matches = [item for item in body["items"] if item["original_filename"] == filename]
    assert len(matches) == 1, f"{filename} tam olarak bir kez bulunmalı"
    return matches[0]


def _confirm(client, batch_id, manifest_entries, file_parts):
    return client.post(
        f"/api/v1/bulk-uploads/{batch_id}/confirm",
        data={"manifest": json.dumps(manifest_entries)},
        files=[("files", (item_id, content, mime)) for item_id, content, mime in file_parts],
    )


def _new_company_resolution(tax_number: str, legal_name: str = "Confirm Test A.Ş.") -> dict:
    return {
        "mode": "new",
        "legal_name": legal_name,
        "tax_number": tax_number,
        "currency": "TRY",
    }


def _new_period_resolution(year: int = 2025) -> dict:
    return {
        "mode": "new",
        "year": year,
        "period_type": "year_end",
        "period_number": 4,
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "months_covered": 12,
        "is_year_end": True,
    }


def _synthetic_balanced_xlsx(seed: int = 0) -> bytes:
    debit = 50000 + seed
    rows = [
        {"Hesap Kodu": "100", "Hesap Adı": "KASA", "Borç Tutarı": debit, "Alacak Tutarı": 0},
        {"Hesap Kodu": "320", "Hesap Adı": "SATICILAR", "Borç Tutarı": 0, "Alacak Tutarı": debit},
    ]
    dataframe = pd.DataFrame(rows)
    buffer = io.BytesIO()
    dataframe.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()


def _patch_accept(client, batch_id, item_id, *, tax_number, document_type, year=2025):
    response = client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items/{item_id}",
        json={
            "company": _new_company_resolution(tax_number),
            "period": _new_period_resolution(year),
            "document_type": document_type,
            "decision": "accepted",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _get_sources_for_analysis(db_session, analysis_result_id):
    """
    Kök neden notu (Milestone 4.2 hotfix): `analysis_result_id` bu dosyada
    HER ZAMAN bir HTTP JSON yanıtından (`confirm_response.json()[...]`)
    geliyor -- FastAPI/Pydantic UUID alanlarını yanıtta STRING olarak
    serialize eder. Bu string'i doğrudan bir `Uuid(as_uuid=True)` kolonuna
    karşı filtrelemek (`== analysis_result_id`) SQLAlchemy'nin bind
    processor'ında `'str' object has no attribute 'hex'` hatasına yol açar
    -- bu, app/services/bulk_upload.py'nin YAZDIĞI değerin yanlış tipte
    olmasından DEĞİL, bu TEST YARDIMCISININ okuma tarafında JSON string'i
    gerçek bir `uuid.UUID`'ye çevirmeden sorgulamasından kaynaklanıyordu.
    Düzeltme: DB'ye giden HER karşılaştırmadan önce açıkça `uuid.UUID(...)`.
    """

    import uuid as uuid_module

    from app.models.financial_analysis_result_source import FinancialAnalysisResultSource

    if not isinstance(analysis_result_id, uuid_module.UUID):
        analysis_result_id = uuid_module.UUID(str(analysis_result_id))

    return (
        db_session.query(FinancialAnalysisResultSource)
        .filter(FinancialAnalysisResultSource.analysis_result_id == analysis_result_id)
        .all()
    )


# --- Aynı-batch trial_balance + balance_sheet -------------------------------


def test_confirm_same_batch_trial_balance_and_balance_sheet_direct_authoritative(
    client, db_session
):
    """Aynı confirm çağrısında trial_balance + balance_sheet (BAŞARIYLA
    ayrıştırılabilen) birlikte onaylanırsa: balance_sheet source_mode=
    direct_document kalmalı, trial_balance yalnızca supporting_analysis
    olarak (reconciliation için) eklenmeli -- ve gerçek source_analysis_
    result_id, FAZ 3'te trial_balance flush edildikten SONRA üretilen
    GERÇEK id olmalı (sahte/uydurma bir UUID DEĞİL)."""

    tb_content = _read_fixture("synthetic_trial_balance_matched_bs_is.xlsx")
    bs_content = _read_fixture("synthetic_balance_sheet_direct.xlsx")

    upload_response = _upload(
        client,
        [("mizan.xlsx", tb_content, XLSX_MIME), ("bilanco.xlsx", bs_content, XLSX_MIME)],
    )
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    tb_item = _item_by_filename(body, "mizan.xlsx")
    bs_item = _item_by_filename(body, "bilanco.xlsx")

    tax_number = "SAMEBATCH-BS-0001"
    _patch_accept(client, batch_id, tb_item["id"], tax_number=tax_number, document_type="trial_balance")
    _patch_accept(client, batch_id, bs_item["id"], tax_number=tax_number, document_type="balance_sheet")

    confirm_response = _confirm(
        client,
        batch_id,
        manifest_entries=[
            {"item_id": tb_item["id"], "original_filename": "mizan.xlsx"},
            {"item_id": bs_item["id"], "original_filename": "bilanco.xlsx"},
        ],
        file_parts=[
            (tb_item["id"], tb_content, XLSX_MIME),
            (bs_item["id"], bs_content, XLSX_MIME),
        ],
    )

    assert confirm_response.status_code == 200, confirm_response.text
    summary = confirm_response.json()
    assert summary["status"] == "confirmed"
    assert summary["created_analysis_count"] == 2
    # Aynı yeni firma+dönemi paylaştıkları için find-or-create ikinci
    # item'da REUSE etmeli.
    assert summary["created_company_count"] == 1
    assert summary["created_period_count"] == 1

    results_by_item = {r["item_id"]: r for r in summary["items"]}
    tb_analysis_id = results_by_item[tb_item["id"]]["resulting_analysis_id"]
    bs_analysis_id = results_by_item[bs_item["id"]]["resulting_analysis_id"]
    assert tb_analysis_id is not None
    assert bs_analysis_id is not None

    bs_analysis = client.get(f"/api/v1/analyses/{bs_analysis_id}").json()
    assert bs_analysis["result_json"]["source_mode"] == "direct_document"
    reconciliation = bs_analysis["result_json"]["reconciliation"]
    assert reconciliation["compared_against"] == "trial_balance"
    assert reconciliation["performed"] is True
    assert reconciliation["within_tolerance"] is True
    assert reconciliation["material_difference"] is False
    assert reconciliation["differences"] == []

    sources = _get_sources_for_analysis(db_session, bs_analysis_id)
    assert len(sources) == 1
    assert sources[0].role.value == "supporting_analysis"
    assert sources[0].source_document_id is None
    # KRİTİK: gerçek, FAZ 3'te üretilmiş trial_balance analysis id'sine
    # işaret etmeli -- sahte/uydurma bir UUID DEĞİL.
    assert str(sources[0].source_analysis_result_id) == tb_analysis_id


def test_confirm_same_batch_unrecognized_balance_sheet_falls_back_to_trial_balance(
    client, db_session
):
    """Aynı batch'te trial_balance BAŞARILI ama balance_sheet belgesi
    TANINAMIYORSA (extractor hiçbir alan bulamıyor): balance_sheet motoru
    hâlâ COMPLETED dönmeli (trial_balance_derived fallback), source_mode=
    trial_balance_derived, role=trial_balance_fallback, ve source id yine
    aynı-batch'teki GERÇEK trial_balance analiz sonucuna işaret etmeli."""

    tb_content = _read_fixture("synthetic_trial_balance_matched_bs_is.xlsx")
    unrecognized_content = b"bu bir bilanco degil, tanimlanamayan rastgele icerik"

    upload_response = _upload(
        client,
        [
            ("mizan.xlsx", tb_content, XLSX_MIME),
            ("bos_bilanco.xlsx", unrecognized_content, XLSX_MIME),
        ],
    )
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    tb_item = _item_by_filename(body, "mizan.xlsx")
    bs_item = _item_by_filename(body, "bos_bilanco.xlsx")

    tax_number = "SAMEBATCH-FALLBACK-0001"
    _patch_accept(client, batch_id, tb_item["id"], tax_number=tax_number, document_type="trial_balance")
    _patch_accept(client, batch_id, bs_item["id"], tax_number=tax_number, document_type="balance_sheet")

    confirm_response = _confirm(
        client,
        batch_id,
        manifest_entries=[
            {"item_id": tb_item["id"], "original_filename": "mizan.xlsx"},
            {"item_id": bs_item["id"], "original_filename": "bos_bilanco.xlsx"},
        ],
        file_parts=[
            (tb_item["id"], tb_content, XLSX_MIME),
            (bs_item["id"], unrecognized_content, XLSX_MIME),
        ],
    )

    assert confirm_response.status_code == 200, confirm_response.text
    summary = confirm_response.json()
    results_by_item = {r["item_id"]: r for r in summary["items"]}
    tb_analysis_id = results_by_item[tb_item["id"]]["resulting_analysis_id"]
    bs_analysis_id = results_by_item[bs_item["id"]]["resulting_analysis_id"]
    assert tb_analysis_id is not None
    assert bs_analysis_id is not None

    bs_analysis = client.get(f"/api/v1/analyses/{bs_analysis_id}").json()
    assert bs_analysis["result_json"]["source_mode"] == "trial_balance_derived"
    # Fallback yolunda İKİ kaynak KARŞILAŞTIRILMIYOR -- trial_balance TEK
    # kaynak olarak kullanıldı, bu bir reconciliation değil.
    reconciliation = bs_analysis["result_json"]["reconciliation"]
    assert reconciliation["performed"] is False
    assert reconciliation["within_tolerance"] is None
    assert reconciliation["material_difference"] is None
    assert reconciliation["differences"] == []

    sources = _get_sources_for_analysis(db_session, bs_analysis_id)
    assert len(sources) == 1
    assert sources[0].role.value == "trial_balance_fallback"
    assert str(sources[0].source_analysis_result_id) == tb_analysis_id


def test_confirm_balance_sheet_uses_preexisting_db_trial_balance_across_batches(
    client, db_session
):
    """Aynı-batch DEĞİL -- önce bir mizan ayrı bir confirm çağrısıyla
    onaylanır (DB'ye gerçekten yazılır), SONRA farklı bir batch'te AYNI
    firma+dönem için bir balance_sheet onaylanır. Motor, DB'deki ÖNCEDEN
    var olan COMPLETED trial_balance sonucunu (FAZ 1'de okunmuş) kaynak
    olarak kullanmalı."""

    tax_number = "CROSSBATCH-BS-0001"
    tb_content = _read_fixture("synthetic_trial_balance_matched_bs_is.xlsx")

    first_upload = _upload(client, [("mizan.xlsx", tb_content, XLSX_MIME)])
    first_body = first_upload.json()
    first_batch_id = first_body["batch"]["id"]
    tb_item = _item_by_filename(first_body, "mizan.xlsx")
    _patch_accept(client, first_batch_id, tb_item["id"], tax_number=tax_number, document_type="trial_balance")
    first_confirm = _confirm(
        client,
        first_batch_id,
        manifest_entries=[{"item_id": tb_item["id"], "original_filename": "mizan.xlsx"}],
        file_parts=[(tb_item["id"], tb_content, XLSX_MIME)],
    )
    assert first_confirm.status_code == 200, first_confirm.text
    tb_analysis_id = first_confirm.json()["items"][0]["resulting_analysis_id"]
    assert tb_analysis_id is not None

    bs_content = _read_fixture("synthetic_balance_sheet_direct.xlsx")
    second_upload = _upload(client, [("bilanco.xlsx", bs_content, XLSX_MIME)])
    second_body = second_upload.json()
    second_batch_id = second_body["batch"]["id"]
    bs_item = _item_by_filename(second_body, "bilanco.xlsx")
    _patch_accept(client, second_batch_id, bs_item["id"], tax_number=tax_number, document_type="balance_sheet")

    second_confirm = _confirm(
        client,
        second_batch_id,
        manifest_entries=[{"item_id": bs_item["id"], "original_filename": "bilanco.xlsx"}],
        file_parts=[(bs_item["id"], bs_content, XLSX_MIME)],
    )
    assert second_confirm.status_code == 200, second_confirm.text
    bs_analysis_id = second_confirm.json()["items"][0]["resulting_analysis_id"]
    assert bs_analysis_id is not None

    bs_analysis = client.get(f"/api/v1/analyses/{bs_analysis_id}").json()
    assert bs_analysis["result_json"]["source_mode"] == "direct_document"
    reconciliation = bs_analysis["result_json"]["reconciliation"]
    assert reconciliation["performed"] is True
    assert reconciliation["within_tolerance"] is True
    assert reconciliation["material_difference"] is False

    sources = _get_sources_for_analysis(db_session, bs_analysis_id)
    assert len(sources) == 1
    assert sources[0].role.value == "supporting_analysis"
    assert str(sources[0].source_analysis_result_id) == tb_analysis_id


# --- Tüm-ya-da-hiçbiri: batch ortasında motor başarısızlığı ----------------


def test_confirm_mid_batch_income_statement_failure_writes_nothing(client):
    """Aynı batch'te bir trial_balance BAŞARILI olsa bile, bir income_statement
    item'ı ENGINE_FAILED dönerse (tanınamayan içerik + trial_balance fallback
    YOK -- farklı firma/dönem) TÜM confirm çağrısı reddedilmeli ve trial_balance
    dahil HİÇBİR belge/analiz/kaynak satırı yazılmamalı (mevcut all-or-nothing
    davranışı korunur)."""

    tb_content = _synthetic_balanced_xlsx(seed=99)
    unrecognized_is_content = b"tanimlanamayan, rastgele gelir tablosu icerigi"

    upload_response = _upload(
        client,
        [
            ("mizan.xlsx", tb_content, XLSX_MIME),
            ("gelir_tablosu.xlsx", unrecognized_is_content, XLSX_MIME),
        ],
    )
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    tb_item = _item_by_filename(body, "mizan.xlsx")
    is_item = _item_by_filename(body, "gelir_tablosu.xlsx")

    # BİLEREK FARKLI firma/dönem -- income_statement item'ının trial_balance
    # fallback'i YOK (ne aynı-batch ne DB'de).
    _patch_accept(
        client, batch_id, tb_item["id"],
        tax_number="MIDBATCH-FAIL-TB-0001", document_type="trial_balance",
    )
    _patch_accept(
        client, batch_id, is_item["id"],
        tax_number="MIDBATCH-FAIL-IS-0002", document_type="income_statement", year=2026,
    )

    companies_before = client.get("/api/v1/companies").json()["total"]

    confirm_response = _confirm(
        client,
        batch_id,
        manifest_entries=[
            {"item_id": tb_item["id"], "original_filename": "mizan.xlsx"},
            {"item_id": is_item["id"], "original_filename": "gelir_tablosu.xlsx"},
        ],
        file_parts=[
            (tb_item["id"], tb_content, XLSX_MIME),
            (is_item["id"], unrecognized_is_content, XLSX_MIME),
        ],
    )

    assert confirm_response.status_code == 422, confirm_response.text
    errors = confirm_response.json()["detail"]["errors"]
    assert any(e["code"] == "ENGINE_FAILED" and e["item_id"] == is_item["id"] for e in errors)

    companies_after = client.get("/api/v1/companies").json()["total"]
    assert companies_after == companies_before  # trial_balance dahil HICBIR sey yazilmadi

    batch_get = client.get(f"/api/v1/bulk-uploads/{batch_id}").json()
    assert batch_get["status"] == "completed"  # confirmed OLMADI

    for item_id in (tb_item["id"], is_item["id"]):
        item_get = next(
            i for i in client.get(f"/api/v1/bulk-uploads/{batch_id}/items").json()["items"]
            if i["id"] == item_id
        )
        assert item_get["resulting_document_id"] is None
        assert item_get["resulting_analysis_id"] is None


# --- Income Statement: doğrudan onay + EBIT_NOT_DETERMINABLE surfacing ----


def test_confirm_income_statement_direct_document(client):
    is_content = _read_fixture("synthetic_income_statement_direct.xlsx")

    upload_response = _upload(client, [("gelir_tablosu.xlsx", is_content, XLSX_MIME)])
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    is_item = _item_by_filename(body, "gelir_tablosu.xlsx")

    _patch_accept(
        client, batch_id, is_item["id"],
        tax_number="IS-DIRECT-ONLY-0001", document_type="income_statement",
    )

    confirm_response = _confirm(
        client,
        batch_id,
        manifest_entries=[{"item_id": is_item["id"], "original_filename": "gelir_tablosu.xlsx"}],
        file_parts=[(is_item["id"], is_content, XLSX_MIME)],
    )

    assert confirm_response.status_code == 200, confirm_response.text
    summary = confirm_response.json()
    analysis_id = summary["items"][0]["resulting_analysis_id"]
    assert analysis_id is not None

    analysis = client.get(f"/api/v1/analyses/{analysis_id}").json()
    result_json = analysis["result_json"]
    assert result_json["source_mode"] == "direct_document"
    assert result_json["facts"]["ebit"] is None
    assert any(w["code"] == "EBIT_NOT_DETERMINABLE" for w in result_json["warnings"])
    # operating_profit ayrı, dolu kalmalı -- ebit'e sessizce eşitlenmedi.
    assert result_json["facts"]["operating_profit"] == 122000.0
