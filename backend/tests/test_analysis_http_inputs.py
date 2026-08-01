from datetime import date, datetime, timezone
import hashlib
import io
import uuid
import zipfile

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.db.base import Base
from app.integrations.analysis_http.contracts import (
    AuthenticationContext, AuthenticationStrength, InputResolutionCode,
    InputResolutionError,
)
from app.integrations.analysis_http.inputs import (
    SqlAlchemyAnalysisResultInputResolver, SqlAlchemyDocumentInputResolver,
)
from app.models.company import Company
from app.models.enums import (
    AnalysisStatus, AnalysisType, DocumentType, PeriodStatus, PeriodType,
    ProcessingStatus, SourceMode,
)
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_document import FinancialDocument
from app.models.financial_period import FinancialPeriod
from app.orchestration_persistence.codec import canonical_json_bytes


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class ContentStore:
    def __init__(self, values): self.values = values
    def read_document_content(self, document_id, checksum): return self.values[document_id]


@pytest.fixture()
def source_data():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("xl/workbook.xml", "workbook")
    content = stream.getvalue()
    with sessions() as session, session.begin():
        company = Company(legal_name="Resolver", tax_number=uuid.uuid4().hex, currency="TRY")
        session.add(company); session.flush()
        period = FinancialPeriod(
            company_id=company.id, year=2026, period_type=PeriodType.YEAR_END,
            period_number=1, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            months_covered=12, is_year_end=True, status=PeriodStatus.DRAFT,
        )
        session.add(period); session.flush()
        document = FinancialDocument(
            company_id=company.id, period_id=period.id,
            document_type=DocumentType.BALANCE_SHEET,
            original_filename="balance.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            file_size=len(content), checksum=hashlib.sha256(content).hexdigest(),
            processing_status=ProcessingStatus.COMPLETED,
        )
        session.add(document); session.flush()
        payload = {"accounts": {"100": "10.00"}}
        trial = FinancialAnalysisResult(
            company_id=company.id, period_id=period.id, document_id=None,
            source_mode=SourceMode.MULTI_SOURCE_DERIVED,
            analysis_type=AnalysisType.TRIAL_BALANCE, engine_version="1",
            status=AnalysisStatus.COMPLETED, result_json=payload,
            canonical_result_digest=hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
            started_at=NOW, completed_at=NOW,
        )
        session.add(trial); session.flush()
        identifiers = company.id, period.id, document.id, trial.id
    context = AuthenticationContext(
        "subject", "tenant", "test", AuthenticationStrength.STRONG,
        NOW, NOW.replace(hour=1), "corr", "1", "issuer", "auth",
    )
    yield sessions, content, identifiers, context
    engine.dispose()


def test_document_and_trial_balance_sources_are_cryptographically_bound(source_data):
    sessions, content, (company_id, period_id, document_id, trial_id), context = source_data
    document = SqlAlchemyDocumentInputResolver(sessions, ContentStore({document_id: content})).resolve_document_input(
        document_id=document_id, company_id=company_id, financial_period_id=period_id,
        expected_engine_code="fs_balance_sheet", authentication=context,
    )
    assert hashlib.sha256(document.content).hexdigest() == document.sha256_checksum
    trial = SqlAlchemyAnalysisResultInputResolver(sessions).resolve_trial_balance_input(
        analysis_result_id=trial_id, company_id=company_id,
        financial_period_id=period_id, authentication=context,
    )
    assert hashlib.sha256(canonical_json_bytes(trial.result_payload)).hexdigest() == trial.canonical_digest


def test_document_checksum_mismatch_and_wrong_scope_are_fail_closed(source_data):
    sessions, content, (company_id, period_id, document_id, _), context = source_data
    forged = content[:-1] + bytes([content[-1] ^ 1])
    resolver = SqlAlchemyDocumentInputResolver(sessions, ContentStore({document_id: forged}))
    with pytest.raises(InputResolutionError) as caught:
        resolver.resolve_document_input(
            document_id=document_id, company_id=company_id, financial_period_id=period_id,
            expected_engine_code="fs_balance_sheet", authentication=context,
        )
    assert caught.value.code is InputResolutionCode.SOURCE_CHECKSUM_MISMATCH
    resolver = SqlAlchemyDocumentInputResolver(sessions, ContentStore({document_id: content}))
    with pytest.raises(InputResolutionError) as caught:
        resolver.resolve_document_input(
            document_id=document_id, company_id=uuid.uuid4(), financial_period_id=period_id,
            expected_engine_code="fs_balance_sheet", authentication=context,
        )
    assert caught.value.code is InputResolutionCode.SOURCE_SCOPE_MISMATCH


def test_trial_balance_digest_corruption_and_fake_source_are_fail_closed(source_data):
    sessions, _, (company_id, period_id, _, trial_id), context = source_data
    with sessions() as session, session.begin():
        session.execute(
            update(FinancialAnalysisResult)
            .where(FinancialAnalysisResult.id == trial_id)
            .values(canonical_result_digest="f" * 64)
        )
    resolver = SqlAlchemyAnalysisResultInputResolver(sessions)
    with pytest.raises(InputResolutionError) as caught:
        resolver.resolve_trial_balance_input(
            analysis_result_id=trial_id, company_id=company_id,
            financial_period_id=period_id, authentication=context,
        )
    assert caught.value.code is InputResolutionCode.SOURCE_CANONICAL_DIGEST_MISMATCH
    with pytest.raises(InputResolutionError) as caught:
        resolver.resolve_trial_balance_input(
            analysis_result_id=uuid.uuid4(), company_id=company_id,
            financial_period_id=period_id, authentication=context,
        )
    assert caught.value.code is InputResolutionCode.SOURCE_NOT_FOUND
