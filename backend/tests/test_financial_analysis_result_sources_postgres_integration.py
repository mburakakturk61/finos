"""
Gerçek PostgreSQL'e karşı çalışan entegrasyon testi (Milestone 4.1 --
Analysis Foundation).

SQLite'ın güvenilir biçimde doğrulayamayacağı PostgreSQL'e özgü davranışları
doğrudan doğrular:
  - financial_analysis_results.source_mode='direct_document' iken
    document_id'nin NULL olamayacağı, diğer iki source_mode değeri için
    NULL olabileceği (ck_financial_analysis_results_direct_requires_document).
  - financial_analysis_results.document_id NULL olsa bile company_id/
    period_id çiftinin geçerli olduğunun fk_financial_analysis_results_
    period_company ile garanti edildiği.
  - financial_analysis_result_sources tablosundaki XOR kaynak kuralı,
    self-reference engeli, role<->kaynak-türü eşleşmesi, company/period
    tutarlılığı (üç composite FK), unique constraint'ler ve RESTRICT silme
    davranışı.

TEST_DATABASE_URL (yoksa DATABASE_URL) ortam değişkeni erişilebilir bir
PostgreSQL'e işaret etmiyorsa bu modüldeki tüm testler zarifçe SKIP edilir.
Bkz. tests/README.md.

Yerelde çalıştırmak için:
    docker compose up -d db
    cd backend && pip install -r requirements.txt
    pytest tests/test_financial_analysis_result_sources_postgres_integration.py -v
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
    (3a7c2e9f5b14 dahil, Milestone 4.1)."""

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
        "legal_name": "Analysis Foundation Test Firması",
        "tax_number": f"AFPG-{uuid.uuid4().hex[:10]}",
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


def _make_analysis(company_id, period_id, document_id=None, **overrides):
    from app.models.enums import AnalysisStatus, AnalysisType, SourceMode
    from app.models.financial_analysis_result import FinancialAnalysisResult

    defaults = {
        "company_id": company_id,
        "period_id": period_id,
        "document_id": document_id,
        "analysis_type": AnalysisType.TRIAL_BALANCE,
        "engine_version": "1.0.0",
        "status": AnalysisStatus.COMPLETED,
        "source_mode": (
            SourceMode.DIRECT_DOCUMENT
            if document_id is not None
            else SourceMode.MULTI_SOURCE_DERIVED
        ),
        "started_at": datetime.now(timezone.utc),
        "completed_at": datetime.now(timezone.utc),
        "result_json": {"status": "VALID"},
    }
    defaults.update(overrides)
    return FinancialAnalysisResult(**defaults)


def _make_source(analysis_result_id, company_id, period_id, **overrides):
    from app.models.enums import AnalysisSourceRole
    from app.models.financial_analysis_result_source import (
        FinancialAnalysisResultSource,
    )

    defaults = {
        "analysis_result_id": analysis_result_id,
        "company_id": company_id,
        "period_id": period_id,
        "role": AnalysisSourceRole.PRIMARY_DOCUMENT,
    }
    defaults.update(overrides)
    return FinancialAnalysisResultSource(**defaults)


def _setup_company_period(db_session: Session):
    company = _make_company()
    db_session.add(company)
    db_session.commit()

    period = _make_period(company.id)
    db_session.add(period)
    db_session.commit()

    return company, period


# --- financial_analysis_results.source_mode / document_id kuralları -------


def test_direct_document_requires_document_id(db_session: Session):
    from app.models.enums import SourceMode

    company, period = _setup_company_period(db_session)

    analysis = _make_analysis(
        company.id, period.id, document_id=None, source_mode=SourceMode.DIRECT_DOCUMENT
    )
    db_session.add(analysis)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_trial_balance_derived_allows_null_document_id(db_session: Session):
    from app.models.enums import SourceMode

    company, period = _setup_company_period(db_session)

    analysis = _make_analysis(
        company.id,
        period.id,
        document_id=None,
        source_mode=SourceMode.TRIAL_BALANCE_DERIVED,
    )
    db_session.add(analysis)
    db_session.commit()

    assert analysis.document_id is None


