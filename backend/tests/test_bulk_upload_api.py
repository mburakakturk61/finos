"""
POST /api/v1/bulk-uploads ve okuma endpointleri için SQLite tabanlı API
testleri (Milestone 2 / Adım 3).

Yalnızca committed sentetik fixture'lar (backend/tests/data/synthetic/)
ve bellek içi üretilen/düz metin içerikler kullanılır --
backend/tests/data/generic/2024_detay_mizan.xlsx (gerçek veri) hiçbir
testte kullanılmaz.

Bu katman bir sınıflandırma ÖNİZLEMESİDİR -- hiçbir testte fiziksel dosya
saklanmadığı, yalnızca metadata + tahminlerin kalıcı olduğu doğrulanır
(item response'unda dosya İÇERİĞİ hiçbir alanda yer almaz).
"""

import hashlib
import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.services.bulk_upload import BulkUploadValidationError, handle_bulk_upload


FIXTURES_DIR = Path(__file__).parent / "data" / "synthetic"


def _read_fixture(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _upload(client, file_tuples):
    """file_tuples: list[(filename, content, mime)]"""

    return client.post(
        "/api/v1/bulk-uploads",
        files=[("files", (name, content, mime)) for name, content, mime in file_tuples],
    )


def _item_by_filename(body, filename):
    matches = [item for item in body["items"] if item["original_filename"] == filename]
    assert len(matches) == 1, f"{filename} tam olarak bir kez bulunmalı"
    return matches[0]


PDF_MIME = "application/pdf"
XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _synthetic_balanced_xlsx(seed: int = 0) -> bytes:
    """Denk (debit == credit), tamamen kurgusal bir mizan -- firma/dönem
    kimliği İÇERMEZ (yalnızca kolon yapısına bakılarak trial_balance
    olarak sınıflandırılır, auto_matched OLMAZ -- manuel PATCH gerektirir,
    bkz. Milestone 3 / Adım 1 confirm testleri)."""

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


def _synthetic_empty_dataframe_xlsx() -> bytes:
    """Zorunlu kolon başlıkları var ama hiç veri satırı yok. classify_file
    yalnızca başlıklara baktığı için bunu yine TRIAL_BALANCE olarak
    tanır -- ama analyze_trial_balance motoru boş dataframe için
    ValueError fırlatır. Confirm'in FAZ 2'sinde "preflight geçti ama
    motor patladı, hiçbir şey yazılmadı" senaryosunu test etmek için
    kullanılır."""

    dataframe = pd.DataFrame(
        columns=["Hesap Kodu", "Hesap Adı", "Borç Tutarı", "Alacak Tutarı"]
    )
    buffer = io.BytesIO()
    dataframe.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer.read()


def _confirm(client, batch_id, manifest_entries, file_parts):
    """manifest_entries: list[dict(item_id=..., original_filename=...)]
    file_parts: list[(item_id_str, content, mime)] -- multipart dosya
    parçasının adı (filename) İTEM_ID'NİN KENDİSİDİR (bkz. router
    docstring'i)."""

    return client.post(
        f"/api/v1/bulk-uploads/{batch_id}/confirm",
        data={"manifest": json.dumps(manifest_entries)},
        files=[
            ("files", (item_id, content, mime))
            for item_id, content, mime in file_parts
        ],
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


# --- Servis katmanı: HTTP'siz doğrudan doğrulama -------------------------


def test_handle_bulk_upload_no_files_raises_validation_error():
    with pytest.raises(BulkUploadValidationError):
        handle_bulk_upload(db=None, files=[])


# --- POST /api/v1/bulk-uploads -------------------------------------------


def test_create_bulk_upload_classifies_multiple_files(client):
    corporate = _read_fixture("synthetic_corporate_tax_return.pdf")
    temporary = _read_fixture("synthetic_temporary_tax_return.pdf")
    garbage = b"bu taninmayan, kurgusal, rastgele bir icerik"

    response = _upload(
        client,
        [
            ("kurumlar_vergisi.pdf", corporate, PDF_MIME),
            ("gecici_vergi.pdf", temporary, PDF_MIME),
            ("notlar.txt", garbage, "text/plain"),
        ],
    )

    assert response.status_code == 201
    body = response.json()

    assert body["batch"]["status"] == "completed"
    assert body["batch"]["total_file_count"] == 3
    assert body["batch"]["classified_file_count"] == 2
    assert body["batch"]["unclassified_file_count"] == 1
    assert body["batch"]["duplicate_file_count"] == 0

    corporate_item = _item_by_filename(body, "kurumlar_vergisi.pdf")
    assert corporate_item["detected_document_type"] == "corporate_tax_return"
    assert corporate_item["detected_tax_number"] == "1234567890"
    assert corporate_item["classification_status"] == "auto_matched"
    assert Decimal(str(corporate_item["confidence_score"])) >= Decimal("0.90")

    temporary_item = _item_by_filename(body, "gecici_vergi.pdf")
    assert temporary_item["detected_document_type"] == "temporary_tax_return"
    assert temporary_item["classification_status"] == "auto_matched"

    garbage_item = _item_by_filename(body, "notlar.txt")
    assert garbage_item["detected_document_type"] == "unknown"
    assert garbage_item["classification_status"] == "unrecognized"

    # Fiziksel dosya içeriği hiçbir alanda saklanmaz -- yalnızca metadata.
    for item in body["items"]:
        assert "content" not in item
        assert "file_content" not in item


def test_create_bulk_upload_within_batch_checksum_collision_is_duplicate(client):
    content = _read_fixture("synthetic_corporate_tax_return.pdf")

    response = _upload(
        client,
        [
            ("first.pdf", content, PDF_MIME),
            ("second.pdf", content, PDF_MIME),
        ],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["batch"]["duplicate_file_count"] == 1

    first_item = _item_by_filename(body, "first.pdf")
    second_item = _item_by_filename(body, "second.pdf")

    assert first_item["classification_status"] == "auto_matched"
    assert second_item["classification_status"] == "duplicate"
    warning_codes = {w["code"] for w in second_item["warnings_json"]}
    assert "DUPLICATE_WITHIN_BATCH" in warning_codes


def test_create_bulk_upload_possible_duplicate_across_completed_batches(client):
    """
    Aynı içerik (checksum) daha önce COMPLETED bir batch'te görüldüyse ve bu
    kez firma/dönem YÜKSEK güvenle tespit edilemiyorsa (bkz. bad_vkn
    fixture'ı -- identity_confidence 0.60 < 0.90 eşiği), sonuç KESİN değil
    possible_duplicate olmalıdır.
    """

    content = _read_fixture("synthetic_corporate_tax_return_bad_vkn.pdf")

    first_response = _upload(client, [("ilk_yukleme.pdf", content, PDF_MIME)])
    assert first_response.status_code == 201
    first_body = first_response.json()
    assert first_body["batch"]["status"] == "completed"
    first_item = _item_by_filename(first_body, "ilk_yukleme.pdf")
    assert first_item["classification_status"] == "needs_review"

    second_response = _upload(client, [("ikinci_yukleme.pdf", content, PDF_MIME)])
    assert second_response.status_code == 201
    second_body = second_response.json()
    second_item = _item_by_filename(second_body, "ikinci_yukleme.pdf")

    assert second_item["classification_status"] == "possible_duplicate"
    warning_codes = {w["code"] for w in second_item["warnings_json"]}
    assert "POSSIBLE_DUPLICATE_CHECKSUM_MATCH" in warning_codes


def test_create_bulk_upload_certain_duplicate_against_confirmed_document(client, db_session):
    """
    checksum, onaylanmış bir FinancialDocument ile eşleşiyor VE bu yükleme
    için firma+dönem YÜKSEK güvenle (>=0.90) tespit edildiyse (bkz. geçerli
    VKN'li kurumlar vergisi fixture'ı) sonuç KESİN duplicate olmalıdır.
    """

    from app.models.company import Company
    from app.models.enums import DocumentType, PeriodType, ProcessingStatus
    from app.models.financial_document import FinancialDocument
    from app.models.financial_period import FinancialPeriod

    content = _read_fixture("synthetic_corporate_tax_return.pdf")
    checksum = hashlib.sha256(content).hexdigest()

    company = Company(
        legal_name="Bulk Upload Dup Test A.Ş.",
        tax_number="BULKDUP-0001",
        currency="TRY",
    )
    db_session.add(company)
    db_session.commit()

    period = FinancialPeriod(
        company_id=company.id,
        year=2025,
        period_type=PeriodType.YEAR_END,
        period_number=4,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        months_covered=12,
        is_year_end=True,
    )
    db_session.add(period)
    db_session.commit()

    document = FinancialDocument(
        company_id=company.id,
        period_id=period.id,
        document_type=DocumentType.TAX_DECLARATION,
        original_filename="onceden_onaylanmis.pdf",
        mime_type=PDF_MIME,
        file_size=len(content),
        checksum=checksum,
        processing_status=ProcessingStatus.COMPLETED,
    )
    db_session.add(document)
    db_session.commit()

    response = _upload(client, [("yeniden_yuklenen.pdf", content, PDF_MIME)])

    assert response.status_code == 201
    body = response.json()
    item = _item_by_filename(body, "yeniden_yuklenen.pdf")

    assert item["classification_status"] == "duplicate"
    warning_codes = {w["code"] for w in item["warnings_json"]}
    assert "DUPLICATE_CHECKSUM_MATCH" in warning_codes


def test_create_bulk_upload_empty_file_is_unrecognized(client):
    response = _upload(client, [("bos_dosya.pdf", b"", PDF_MIME)])

    assert response.status_code == 201
    body = response.json()
    item = _item_by_filename(body, "bos_dosya.pdf")

    assert item["classification_status"] == "unrecognized"
    warning_codes = {w["code"] for w in item["warnings_json"]}
    assert "EMPTY_FILE" in warning_codes


# --- Okuma endpointleri ----------------------------------------------------


def test_get_bulk_upload_batch_success(client):
    corporate = _read_fixture("synthetic_corporate_tax_return.pdf")
    temporary = _read_fixture("synthetic_temporary_tax_return.pdf")

    create_response = _upload(
        client,
        [("a.pdf", corporate, PDF_MIME), ("b.pdf", temporary, PDF_MIME)],
    )
    batch_id = create_response.json()["batch"]["id"]

    response = client.get(f"/api/v1/bulk-uploads/{batch_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == batch_id
    assert body["status"] == "completed"
    assert body["total_file_count"] == 2


def test_get_bulk_upload_batch_not_found(client):
    random_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/bulk-uploads/{random_id}")
    assert response.status_code == 404


def test_list_bulk_upload_items_pagination(client):
    contents = [
        _read_fixture("synthetic_corporate_tax_return.pdf"),
        _read_fixture("synthetic_temporary_tax_return.pdf"),
        _read_fixture("synthetic_balance_sheet.pdf"),
    ]
    create_response = _upload(
        client,
        [(f"file_{i}.pdf", content, PDF_MIME) for i, content in enumerate(contents)],
    )
    batch_id = create_response.json()["batch"]["id"]

    response = client.get(
        f"/api/v1/bulk-uploads/{batch_id}/items",
        params={"limit": 2, "offset": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


def test_list_bulk_upload_items_batch_not_found(client):
    random_id = "00000000-0000-0000-0000-000000000000"
    response = client.get(f"/api/v1/bulk-uploads/{random_id}/items")
    assert response.status_code == 404


# =========================================================================
# Milestone 3 / Adım 1 -- review (PATCH) + confirm
# =========================================================================


# --- Auto-fill (auto_matched item'larda resolution_json ön-doldurması) --


def test_auto_matched_item_prefills_new_company_and_period(client):
    content = _read_fixture("synthetic_corporate_tax_return.pdf")
    response = _upload(client, [("kv.pdf", content, PDF_MIME)])
    item = _item_by_filename(response.json(), "kv.pdf")

    assert item["classification_status"] == "auto_matched"
    assert item["user_decision"] == "pending"
    resolution = item["resolution_json"]
    assert resolution is not None
    assert resolution["company"]["mode"] == "new"
    assert resolution["company"]["tax_number"] == "1234567890"
    assert resolution["period"]["mode"] == "new"
    assert resolution["period"]["year"] == 2025
    assert resolution["period"]["period_type"] == "year_end"
    assert resolution["document_type"] == "corporate_tax_return"


def test_auto_matched_item_prefills_existing_company_reference(client):
    create_company = client.post(
        "/api/v1/companies",
        json={
            "legal_name": "Önceden Var Olan A.Ş.",
            "tax_number": "1234567890",
            "currency": "TRY",
        },
    )
    assert create_company.status_code == 201
    company_id = create_company.json()["id"]

    content = _read_fixture("synthetic_corporate_tax_return.pdf")
    response = _upload(client, [("kv.pdf", content, PDF_MIME)])
    item = _item_by_filename(response.json(), "kv.pdf")

    resolution = item["resolution_json"]
    assert resolution["company"] == {"mode": "existing", "id": company_id}


# --- PATCH /api/v1/bulk-uploads/{batch_id}/items/{item_id} --------------


def test_patch_item_sets_resolution_and_accepts(client):
    content = _synthetic_balanced_xlsx(seed=1)
    response = _upload(client, [("mizan.xlsx", content, XLSX_MIME)])
    body = response.json()
    batch_id = body["batch"]["id"]
    item = _item_by_filename(body, "mizan.xlsx")
    assert item["classification_status"] == "needs_review"
    assert item["resolution_json"] is None

    patch_response = client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items/{item['id']}",
        json={
            "company": _new_company_resolution("PATCH-0001"),
            "period": _new_period_resolution(),
            "document_type": "trial_balance",
            "decision": "accepted",
        },
    )

    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["user_decision"] == "accepted"
    assert patched["resolution_json"]["company"]["tax_number"] == "PATCH-0001"


def test_patch_item_accept_without_resolution_returns_422(client):
    content = _synthetic_balanced_xlsx(seed=2)
    response = _upload(client, [("mizan.xlsx", content, XLSX_MIME)])
    body = response.json()
    batch_id = body["batch"]["id"]
    item = _item_by_filename(body, "mizan.xlsx")

    patch_response = client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items/{item['id']}",
        json={"decision": "accepted"},
    )

    assert patch_response.status_code == 422


def test_patch_item_invalid_existing_company_id_returns_422(client):
    content = _synthetic_balanced_xlsx(seed=3)
    response = _upload(client, [("mizan.xlsx", content, XLSX_MIME)])
    body = response.json()
    batch_id = body["batch"]["id"]
    item = _item_by_filename(body, "mizan.xlsx")

    random_id = "00000000-0000-0000-0000-000000000000"
    patch_response = client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items/{item['id']}",
        json={"company": {"mode": "existing", "id": random_id}},
    )

    assert patch_response.status_code == 422


def test_patch_item_not_found_returns_404(client):
    content = _synthetic_balanced_xlsx(seed=4)
    response = _upload(client, [("mizan.xlsx", content, XLSX_MIME)])
    batch_id = response.json()["batch"]["id"]

    random_id = "00000000-0000-0000-0000-000000000000"
    patch_response = client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items/{random_id}",
        json={"decision": "ignored"},
    )

    assert patch_response.status_code == 404


def test_patch_item_batch_not_found_returns_404(client):
    content = _synthetic_balanced_xlsx(seed=5)
    response = _upload(client, [("mizan.xlsx", content, XLSX_MIME)])
    item = _item_by_filename(response.json(), "mizan.xlsx")

    random_batch_id = "00000000-0000-0000-0000-000000000000"
    patch_response = client.patch(
        f"/api/v1/bulk-uploads/{random_batch_id}/items/{item['id']}",
        json={"decision": "ignored"},
    )

    assert patch_response.status_code == 404


# --- PATCH /api/v1/bulk-uploads/{batch_id}/items (toplu karar) ----------


def test_bulk_patch_decisions_partial_success(client):
    corporate = _read_fixture("synthetic_corporate_tax_return.pdf")
    xlsx_no_resolution = _synthetic_balanced_xlsx(seed=6)

    response = _upload(
        client,
        [
            ("kv.pdf", corporate, PDF_MIME),
            ("mizan.xlsx", xlsx_no_resolution, XLSX_MIME),
        ],
    )
    body = response.json()
    batch_id = body["batch"]["id"]
    auto_item = _item_by_filename(body, "kv.pdf")
    unresolved_item = _item_by_filename(body, "mizan.xlsx")
    random_item_id = "00000000-0000-0000-0000-000000000000"

    bulk_response = client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items",
        json={
            "items": [
                {"item_id": auto_item["id"], "decision": "accepted"},
                {"item_id": unresolved_item["id"], "decision": "accepted"},
                {"item_id": random_item_id, "decision": "accepted"},
            ]
        },
    )

    assert bulk_response.status_code == 200
    results = {r["item_id"]: r for r in bulk_response.json()["results"]}

    assert results[auto_item["id"]]["success"] is True
    assert results[auto_item["id"]]["user_decision"] == "accepted"

    assert results[unresolved_item["id"]]["success"] is False
    assert results[unresolved_item["id"]]["error"] is not None

    assert results[random_item_id]["success"] is False


def test_bulk_patch_batch_not_found_returns_404(client):
    random_batch_id = "00000000-0000-0000-0000-000000000000"
    response = client.patch(
        f"/api/v1/bulk-uploads/{random_batch_id}/items",
        json={"items": []},
    )
    assert response.status_code == 404


# --- POST /api/v1/bulk-uploads/{batch_id}/confirm -----------------------


def test_confirm_happy_path_creates_company_period_document_analysis(client):
    corporate = _read_fixture("synthetic_corporate_tax_return.pdf")
    xlsx_content = _synthetic_balanced_xlsx(seed=10)

    upload_response = _upload(
        client,
        [
            ("kv.pdf", corporate, PDF_MIME),
            ("mizan.xlsx", xlsx_content, XLSX_MIME),
        ],
    )
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    auto_item = _item_by_filename(body, "kv.pdf")
    xlsx_item = _item_by_filename(body, "mizan.xlsx")

    # auto_matched item: yalnızca toplu karar yeterli (resolution zaten dolu)
    bulk_patch = client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items",
        json={"items": [{"item_id": auto_item["id"], "decision": "accepted"}]},
    )
    assert bulk_patch.status_code == 200

    # trial_balance item: manuel çözüm gerekli
    patch_response = client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items/{xlsx_item['id']}",
        json={
            "company": _new_company_resolution("CONFIRM-HAPPY-0001"),
            "period": _new_period_resolution(2025),
            "document_type": "trial_balance",
            "decision": "accepted",
        },
    )
    assert patch_response.status_code == 200

    confirm_response = _confirm(
        client,
        batch_id,
        manifest_entries=[{"item_id": xlsx_item["id"], "original_filename": "mizan.xlsx"}],
        file_parts=[(xlsx_item["id"], xlsx_content, XLSX_MIME)],
    )

    assert confirm_response.status_code == 200
    summary = confirm_response.json()

    assert summary["batch_id"] == batch_id
    assert summary["status"] == "confirmed"
    assert summary["confirmed_at"] is not None
    assert summary["created_company_count"] == 2
    assert summary["reused_company_count"] == 0
    assert summary["created_period_count"] == 2
    assert summary["reused_period_count"] == 0
    assert summary["created_document_count"] == 2
    assert summary["created_analysis_count"] == 1
    assert summary["ignored_item_count"] == 0
    assert len(summary["items"]) == 2

    results_by_item = {r["item_id"]: r for r in summary["items"]}
    assert results_by_item[xlsx_item["id"]]["resulting_analysis_id"] is not None
    assert results_by_item[auto_item["id"]]["resulting_analysis_id"] is None
    for result in summary["items"]:
        assert result["resulting_company_id"] is not None
        assert result["resulting_period_id"] is not None
        assert result["resulting_document_id"] is not None

    # Batch/item durumları da tutarlı güncellenmiş olmalı.
    batch_get = client.get(f"/api/v1/bulk-uploads/{batch_id}").json()
    assert batch_get["status"] == "confirmed"
    assert batch_get["confirmed_at"] is not None

    items_get = client.get(f"/api/v1/bulk-uploads/{batch_id}/items").json()["items"]
    for item in items_get:
        assert item["resulting_document_id"] is not None

    # Üretilen FinancialDocument/FinancialAnalysisResult gerçekten GET
    # edilebiliyor mu (var mı) diye çapraz kontrol.
    document_get = client.get(
        f"/api/v1/documents/{results_by_item[xlsx_item['id']]['resulting_document_id']}"
    )
    assert document_get.status_code == 200
    assert document_get.json()["processing_status"] == "completed"

    analysis_get = client.get(
        f"/api/v1/analyses/{results_by_item[xlsx_item['id']]['resulting_analysis_id']}"
    )
    assert analysis_get.status_code == 200
    assert analysis_get.json()["result_json"]["status"] == "VALID"


