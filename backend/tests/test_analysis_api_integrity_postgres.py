from datetime import date, datetime, timezone
import hashlib
import uuid

import pytest
from sqlalchemy import insert, update
from sqlalchemy.exc import DBAPIError

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.enums import AnalysisStatus, AnalysisType, PeriodStatus, PeriodType, SourceMode
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_period import FinancialPeriod
from app.orchestration_persistence.codec import canonical_json_bytes


def test_terminal_financial_result_payload_and_digest_are_immutable_postgres():
    payload = {"trial_balance": {"100": "1.00"}}
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    with SessionLocal() as session, session.begin():
        company = Company(legal_name="API Integrity", tax_number=uuid.uuid4().hex, currency="TRY")
        session.add(company)
        session.flush()
        period = FinancialPeriod(
            company_id=company.id, year=2026, period_type=PeriodType.YEAR_END,
            period_number=1, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            months_covered=12, is_year_end=True, status=PeriodStatus.DRAFT,
        )
        session.add(period)
        session.flush()
        result = FinancialAnalysisResult(
            company_id=company.id, period_id=period.id, document_id=None,
            source_mode=SourceMode.MULTI_SOURCE_DERIVED,
            analysis_type=AnalysisType.TRIAL_BALANCE, engine_version="1.0.0",
            status=AnalysisStatus.COMPLETED, result_json=payload,
            canonical_result_digest=digest,
            started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc),
        )
        session.add(result)
        session.flush()
        result_id = result.id

    for values in (
        {"result_json": {"forged": True}},
        {"canonical_result_digest": "f" * 64},
    ):
        with SessionLocal() as session, pytest.raises(DBAPIError):
            session.execute(
                update(FinancialAnalysisResult)
                .where(FinancialAnalysisResult.id == result_id)
                .values(**values)
            )
            session.commit()


def test_completed_payload_requires_canonical_digest_postgres():
    with SessionLocal() as session:
        company = Company(legal_name="API Digest", tax_number=uuid.uuid4().hex, currency="TRY")
        session.add(company)
        session.flush()
        period = FinancialPeriod(
            company_id=company.id, year=2026, period_type=PeriodType.YEAR_END,
            period_number=1, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
            months_covered=12, is_year_end=True, status=PeriodStatus.DRAFT,
        )
        session.add(period)
        session.flush()
        with pytest.raises(DBAPIError):
            session.execute(insert(FinancialAnalysisResult.__table__).values(
                id=uuid.uuid4(), company_id=company.id, period_id=period.id,
                document_id=None, source_mode=SourceMode.MULTI_SOURCE_DERIVED.value,
                analysis_type=AnalysisType.TRIAL_BALANCE.value, engine_version="1.0.0",
                status=AnalysisStatus.COMPLETED.value, result_json={"x": 1},
                canonical_result_digest=None, started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            ))
            session.flush()
        session.rollback()