def test_multi_source_derived_allows_null_document_id(db_session: Session):
    from app.models.enums import SourceMode

    company, period = _setup_company_period(db_session)

    analysis = _make_analysis(
        company.id,
        period.id,
        document_id=None,
        source_mode=SourceMode.MULTI_SOURCE_DERIVED,
    )
    db_session.add(analysis)
    db_session.commit()

    assert analysis.document_id is None


def test_source_mode_defaults_to_direct_document(db_session: Session):
    """Python-seviyeli ORM default'un (SourceMode.DIRECT_DOCUMENT) source_mode
    HİÇ verilmediğinde devreye girdiğini doğrular -- migration'daki
    backfill'in Milestone 3'ten kalan (hepsi trial_balance) mevcut satırlar
    için KULLANDIĞI değer de budur (bkz. migration docstring'i). Gerçek
    Milestone 3 verisiyle dolu bir veritabanında migration'ın DAVRANIŞI
    (mevcut satırların gerçekten direct_document kalması) yalnızca o veriyle
    birebir çalıştırılarak doğrulanabilir -- bu, kullanıcının yerelinde
    Milestone 3 verisi üzerinden `alembic upgrade head` çalıştırmasıyla
    ayrıca doğrulanmalıdır; bu test yalnızca ORM default MEKANİZMASININ
    doğru değere sahip olduğunu kanıtlar."""

    from app.models.enums import AnalysisStatus, AnalysisType, SourceMode
    from app.models.financial_analysis_result import FinancialAnalysisResult

    company, period = _setup_company_period(db_session)
    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    # source_mode BİLEREK verilmiyor -- ORM Python-seviyeli default'un
    # (SourceMode.DIRECT_DOCUMENT) devreye girmesini bekliyoruz.
    analysis = FinancialAnalysisResult(
        company_id=company.id,
        period_id=period.id,
        document_id=document.id,
        analysis_type=AnalysisType.TRIAL_BALANCE,
        engine_version="1.0.0",
        status=AnalysisStatus.COMPLETED,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        result_json={"status": "VALID"},
    )
    db_session.add(analysis)
    db_session.commit()

    assert analysis.source_mode == SourceMode.DIRECT_DOCUMENT


def test_period_company_fk_rejects_mismatched_pair(db_session: Session):
    """fk_financial_analysis_results_period_company'nin document_id'den
    BAĞIMSIZ olarak devrede olduğunu doğrular -- document_id NULL olsa
    bile geçersiz bir (company_id, period_id) çifti reddedilir."""

    from app.models.enums import SourceMode

    company_a, period_a = _setup_company_period(db_session)
    company_b, _period_b = _setup_company_period(db_session)

    # period_a, company_a'ya ait; company_id'yi bilerek company_b yapıyoruz.
    analysis = _make_analysis(
        company_b.id,
        period_a.id,
        document_id=None,
        source_mode=SourceMode.MULTI_SOURCE_DERIVED,
    )
    db_session.add(analysis)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- financial_analysis_result_sources: XOR / self-reference / role -------