def test_confirm_reuses_company_and_period_created_earlier_in_same_confirm(client):
    """İki farklı (checksum'ı farklı) item, AYNI yeni firma/dönem taslağını
    (aynı tax_number/year/period_type/period_number) işaret ediyorsa --
    ilk item firma+dönemi OLUŞTURUR, ikinci item AYNI confirm çağrısı
    içinde onu REUSE etmelidir (find-or-create'in kendi flush'ladığı
    kaydı görebildiğinin kanıtı)."""

    xlsx_a = _synthetic_balanced_xlsx(seed=20)
    xlsx_b = _synthetic_balanced_xlsx(seed=21)

    upload_response = _upload(
        client, [("a.xlsx", xlsx_a, XLSX_MIME), ("b.xlsx", xlsx_b, XLSX_MIME)]
    )
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    item_a = _item_by_filename(body, "a.xlsx")
    item_b = _item_by_filename(body, "b.xlsx")

    shared_company = _new_company_resolution("REUSE-SAME-CONFIRM-0001")
    shared_period = _new_period_resolution(2026)

    for item, content in ((item_a, xlsx_a), (item_b, xlsx_b)):
        patch_response = client.patch(
            f"/api/v1/bulk-uploads/{batch_id}/items/{item['id']}",
            json={
                "company": shared_company,
                "period": shared_period,
                "document_type": "trial_balance",
                "decision": "accepted",
            },
        )
        assert patch_response.status_code == 200

    confirm_response = _confirm(
        client,
        batch_id,
        manifest_entries=[
            {"item_id": item_a["id"], "original_filename": "a.xlsx"},
            {"item_id": item_b["id"], "original_filename": "b.xlsx"},
        ],
        file_parts=[
            (item_a["id"], xlsx_a, XLSX_MIME),
            (item_b["id"], xlsx_b, XLSX_MIME),
        ],
    )

    assert confirm_response.status_code == 200
    summary = confirm_response.json()
    assert summary["created_company_count"] == 1
    assert summary["reused_company_count"] == 1
    assert summary["created_period_count"] == 1
    assert summary["reused_period_count"] == 1

    company_ids = {r["resulting_company_id"] for r in summary["items"]}
    period_ids = {r["resulting_period_id"] for r in summary["items"]}
    assert len(company_ids) == 1
    assert len(period_ids) == 1


