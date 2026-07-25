"""
Gerçek PostgreSQL'e karşı çalışan entegrasyon testi (Milestone 2 / Adım 2).

SQLite testlerinin (test_trial_balance_upload_api.py) doğrulayamadığı
PostgreSQL'e özgü davranışları doğrudan doğrular: FinancialAnalysisResult
composite foreign key tutarlılığı, financial_documents üzerindeki yeni
(period_id, checksum) unique constraint, RESTRICT silme davranışı ve
result_json kolonunun gerçekten native JSONB olduğu.

TEST_DATABASE_URL (yoksa DATABASE_URL) ortam değişkeni erişilebilir bir
PostgreSQL'e işaret etmiyorsa bu modüldeki tüm testler zarifçe SKIP edilir.
Bkz. tests/README.md.

Yerelde çalıştırmak için:
    docker compose up -d db
    cd backend && pip install -r requirements.txt
    pytest tests/test_trial_balance_upload_postgres_integration.py -v
"""

import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

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
    (94c5e7403385 + 1f0e6d51f21b dahil)."""

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


def _make_company(**overrides):
    from app.models.company import Company

    defaults = {
        "legal_name": "Upload Entegrasyon Test Firması",
        "tax_number": f"UPLDPG-{uuid.uuid4().hex[:10]}",
        "currency": "TRY",
    }
    defaults.update(overrides)
    return Company(**defaults)


def _make_period(company_id, **overrides):
    from app.models.enums import PeriodType
    from app.models.financial_period import FinancialPeriod

    defaults = {
        "company_id": company_id,
        "year": 2024,
        "period_type": PeriodType.YEAR_END,
        "period_number": 4,
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
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
        "original_filename": "test.xlsx",
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
    from app.models.enums import AnalysisStatus, AnalysisType
    from app.models.financial_analysis_result import FinancialAnalysisResult

    defaults = {
        "company_id": company_id,
        "period_id": period_id,
        "document_id": document_id,
        "analysis_type": AnalysisType.TRIAL_BALANCE,
        "engine_version": "1.0.0",
        "status": AnalysisStatus.COMPLETED,
        "started_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
        "result_json": {"status": "VALID", "totals": {"balanced": True}},
    }
    defaults.update(overrides)
    return FinancialAnalysisResult(**defaults)


def test_period_checksum_unique_constraint_enforced(db_session: Session):
    company = _make_company()
    db_session.add(company)
    db_session.commit()

    period = _make_period(company.id)
    db_session.add(period)
    db_session.commit()

    checksum = uuid.uuid4().hex

    db_session.add(_make_document(company.id, period.id, checksum=checksum))
    db_session.commit()

    db_session.add(_make_document(company.id, period.id, checksum=checksum))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_analysis_composite_fk_rejects_mismatched_document(db_session: Session):
    company_a = _make_company()
    company_b = _make_company()
    db_session.add_all([company_a, company_b])
    db_session.commit()

    period_a = _make_period(company_a.id)
    db_session.add(period_a)
    db_session.commit()

    document_a = _make_document(company_a.id, period_a.id)
    db_session.add(document_a)
    db_session.commit()

    # document_a company_a/period_a'ya ait; analiz kaydında company_id'yi
    # bilerek company_b yaparak composite FK'nin bunu reddetmesini
    # bekliyoruz.
    inconsistent_analysis = _make_analysis(
        company_id=company_b.id,
        period_id=period_a.id,
        document_id=document_a.id,
    )
    db_session.add(inconsistent_analysis)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_restrict_prevents_deleting_document_with_analysis(db_session: Session):
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

    db_session.delete(document)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_result_json_is_native_jsonb(db_session: Session):
    company = _make_company()
    db_session.add(company)
    db_session.commit()

    period = _make_period(company.id)
    db_session.add(period)
    db_session.commit()

    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    analysis = _make_analysis(
        company.id,
        period.id,
        document.id,
        result_json={"status": "VALID", "nested": {"a": 1, "b": [1, 2, 3]}},
    )
    db_session.add(analysis)
    db_session.commit()

    column_type = db_session.execute(
        text(
            "SELECT pg_typeof(result_json)::text FROM financial_analysis_results "
            "WHERE id = :analysis_id"
        ),
        {"analysis_id": analysis.id},
    ).scalar_one()

    assert column_type == "jsonb"
