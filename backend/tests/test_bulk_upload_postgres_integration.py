"""
Gerçek PostgreSQL'e karşı çalışan entegrasyon testi (Milestone 2 / Adım 3
+ Milestone 3 / Adım 1).

SQLite testlerinin (test_bulk_upload_api.py) doğrulayamadığı PostgreSQL'e
özgü davranışları doğrudan doğrular: bulk_upload_items -> bulk_upload_batches
üzerindeki RESTRICT silme davranışı, warnings_json/detection_evidence_json/
resolution_json kolonlarının gerçekten native JSONB olduğu, enum CHECK
constraint'lerinin (values_callable ile üretilen küçük harfli .value'lar,
"confirmed" dahil) gerçek insert'lerde ihlal edilmediği, ve Milestone 3 /
Adım 1'de eklenen dört resulting_*_id RESTRICT FK'sinin (companies/
financial_periods/financial_documents/financial_analysis_results) gerçekten
silmeyi engellediği -- ve tüm bu constraint/index adlarının (özellikle
fk_bulk_upload_items_resulting_analysis -- PostgreSQL'in 63 karakter
identifier sınırını aşmaması için kısaltıldı, bkz. migration 9d4f1a7c6e52)
gerçek Postgres'e uygulanabildiği.

TEST_DATABASE_URL (yoksa DATABASE_URL) ortam değişkeni erişilebilir bir
PostgreSQL'e işaret etmiyorsa bu modüldeki tüm testler zarifçe SKIP edilir.
Bkz. tests/README.md.

Yerelde çalıştırmak için:
    docker compose up -d db
    cd backend && pip install -r requirements.txt
    pytest tests/test_bulk_upload_postgres_integration.py -v
"""

import os
import subprocess
import sys
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL"
)


def _postgres_available() -> bool:
    if not TEST_DATABASE_URL:
        return False

    try:
        probe_engine = create_engine(TEST_DATABASE_URL)
        with probe_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        probe_engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason=(
        "Erişilebilir bir PostgreSQL bulunamadı "
        "(TEST_DATABASE_URL veya DATABASE_URL ortam değişkeni gerekli). "
        "`docker compose up -d db` çalıştırıp tekrar deneyin."
    ),
)