def test_confirm_reuses_company_and_period_across_batches(client):
    xlsx_first = _synthetic_balanced_xlsx(seed=30)
    xlsx_second = _synthetic_balanced_xlsx(seed=31)
    shared_company = _new_company_resolution("REUSE-ACROSS-BATCH-0001")
    shared_period = _new_period_resolution(2027)

    first_upload = _upload(client, [("first.xlsx", xlsx_first, XLSX_MIME)])
    first_body = first_upload.json()
    first_batch_id = first_body["batch"]["id"]
    first_item = _item_by_filename(first_body, "first.xlsx")

    client.patch(
        f"/api/v1/bulk-uploads/{first_batch_id}/items/{first_item['id']}",
        json={
            "company": shared_company,
            "period": shared_period,
            "document_type": "trial_balance",
            "decision": "accepted",
        },
    )
    first_confirm = _confirm(
        client,
        first_batch_id,
        manifest_entries=[{"item_id": first_item["id"], "original_filename": "first.xlsx"}],
        file_parts=[(first_item["id"], xlsx_first, XLSX_MIME)],
    )
    assert first_confirm.status_code == 200
    assert first_confirm.json()["created_company_count"] == 1
    assert first_confirm.json()["created_period_count"] == 1

    second_upload = _upload(client, [("second.xlsx", xlsx_second, XLSX_MIME)])
    second_body = second_upload.json()
    second_batch_id = second_body["batch"]["id"]
    second_item = _item_by_filename(second_body, "second.xlsx")

    client.patch(
        f"/api/v1/bulk-uploads/{second_batch_id}/items/{second_item['id']}",
        json={
            "company": shared_company,
            "period": shared_period,
            "document_type": "trial_balance",
            "decision": "accepted",
        },
    )
    second_confirm = _confirm(
        client,
        second_batch_id,
        manifest_entries=[{"item_id": second_item["id"], "original_filename": "second.xlsx"}],
        file_parts=[(second_item["id"], xlsx_second, XLSX_MIME)],
    )

    assert second_confirm.status_code == 200
    second_summary = second_confirm.json()
    assert second_summary["created_company_count"] == 0
    assert second_summary["reused_company_count"] == 1
    assert second_summary["created_period_count"] == 0
    assert second_summary["reused_period_count"] == 1
    assert (
        second_summary["items"][0]["resulting_company_id"]
        == first_confirm.json()["items"][0]["resulting_company_id"]
    )
    assert (
        second_summary["items"][0]["resulting_period_id"]
        == first_confirm.json()["items"][0]["resulting_period_id"]
    )


