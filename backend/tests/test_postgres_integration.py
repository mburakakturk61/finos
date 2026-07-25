"""
Gerçek PostgreSQL'e karşı çalışan entegrasyon testi.

SQLite testlerinin (test_companies_api.py, test_periods_api.py) doğrulayamadığı
PostgreSQL'e özgü davranışları doğrudan doğrular: tax_number unique
constraint, composite foreign key tutarlılığı (document.company_id ==
period.company_id) ve ondelete=RESTRICT silme davranışı. Ayrıca ilk
Alembic migration'ın gerçekten uygulanabilir olduğunu kanıtlar.

TEST_DATABASE_URL (yoksa DATABASE_URL) ortam değişkeni erişilebilir bir
PostgreSQL'e işaret etmiyorsa bu modüldeki tüm testler zarifçe SKIP edilir
-- sahte "geçti" sonucu üretilmez. Bkz. tests/README.md.

Yerelde çalıştırmak için:
    docker compose up -d db
    cd backend && pip install -r requirements.txt
    pytest tests/test_postgres_integration.py -v
"""

import os
import subprocess
import sys
import uuid

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
    """Testlerden önce gerçek Postgres'e `alembic upgrade head` uygular."""

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
            "alembic upgrade head başarısız oldu -- migration dosyası "
            f"gerçek PostgreSQL'e uygulanamadı.\nstdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
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
        "legal_name": "Entegrasyon Test Firması",
        "tax_number": f"PGTEST-{uuid.uuid4().hex[:10]}",
        "currency": "TRY",
    }
    defaults.update(overrides)
    return Company(**defaults)


def test_tax_number_unique_constraint_enforced(db_session: Session):
    tax_number = f"PGTEST-{uuid.uuid4().hex[:10]}"

    db_session.add(_make_company(tax_number=tax_number))
    db_session.commit()

    db_session.add(_make_company(tax_number=tax_number))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_period_composite_fk_rejects_mismatched_company(db_session: Session):
    from app.models.enums import DocumentType, PeriodType, ProcessingStatus
    from app.models.financial_document import FinancialDocument
    from app.models.financial_period import FinancialPeriod

    company_a = _make_company()
    company_b = _make_company()
    db_session.add_all([company_a, company_b])
    db_session.commit()

    period_a = FinancialPeriod(
        company_id=company_a.id,
        year=2024,
        period_type=PeriodType.YEAR_END,
        period_number=4,
        start_date="2024-01-01",
        end_date="2024-12-31",
        months_covered=12,
        is_year_end=True,
    )
    db_session.add(period_a)
    db_session.commit()

    # period_a company_a'ya ait; company_id'yi bilerek company_b yaparak
    # composite FK'nin (period_id, company_id) -> (id, company_id)
    # tutarsızlığı reddetmesini bekliyoruz.
    inconsistent_document = FinancialDocument(
        company_id=company_b.id,
        period_id=period_a.id,
        document_type=DocumentType.TRIAL_BALANCE,
        original_filename="test.xlsx",
        mime_type=(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        ),
        file_size=1024,
        checksum="deadbeef",
        processing_status=ProcessingStatus.PENDING,
    )
    db_session.add(inconsistent_document)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_restrict_prevents_deleting_company_with_periods(db_session: Session):
    from app.models.enums import PeriodType
    from app.models.financial_period import FinancialPeriod

    company = _make_company()
    db_session.add(company)
    db_session.commit()

    period = FinancialPeriod(
        company_id=company.id,
        year=2024,
        period_type=PeriodType.YEAR_END,
        period_number=4,
        start_date="2024-01-01",
        end_date="2024-12-31",
        months_covered=12,
        is_year_end=True,
    )
    db_session.add(period)
    db_session.commit()

    db_session.delete(company)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_restrict_allows_deleting_company_without_periods(db_session: Session):
    """Kontrol testi: bağlı kaydı olmayan bir firma normal şekilde silinebilmeli
    -- RESTRICT'in her silmeyi değil, yalnızca bağlı-kayıt durumunu
    engellediğini doğrular."""

    company = _make_company()
    db_session.add(company)
    db_session.commit()

    db_session.delete(company)
    db_session.commit()  # hata fırlatmamalı

    from app.models.company import Company

    assert db_session.get(Company, company.id) is None
