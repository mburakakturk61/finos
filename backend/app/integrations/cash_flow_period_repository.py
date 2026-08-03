"""PostgreSQL adapter for Milestone 4.5C period/source resolution."""

from __future__ import annotations

from datetime import timezone
from hashlib import sha256
import hmac
from typing import Callable

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.enums import AnalysisType
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_period import FinancialPeriod
from app.orchestration_persistence.codec import canonical_json_bytes

from app.engines.cash_flow.resolution_contracts import (
    CashFlowPeriodResolutionRequest,
    CashFlowResolutionRepositoryError,
    CashFlowResolutionSnapshot,
    CashFlowResolvedPeriod,
    CashFlowResolvedSource,
    canonical_resolution_digest,
)
from app.engines.cash_flow.types import (
    CashFlowAccountingBasisCode,
    CashFlowErrorCode,
    CashFlowSourceRole,
)


_CURRENT_ROLE_BY_TYPE = {
    AnalysisType.BALANCE_SHEET: CashFlowSourceRole.CURRENT_BALANCE_SHEET,
    AnalysisType.INCOME_STATEMENT: CashFlowSourceRole.CURRENT_INCOME_STATEMENT,
    AnalysisType.TRIAL_BALANCE: CashFlowSourceRole.CURRENT_TRIAL_BALANCE,
}
_PRIOR_ROLE_BY_TYPE = {
    AnalysisType.BALANCE_SHEET: CashFlowSourceRole.PRIOR_BALANCE_SHEET,
    AnalysisType.TRIAL_BALANCE: CashFlowSourceRole.PRIOR_TRIAL_BALANCE,
}