def test_confirm_missing_file_returns_422(client):
    xlsx_content = _synthetic_balanced_xlsx(seed=40)
    upload_response = _upload(client, [("mizan.xlsx", xlsx_content, XLSX_MIME)])
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    item = _item_by_filename(body, "mizan.xlsx")

    client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items/{item['id']}",
        json={
            "company": _new_company_resolution("MISSING-FILE-0001"),
            "period": _new_period_resolution(),
            "document_type": "trial_balance",
            "decision": "accepted",
        },
    )

    confirm_response = _confirm(
        client,
        batch_id,
        manifest_entries=[{"item_id": item["id"], "original_filename": "mizan.xlsx"}],
        file_parts=[],
    )

    assert confirm_response.status_code == 422
    errors = confirm_response.json()["detail"]["errors"]
    assert any(e["code"] == "MISSING_FILE" and e["item_id"] == item["id"] for e in errors)

    # Hiçbir şey yazılmamış olmalı.
    batch_get = client.get(f"/api/v1/bulk-uploads/{batch_id}").json()
    assert batch_get["status"] == "completed"


def test_confirm_checksum_mismatch_returns_422(client):
    xlsx_content = _synthetic_balanced_xlsx(seed=41)
    different_content = _synthetic_balanced_xlsx(seed=42)

    upload_response = _upload(client, [("mizan.xlsx", xlsx_content, XLSX_MIME)])
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    item = _item_by_filename(body, "mizan.xlsx")

    client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items/{item['id']}",
        json={
            "company": _new_company_resolution("CHECKSUM-MISMATCH-0001"),
            "period": _new_period_resolution(),
            "document_type": "trial_balance",
            "decision": "accepted",
        },
    )

    confirm_response = _confirm(
        client,
        batch_id,
        manifest_entries=[{"item_id": item["id"], "original_filename": "mizan.xlsx"}],
        file_parts=[(item["id"], different_content, XLSX_MIME)],
    )

    assert confirm_response.status_code == 422
    errors = confirm_response.json()["detail"]["errors"]
    assert any(e["code"] == "CHECKSUM_MISMATCH" for e in errors)