@pytest.fixture(scope="module", autouse=True)
def _apply_migrations():
    """Testlerden önce gerçek Postgres'e `alembic upgrade head` uygular
    (94c5e7403385 + 1f0e6d51f21b + 2b6a8f4c9d31 + 9d4f1a7c6e52 dahil)."""

    backend_dir = os.path.join(os.path.dirname(__file__), "..")

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        pytest.fail(
            "alembic upgrade head başarısız oldu.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    yield


@pytest.fixture()
def db_session():
    engine = create_engine(TEST_DATABASE_URL)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_local()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def _make_batch(**overrides):
    from app.models.bulk_upload_batch import BulkUploadBatch
    from app.models.enums import BatchStatus

    defaults = {
        "status": BatchStatus.COMPLETED,
        "total_file_count": 1,
        "classified_file_count": 1,
        "unclassified_file_count": 0,
        "duplicate_file_count": 0,
    }
    defaults.update(overrides)
    return BulkUploadBatch(**defaults)


def _make_item(batch_id, **overrides):
    from app.models.bulk_upload_item import BulkUploadItem
    from app.models.enums import ClassificationStatus, DetectedDocumentType

    defaults = {
        "batch_id": batch_id,
        "original_filename": "test.pdf",
        "mime_type": "application/pdf",
        "file_size": 1024,
        "checksum": uuid.uuid4().hex,
        "detected_document_type": DetectedDocumentType.CORPORATE_TAX_RETURN,
        "confidence_score": Decimal("0.95"),
        "classification_status": ClassificationStatus.AUTO_MATCHED,
        "warnings_json": [],
        "detection_evidence_json": {},
    }
    defaults.update(overrides)
    return BulkUploadItem(**defaults)


def test_restrict_prevents_deleting_batch_with_items(db_session: Session):
    batch = _make_batch()
    db_session.add(batch)
    db_session.commit()

    item = _make_item(batch.id)
    db_session.add(item)
    db_session.commit()

    db_session.delete(batch)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_json_columns_are_native_jsonb(db_session: Session):
    batch = _make_batch()
    db_session.add(batch)
    db_session.commit()

    item = _make_item(
        batch.id,
        warnings_json=[{"code": "VKN_CHECKSUM_FAILED", "message": "test"}],
        detection_evidence_json={"tax_number": {"value": "1234567890", "source": "pdf_text"}},
    )
    db_session.add(item)
    db_session.commit()

    warnings_type, evidence_type = db_session.execute(
        text(
            "SELECT pg_typeof(warnings_json)::text, "
            "pg_typeof(detection_evidence_json)::text "
            "FROM bulk_upload_items WHERE id = :item_id"
        ),
        {"item_id": item.id},
    ).one()

    assert warnings_type == "jsonb"
    assert evidence_type == "jsonb"


def test_all_classification_status_values_accepted(db_session: Session):
    from app.models.enums import ClassificationStatus

    batch = _make_batch()
    db_session.add(batch)
    db_session.commit()

    for status_value in ClassificationStatus:
        item = _make_item(
            batch.id,
            checksum=uuid.uuid4().hex,
            classification_status=status_value,
        )
        db_session.add(item)
    db_session.commit()


def test_all_detected_document_type_values_accepted(db_session: Session):
    from app.models.enums import DetectedDocumentType

    batch = _make_batch()
    db_session.add(batch)
    db_session.commit()

    for doc_type in DetectedDocumentType:
        item = _make_item(
            batch.id,
            checksum=uuid.uuid4().hex,
            detected_document_type=doc_type,
        )
        db_session.add(item)
    db_session.commit()


def test_checksum_duplicates_within_batch_are_allowed_at_db_level(db_session: Session):
    """
    bulk_upload_items.checksum'da KASITLI OLARAK unique constraint yok --
    aynı checksum'a sahip iki item'ın var olabilmesi bir bütünlük ihlali
    değildir (duplicate tespiti uygulama katmanındadır, DB constraint'i
    DEĞİLDİR).
    """

    batch = _make_batch(total_file_count=2)
    db_session.add(batch)
    db_session.commit()

    shared_checksum = uuid.uuid4().hex
    db_session.add(_make_item(batch.id, checksum=shared_checksum))
    db_session.add(_make_item(batch.id, checksum=shared_checksum))
    db_session.commit()  # IntegrityError BEKLENMİYOR


# =========================================================================
# Milestone 3 / Adım 1 -- confirm alanları
# =========================================================================


def _make_company(**overrides):
    from app.models.company import Company

    defaults = {
        "legal_name": "Bulk Upload Confirm PG Test A.Ş.",
        "tax_number": f"BULKPGCONF-{uuid.uuid4().hex[:10]}",
        "currency": "TRY",
    }
    defaults.update(overrides)
    return Company(**defaults)


def _make_period(company_id, **overrides):
    from datetime import date

    from app.models.enums import PeriodType
    from app.models.financial_period import FinancialPeriod

    defaults = {
        "company_id": company_id,
        "year": 2025,
        "period_type": PeriodType.YEAR_END,
        "period_number": 4,
        "start_date": date(2025, 1, 1),
        "end_date": date(2025, 12, 31),
        "months_covered": 12,
        "is_year_end": True,
    }
    defaults.update(overrides)
    return FinancialPeriod(**defaults)


def _make_document(company_id, period_id, **overrides):
    from app.models.enums import DocumentType, ProcessingStatus
    from app.models.financial_document import FinancialDocument

    defaults = {
        "company_id": company_id,
        "period_id": period_id,
        "document_type": DocumentType.TRIAL_BALANCE,
        "original_filename": "confirm_pg_test.xlsx",
        "mime_type": (
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        ),
        "file_size": 1024,
        "checksum": uuid.uuid4().hex,
        "processing_status": ProcessingStatus.COMPLETED,
    }
    defaults.update(overrides)
    return FinancialDocument(**defaults)


def _make_analysis(company_id, period_id, document_id, **overrides):
    from datetime import datetime, timezone

    from app.models.enums import AnalysisStatus, AnalysisType
    from app.models.financial_analysis_result import FinancialAnalysisResult

    now = datetime.now(timezone.utc)
    defaults = {
        "company_id": company_id,
        "period_id": period_id,
        "document_id": document_id,
        "analysis_type": AnalysisType.TRIAL_BALANCE,
        "engine_version": "1.0.0",
        "status": AnalysisStatus.COMPLETED,
        "started_at": now,
        "completed_at": now,
        "result_json": {"status": "VALID", "totals": {"balanced": True}},
    }
    defaults.update(overrides)
    return FinancialAnalysisResult(**defaults)


def test_batch_status_accepts_confirmed_value(db_session: Session):
    from datetime import datetime, timezone

    from app.models.enums import BatchStatus

    batch = _make_batch(status=BatchStatus.CONFIRMED, confirmed_at=datetime.now(timezone.utc))
    db_session.add(batch)
    db_session.commit()  # CHECK constraint ihlali BEKLENMİYOR


def test_all_item_review_decision_values_accepted(db_session: Session):
    from app.models.enums import ItemReviewDecision

    batch = _make_batch()
    db_session.add(batch)
    db_session.commit()

    for decision in ItemReviewDecision:
        item = _make_item(batch.id, checksum=uuid.uuid4().hex, user_decision=decision)
        db_session.add(item)
    db_session.commit()


def test_resolution_json_is_native_jsonb(db_session: Session):
    batch = _make_batch()
    db_session.add(batch)
    db_session.commit()

    item = _make_item(
        batch.id,
        resolution_json={
            "company": {"mode": "new", "legal_name": "X", "tax_number": "1234567890"},
            "period": {"mode": "new", "year": 2025},
            "document_type": "trial_balance",
        },
    )
    db_session.add(item)
    db_session.commit()

    column_type = db_session.execute(
        text(
            "SELECT pg_typeof(resolution_json)::text FROM bulk_upload_items "
            "WHERE id = :item_id"
        ),
        {"item_id": item.id},
    ).scalar_one()

    assert column_type == "jsonb"


def test_resulting_ids_default_to_null(db_session: Session):
    batch = _make_batch()
    db_session.add(batch)
    db_session.commit()

    item = _make_item(batch.id)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    assert item.resulting_company_id is None
    assert item.resulting_period_id is None
    assert item.resulting_document_id is None
    assert item.resulting_analysis_id is None


def test_restrict_prevents_deleting_company_referenced_by_resulting_company_id(
    db_session: Session,
):
    company = _make_company()
    db_session.add(company)
    db_session.commit()

    batch = _make_batch()
    db_session.add(batch)
    db_session.commit()

    item = _make_item(batch.id, resulting_company_id=company.id)
    db_session.add(item)
    db_session.commit()

    db_session.delete(company)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_restrict_prevents_deleting_period_referenced_by_resulting_period_id(
    db_session: Session,
):
    company = _make_company()
    db_session.add(company)
    db_session.commit()

    period = _make_period(company.id)
    db_session.add(period)
    db_session.commit()

    batch = _make_batch()
    db_session.add(batch)
    db_session.commit()

    item = _make_item(batch.id, resulting_company_id=company.id, resulting_period_id=period.id)
    db_session.add(item)
    db_session.commit()

    db_session.delete(period)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_restrict_prevents_deleting_document_referenced_by_resulting_document_id(
    db_session: Session,
):
    company = _make_company()
    db_session.add(company)
    db_session.commit()

    period = _make_period(company.id)
    db_session.add(period)
    db_session.commit()

    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    batch = _make_batch()
    db_session.add(batch)
    db_session.commit()

    item = _make_item(
        batch.id,
        resulting_company_id=company.id,
        resulting_period_id=period.id,
        resulting_document_id=document.id,
    )
    db_session.add(item)
    db_session.commit()

    db_session.delete(document)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_restrict_prevents_deleting_analysis_referenced_by_resulting_analysis_id(
    db_session: Session,
):
    company = _make_company()
    db_session.add(company)
    db_session.commit()

    period = _make_period(company.id)
    db_session.add(period)
    db_session.commit()

    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    analysis = _make_analysis(company.id, period.id, document.id)
    db_session.add(analysis)
    db_session.commit()

    batch = _make_batch()
    db_session.add(batch)
    db_session.commit()

    item = _make_item(
        batch.id,
        resulting_company_id=company.id,
        resulting_period_id=period.id,
        resulting_document_id=document.id,
        resulting_analysis_id=analysis.id,
    )
    db_session.add(item)
    db_session.commit()

    db_session.delete(analysis)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
