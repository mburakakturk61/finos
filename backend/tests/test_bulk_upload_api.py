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
from datetime import date
from decimal import Decimal
from pathlib import Path

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