def test_confirm_engine_failure_writes_nothing(client):
    broken_content = _synthetic_empty_dataframe_xlsx()
    upload_response = _upload(client, [("bos.xlsx", broken_content, XLSX_MIME)])
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    item = _item_by_filename(body, "bos.xlsx")
    assert item["detected_document_type"] == "trial_balance"

    client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items/{item['id']}",
        json={
            "company": _new_company_resolution("ENGINE-FAIL-0001"),
            "period": _new_period_resolution(),
            "document_type": "trial_balance",
            "decision": "accepted",
        },
    )

    companies_before = client.get("/api/v1/companies").json()["total"]

    confirm_response = _confirm(
        client,
        batch_id,
        manifest_entries=[{"item_id": item["id"], "original_filename": "bos.xlsx"}],
        file_parts=[(item["id"], broken_content, XLSX_MIME)],
    )

    assert confirm_response.status_code == 422
    errors = confirm_response.json()["detail"]["errors"]
    assert any(e["code"] == "ENGINE_FAILED" for e in errors)

    companies_after = client.get("/api/v1/companies").json()["total"]
    assert companies_after == companies_before  # hiçbir Company yazılmadı

    batch_get = client.get(f"/api/v1/bulk-uploads/{batch_id}").json()
    assert batch_get["status"] == "completed"  # confirmed OLMADI

    item_get = next(
        i for i in client.get(f"/api/v1/bulk-uploads/{batch_id}/items").json()["items"]
        if i["id"] == item["id"]
    )
    assert item_get["resulting_document_id"] is None
    assert item_get["user_decision"] == "accepted"  # karar geri alınmadı, yalnızca yazma