def test_source_row_rejects_both_sources_filled(db_session: Session):
    company, period = _setup_company_period(db_session)
    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    parent = _make_analysis(company.id, period.id, document.id)
    db_session.add(parent)
    db_session.commit()

    other = _make_analysis(company.id, period.id, document.id)
    db_session.add(other)
    db_session.commit()

    source = _make_source(
        parent.id,
        company.id,
        period.id,
        source_document_id=document.id,
        source_analysis_result_id=other.id,
    )
    db_session.add(source)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_source_row_rejects_both_sources_empty(db_session: Session):
    company, period = _setup_company_period(db_session)
    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    parent = _make_analysis(company.id, period.id, document.id)
    db_session.add(parent)
    db_session.commit()

    source = _make_source(parent.id, company.id, period.id)
    db_session.add(source)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_source_row_rejects_self_reference(db_session: Session):
    from app.models.enums import AnalysisSourceRole

    company, period = _setup_company_period(db_session)
    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    parent = _make_analysis(company.id, period.id, document.id)
    db_session.add(parent)
    db_session.commit()

    source = _make_source(
        parent.id,
        company.id,
        period.id,
        source_document_id=None,
        source_analysis_result_id=parent.id,
        role=AnalysisSourceRole.PRIMARY_ANALYSIS,
    )
    db_session.add(source)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_source_row_rejects_role_source_type_mismatch(db_session: Session):
    """Onaylanan Milestone 4.1 kararı #2: primary_document rolü yalnızca
    source_document_id ile kullanılabilir; burada bilerek
    source_analysis_result_id ile kullanılmaya çalışılıyor."""

    from app.models.enums import AnalysisSourceRole

    company, period = _setup_company_period(db_session)
    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    parent = _make_analysis(company.id, period.id, document.id)
    other = _make_analysis(company.id, period.id, document.id)
    db_session.add_all([parent, other])
    db_session.commit()

    source = _make_source(
        parent.id,
        company.id,
        period.id,
        source_document_id=None,
        source_analysis_result_id=other.id,
        role=AnalysisSourceRole.PRIMARY_DOCUMENT,  # KASITLI uyumsuz
    )
    db_session.add(source)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_all_role_values_accepted_with_matching_source_type(db_session: Session):
    """AnalysisSourceRole'ün TÜM değerlerinin, doğru kaynak türüyle
    eşleştirildiğinde CHECK constraint tarafından kabul edildiğini
    doğrular (onaylanan Milestone 4.1 kararı #2)."""

    from app.models.enums import AnalysisSourceRole

    company, period = _setup_company_period(db_session)
    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    parent = _make_analysis(company.id, period.id, document.id)
    db_session.add(parent)
    db_session.commit()

    document_roles = [
        AnalysisSourceRole.PRIMARY_DOCUMENT,
        AnalysisSourceRole.SUPPORTING_DOCUMENT,
    ]
    analysis_roles = [
        AnalysisSourceRole.PRIMARY_ANALYSIS,
        AnalysisSourceRole.SUPPORTING_ANALYSIS,
        AnalysisSourceRole.TRIAL_BALANCE_FALLBACK,
    ]

    for role in document_roles:
        extra_document = _make_document(company.id, period.id)
        db_session.add(extra_document)
        db_session.commit()

        source = _make_source(
            parent.id,
            company.id,
            period.id,
            source_document_id=extra_document.id,
            role=role,
        )
        db_session.add(source)
        db_session.commit()

    for role in analysis_roles:
        extra_analysis = _make_analysis(company.id, period.id, document.id)
        db_session.add(extra_analysis)
        db_session.commit()

        source = _make_source(
            parent.id,
            company.id,
            period.id,
            source_document_id=None,
            source_analysis_result_id=extra_analysis.id,
            role=role,
        )
        db_session.add(source)
        db_session.commit()

    # prior_period_reference her iki kaynak türüyle de kullanılabilir.
    another_document = _make_document(company.id, period.id)
    db_session.add(another_document)
    db_session.commit()

    source = _make_source(
        parent.id,
        company.id,
        period.id,
        source_document_id=another_document.id,
        role=AnalysisSourceRole.PRIOR_PERIOD_REFERENCE,
    )
    db_session.add(source)
    db_session.commit()


# --- financial_analysis_result_sources: company/period tutarlılığı -------