def _utc(value):
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SqlAlchemyComparablePeriodRepository:
    """Owns one short company-namespace transaction per resolution call."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        statement_timeout_seconds: float = 3.0,
        lock_timeout_seconds: float = 1.0,
    ) -> None:
        if not 0 < statement_timeout_seconds <= 5:
            raise ValueError("statement timeout must be in (0, 5]")
        if not 0 < lock_timeout_seconds <= statement_timeout_seconds:
            raise ValueError("lock timeout must be positive and bounded by statement timeout")
        self._sessions = session_factory
        self._statement_timeout_ms = max(1, int(statement_timeout_seconds * 1000))
        self._lock_timeout_ms = max(1, int(lock_timeout_seconds * 1000))

    def _before_terminal_requery(
        self,
        session: Session,
        request: CashFlowPeriodResolutionRequest,
    ) -> None:
        """Override only in deterministic race tests; production is a no-op."""

    def _set_timeouts(self, session: Session) -> None:
        session.execute(
            text("SELECT set_config('statement_timeout', :value, true)"),
            {"value": f"{self._statement_timeout_ms}ms"},
        )
        session.execute(
            text("SELECT set_config('lock_timeout', :value, true)"),
            {"value": f"{self._lock_timeout_ms}ms"},
        )

    @staticmethod
    def _period(row: FinancialPeriod, company: Company) -> CashFlowResolvedPeriod:
        basis = (
            CashFlowAccountingBasisCode(row.accounting_basis_code)
            if row.accounting_basis_code is not None
            else None
        )
        return CashFlowResolvedPeriod(
            period_id=row.id,
            tenant_id=company.tenant_id,
            company_id=row.company_id,
            currency_code=company.currency,
            period_type=row.period_type,
            period_number=row.period_number,
            start_date=row.start_date,
            end_date=row.end_date,
            months_covered=row.months_covered,
            status=row.status,
            accounting_basis_code=basis,
            accounting_policy_version=row.accounting_policy_version,
            annual_reporting_period_start_date=row.annual_reporting_period_start_date,
            annual_reporting_period_end_date=row.annual_reporting_period_end_date,
            ifrs18_early_adopted=row.ifrs18_early_adopted,
            coverage_kind=row.cash_flow_coverage_kind,
        )

    @staticmethod
    def _source(
        row: FinancialAnalysisResult,
        role: CashFlowSourceRole,
    ) -> CashFlowResolvedSource:
        recomputed = (
            sha256(canonical_json_bytes(row.result_json)).hexdigest()
            if row.result_json is not None
            else None
        )
        verified = (
            row.canonical_result_digest is not None
            and recomputed is not None
            and hmac.compare_digest(row.canonical_result_digest, recomputed)
        )
        return CashFlowResolvedSource(
            source_role=role,
            analysis_result_id=row.id,
            company_id=row.company_id,
            period_id=row.period_id,
            analysis_type=row.analysis_type,
            source_mode=row.source_mode,
            status=row.status,
            canonical_digest=row.canonical_result_digest,
            recomputed_payload_digest=recomputed,
            engine_version=row.engine_version,
            completed_at=_utc(row.completed_at),
            digest_verified=verified,
        )

    def _snapshot(
        self,
        session: Session,
        request: CashFlowPeriodResolutionRequest,
        company: Company,
    ) -> CashFlowResolutionSnapshot:
        current = session.execute(
            select(FinancialPeriod).where(
                FinancialPeriod.id == request.current_period_id,
                FinancialPeriod.company_id == request.company_id,
            )
        ).scalar_one_or_none()
        if current is None:
            raise CashFlowResolutionRepositoryError(CashFlowErrorCode.SOURCE_NOT_FOUND)

        if request.explicit_prior_period_id is not None:
            claimed = session.execute(
                select(FinancialPeriod).where(
                    FinancialPeriod.id == request.explicit_prior_period_id
                )
            ).scalar_one_or_none()
            if claimed is None:
                raise CashFlowResolutionRepositoryError(CashFlowErrorCode.SOURCE_NOT_FOUND)
            if claimed.company_id != request.company_id:
                raise CashFlowResolutionRepositoryError(CashFlowErrorCode.SOURCE_SCOPE_MISMATCH)

        prior_rows = tuple(session.execute(
            select(FinancialPeriod)
            .where(
                FinancialPeriod.company_id == request.company_id,
                FinancialPeriod.id != request.current_period_id,
                FinancialPeriod.end_date < current.end_date,
            )
            .order_by(FinancialPeriod.id)
        ).scalars())
        periods = (current,) + prior_rows
        period_ids = tuple(period.id for period in periods)
        analysis_rows = tuple(session.execute(
            select(FinancialAnalysisResult)
            .where(
                FinancialAnalysisResult.company_id == request.company_id,
                FinancialAnalysisResult.period_id.in_(period_ids),
                FinancialAnalysisResult.analysis_type.in_(tuple(_CURRENT_ROLE_BY_TYPE)),
            )
            .order_by(FinancialAnalysisResult.id)
        ).scalars())

        sources: list[CashFlowResolvedSource] = []
        for row in analysis_rows:
            if row.period_id == current.id:
                sources.append(self._source(row, _CURRENT_ROLE_BY_TYPE[row.analysis_type]))
            else:
                role = _PRIOR_ROLE_BY_TYPE.get(row.analysis_type)
                if role is not None:
                    sources.append(self._source(row, role))
        current_dto = self._period(current, company)
        prior_dtos = tuple(sorted(
            (self._period(row, company) for row in prior_rows),
            key=lambda item: str(item.period_id),
        ))
        source_dtos = tuple(sorted(
            sources,
            key=lambda item: (item.source_role.value, str(item.analysis_result_id)),
        ))
        projection = (
            current_dto,
            prior_dtos,
            tuple(
                (
                    source.source_role,
                    source.analysis_result_id,
                    source.period_id,
                    source.analysis_type,
                    source.status,
                    source.canonical_digest,
                    source.recomputed_payload_digest,
                    source.digest_verified,
                )
                for source in source_dtos
            ),
        )
        return CashFlowResolutionSnapshot(
            current_period=current_dto,
            prior_candidates=prior_dtos,
            source_candidates=source_dtos,
            candidate_set_digest=canonical_resolution_digest(
                "cash-flow/source-candidate-set/v1", projection
            ),
        )

    def load_resolution_snapshot(
        self,
        request: CashFlowPeriodResolutionRequest,
    ) -> CashFlowResolutionSnapshot:
        if type(request) is not CashFlowPeriodResolutionRequest:
            raise CashFlowResolutionRepositoryError(CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT)
        try:
            with self._sessions() as session, session.begin():
                self._set_timeouts(session)
                company = session.execute(
                    select(Company)
                    .where(Company.id == request.company_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if company is None:
                    raise CashFlowResolutionRepositoryError(CashFlowErrorCode.SOURCE_NOT_FOUND)
                if company.tenant_id != request.tenant_id:
                    raise CashFlowResolutionRepositoryError(CashFlowErrorCode.SOURCE_SCOPE_MISMATCH)
                first = self._snapshot(session, request, company)
                self._before_terminal_requery(session, request)
                session.expire_all()
                terminal = self._snapshot(session, request, company)
                if not hmac.compare_digest(first.candidate_set_digest, terminal.candidate_set_digest):
                    raise CashFlowResolutionRepositoryError(CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT)
                return terminal
        except CashFlowResolutionRepositoryError:
            raise
        except DBAPIError as exc:
            raise CashFlowResolutionRepositoryError(
                CashFlowErrorCode.SOURCE_RESOLUTION_UNAVAILABLE
            ) from None
        except (SQLAlchemyError, ValueError, TypeError):
            raise CashFlowResolutionRepositoryError(
                CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT
            ) from None