def test_confirm_duplicate_document_returns_422(client):
    xlsx_content = _synthetic_balanced_xlsx(seed=50)

    first_upload = _upload(client, [("first.xlsx", xlsx_content, XLSX_MIME)])
    first_body = first_upload.json()
    first_batch_id = first_body["batch"]["id"]
    first_item = _item_by_filename(first_body, "first.xlsx")

    client.patch(
        f"/api/v1/bulk-uploads/{first_batch_id}/items/{first_item['id']}",
        json={
            "company": _new_company_resolution("DUPLICATE-DOC-0001"),
            "period": _new_period_resolution(),
            "document_type": "trial_balance",
            "decision": "accepted",
        },
    )
    first_confirm = _confirm(
        client,
        first_batch_id,
        manifest_entries=[{"item_id": first_item["id"], "original_filename": "first.xlsx"}],
        file_parts=[(first_item["id"], xlsx_content, XLSX_MIME)],
    )
    assert first_confirm.status_code == 200
    resulting_company_id = first_confirm.json()["items"][0]["resulting_company_id"]
    resulting_period_id = first_confirm.json()["items"][0]["resulting_period_id"]

    # AYNI baytları ikinci kez, AYNI dönem/firmaya karşı yükle.
    second_upload = _upload(client, [("second.xlsx", xlsx_content, XLSX_MIME)])
    second_body = second_upload.json()
    second_batch_id = second_body["batch"]["id"]
    second_item = _item_by_filename(second_body, "second.xlsx")
    # Sınıflandırma motoru bunu zaten duplicate/possible_duplicate
    # olarak işaretlemiş olabilir -- kullanıcı yine de manuel çözüp
    # accepted yapabilir (bkz. Milestone 3 / Adım 1 madde 11 kararı);
    # asıl garanti DB seviyesindeki (period_id, checksum) kontrolüdür.
    client.patch(
        f"/api/v1/bulk-uploads/{second_batch_id}/items/{second_item['id']}",
        json={
            "company": {"mode": "existing", "id": resulting_company_id},
            "period": {"mode": "existing", "id": resulting_period_id},
            "document_type": "trial_balance",
            "decision": "accepted",
        },
    )

    second_confirm = _confirm(
        client,
        second_batch_id,
        manifest_entries=[{"item_id": second_item["id"], "original_filename": "second.xlsx"}],
        file_parts=[(second_item["id"], xlsx_content, XLSX_MIME)],
    )

    assert second_confirm.status_code == 422
    errors = second_confirm.json()["detail"]["errors"]
    assert any(e["code"] == "DUPLICATE_DOCUMENT" for e in errors)