def test_source_row_rejects_document_from_different_company(db_session: Session):
    company_a, period_a = _setup_company_period(db_session)
    company_b, period_b = _setup_company_period(db_session)

    document_b = _make_document(company_b.id, period_b.id)
    db_session.add(document_b)
    db_session.commit()

    document_a = _make_document(company_a.id, period_a.id)
    db_session.add(document_a)
    db_session.commit()

    parent = _make_analysis(company_a.id, period_a.id, document_a.id)
    db_session.add(parent)
    db_session.commit()

    # source_document_id company_b'ye ait ama satırın company_id'si
    # (parent'la aynı tutulmak zorunda) company_a -- composite FK reddetmeli.
    source = _make_source(
        parent.id,
        company_a.id,
        period_a.id,
        source_document_id=document_b.id,
    )
    db_session.add(source)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_source_row_rejects_analysis_from_different_period(db_session: Session):
    company, period_a = _setup_company_period(db_session)
    period_b = _make_period(company.id, year=2023, period_number=4)
    db_session.add(period_b)
    db_session.commit()

    document_a = _make_document(company.id, period_a.id)
    document_b = _make_document(company.id, period_b.id)
    db_session.add_all([document_a, document_b])
    db_session.commit()

    parent = _make_analysis(company.id, period_a.id, document_a.id)
    other_period_analysis = _make_analysis(company.id, period_b.id, document_b.id)
    db_session.add_all([parent, other_period_analysis])
    db_session.commit()

    from app.models.enums import AnalysisSourceRole

    source = _make_source(
        parent.id,
        company.id,
        period_a.id,
        source_document_id=None,
        source_analysis_result_id=other_period_analysis.id,
        role=AnalysisSourceRole.PRIOR_PERIOD_REFERENCE,
    )
    db_session.add(source)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- financial_analysis_result_sources: unique constraint'ler -------------


def test_duplicate_document_source_rejected(db_session: Session):
    company, period = _setup_company_period(db_session)
    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    parent = _make_analysis(company.id, period.id, document.id)
    db_session.add(parent)
    db_session.commit()

    db_session.add(_make_source(parent.id, company.id, period.id, source_document_id=document.id))
    db_session.commit()

    db_session.add(_make_source(parent.id, company.id, period.id, source_document_id=document.id))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_duplicate_analysis_source_rejected(db_session: Session):
    from app.models.enums import AnalysisSourceRole

    company, period = _setup_company_period(db_session)
    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    parent = _make_analysis(company.id, period.id, document.id)
    other = _make_analysis(company.id, period.id, document.id)
    db_session.add_all([parent, other])
    db_session.commit()

    db_session.add(
        _make_source(
            parent.id, company.id, period.id,
            source_document_id=None, source_analysis_result_id=other.id,
            role=AnalysisSourceRole.PRIMARY_ANALYSIS,
        )
    )
    db_session.commit()

    db_session.add(
        _make_source(
            parent.id, company.id, period.id,
            source_document_id=None, source_analysis_result_id=other.id,
            role=AnalysisSourceRole.SUPPORTING_ANALYSIS,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- financial_analysis_result_sources: RESTRICT silme davranışı ---------


def test_restrict_prevents_deleting_document_referenced_as_source(db_session: Session):
    company, period = _setup_company_period(db_session)
    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    parent = _make_analysis(company.id, period.id, document.id)
    db_session.add(parent)
    db_session.commit()

    db_session.add(_make_source(parent.id, company.id, period.id, source_document_id=document.id))
    db_session.commit()

    db_session.delete(document)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_restrict_prevents_deleting_analysis_referenced_as_source(db_session: Session):
    from app.models.enums import AnalysisSourceRole

    company, period = _setup_company_period(db_session)
    document = _make_document(company.id, period.id)
    db_session.add(document)
    db_session.commit()

    parent = _make_analysis(company.id, period.id, document.id)
    other = _make_analysis(company.id, period.id, document.id)
    db_session.add_all([parent, other])
    db_session.commit()

    db_session.add(
        _make_source(
            parent.id, company.id, period.id,
            source_document_id=None, source_analysis_result_id=other.id,
            role=AnalysisSourceRole.PRIMARY_ANALYSIS,
        )
    )
    db_session.commit()

    db_session.delete(other)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