def test_confirm_not_ready_batch_returns_409():
    """PROCESSING/FAILED durumundaki bir batch confirm edilemez -- servis
    katmanı doğrudan çağrılarak (HTTP'siz) test edilir."""

    import uuid as uuid_module

    from app.services.bulk_upload import BatchNotReadyError, confirm_bulk_upload

    class _FakeBatch:
        id = uuid_module.uuid4()
        status = "processing"

    class _FakeDB:
        def get(self, model, batch_id):
            return _FakeBatch()

    # BatchStatus.PROCESSING gerçek enum değeriyle karşılaştırıldığında
    # eşleşmeyecek şekilde bilerek düz string kullanıldı -- yalnızca
    # "COMPLETED değilse 409" dalının tetiklendiğini doğrular.
    with pytest.raises(BatchNotReadyError):
        confirm_bulk_upload(_FakeDB(), _FakeBatch.id, {})


def test_confirm_twice_returns_409(client):
    corporate = _read_fixture("synthetic_corporate_tax_return.pdf")
    upload_response = _upload(client, [("kv.pdf", corporate, PDF_MIME)])
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    item = _item_by_filename(body, "kv.pdf")

    client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items",
        json={"items": [{"item_id": item["id"], "decision": "accepted"}]},
    )

    first_confirm = _confirm(client, batch_id, [], [])
    assert first_confirm.status_code == 200

    second_confirm = _confirm(client, batch_id, [], [])
    assert second_confirm.status_code == 409


def test_confirm_then_patch_returns_409(client):
    corporate = _read_fixture("synthetic_corporate_tax_return.pdf")
    upload_response = _upload(client, [("kv.pdf", corporate, PDF_MIME)])
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    item = _item_by_filename(body, "kv.pdf")

    client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items",
        json={"items": [{"item_id": item["id"], "decision": "accepted"}]},
    )
    confirm_response = _confirm(client, batch_id, [], [])
    assert confirm_response.status_code == 200

    patch_after_confirm = client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items/{item['id']}",
        json={"decision": "ignored"},
    )
    assert patch_after_confirm.status_code == 409

    bulk_patch_after_confirm = client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items",
        json={"items": [{"item_id": item["id"], "decision": "ignored"}]},
    )
    assert bulk_patch_after_confirm.status_code == 409


def test_confirm_ignored_items_never_written(client):
    corporate = _read_fixture("synthetic_corporate_tax_return.pdf")
    temporary = _read_fixture("synthetic_temporary_tax_return.pdf")

    upload_response = _upload(
        client,
        [("kv.pdf", corporate, PDF_MIME), ("gv.pdf", temporary, PDF_MIME)],
    )
    body = upload_response.json()
    batch_id = body["batch"]["id"]
    accepted_item = _item_by_filename(body, "kv.pdf")
    ignored_item = _item_by_filename(body, "gv.pdf")

    client.patch(
        f"/api/v1/bulk-uploads/{batch_id}/items",
        json={
            "items": [
                {"item_id": accepted_item["id"], "decision": "accepted"},
                {"item_id": ignored_item["id"], "decision": "ignored"},
            ]
        },
    )

    confirm_response = _confirm(client, batch_id, [], [])

    assert confirm_response.status_code == 200
    summary = confirm_response.json()
    assert summary["ignored_item_count"] == 1
    assert len(summary["items"]) == 1  # yalnızca accepted item işlendi

    items_get = client.get(f"/api/v1/bulk-uploads/{batch_id}/items").json()["items"]
    ignored_get = next(i for i in items_get if i["id"] == ignored_item["id"])
    assert ignored_get["resulting_company_id"] is None
    assert ignored_get["resulting_period_id"] is None
    assert ignored_get["resulting_document_id"] is None
    assert ignored_get["resulting_analysis_id"] is None
