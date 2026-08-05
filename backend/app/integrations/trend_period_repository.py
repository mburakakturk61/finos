"""Authoritative PostgreSQL adapter for Milestone 4.6C series resolution."""

from __future__ import annotations

from datetime import date, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import hmac
from typing import Callable

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.engines.multi_period_trend.registry import (
    TREND_METRIC_REGISTRY_V1,
    TrendMetricDefinition,
    TrendMetricRegistry,
    TrendSourceAnalysisType,
)
from app.engines.multi_period_trend.resolution_contracts import (
    TrendResolvedPeriod,
    TrendResolvedPeriodStatus,
    TrendResolvedPeriodType,
    TrendResolvedSourceCandidate,
    TrendResolvedSourceStatus,
    TrendSeriesRepositoryError,
    TrendSeriesResolutionErrorCode,
    TrendSeriesResolutionRequest,
    TrendSeriesResolutionSnapshot,
    TrendSourceSelectionRole,
    canonical_candidate_set_digest,
)
from app.engines.multi_period_trend.types import (
    TrendCoverageKind,
    TrendEvidenceLevel,
    TrendOneOffStatus,
    TrendRestatementProfile,
    TrendSourceEngineType,
)
from app.models.company import Company
from app.models.enums import AnalysisStatus, AnalysisType, PeriodCoverageKind, PeriodStatus, SourceMode
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_revision_metadata import FinancialAnalysisResultRevisionMetadata
from app.models.financial_period import FinancialPeriod
from app.orchestration_persistence.codec import canonical_json_bytes
from app.orchestration_persistence_v3.cash_flow_codec import decode_cash_flow_financial_result


_ANALYSIS_TYPE = {
    TrendSourceAnalysisType.BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    TrendSourceAnalysisType.INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
    TrendSourceAnalysisType.CASH_FLOW: AnalysisType.CASH_FLOW,
    TrendSourceAnalysisType.FINANCIAL_RATIOS: AnalysisType.FINANCIAL_RATIOS,
}
_ROLE_BY_ENGINE = {
    TrendSourceEngineType.BALANCE_SHEET: TrendSourceSelectionRole.BALANCE_SHEET,
    TrendSourceEngineType.INCOME_STATEMENT: TrendSourceSelectionRole.INCOME_STATEMENT,
    TrendSourceEngineType.CASH_FLOW: TrendSourceSelectionRole.CASH_FLOW,
    TrendSourceEngineType.FINANCIAL_RATIOS: TrendSourceSelectionRole.FINANCIAL_RATIOS,
}


def fiscal_calendar_reference(
    annual_start: date | None, annual_end: date | None
) -> str | None:
    if annual_start is None or annual_end is None:
        return None
    return (
        "fiscal-calendar:v1:"
        f"{annual_start.month:02d}-{annual_start.day:02d}:"
        f"{annual_end.month:02d}-{annual_end.day:02d}"
    )


def trend_company_lock_key(tenant_id, company_id) -> int:
    digest = sha256(
        b"multi-period-trend/company-lock/v1\0"
        + tenant_id.bytes
        + company_id.bytes
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    if type(value) is bool or type(value) not in {str, int, Decimal}:
        raise ValueError("source metric is not a canonical Decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("source metric Decimal is invalid") from None
    if not parsed.is_finite():
        raise ValueError("source metric Decimal is non-finite")
    return Decimal(0) if parsed.is_zero() else parsed


def _path(payload: dict, path: tuple[str, ...]):
    current = payload
    for segment in path:
        if type(current) is not dict or segment not in current:
            return False, None, None
        parent = current
        current = current[segment]
    return True, current, parent


def _source_status(status: AnalysisStatus) -> TrendResolvedSourceStatus:
    return TrendResolvedSourceStatus(status.value)


def _period_status(status: PeriodStatus) -> TrendResolvedPeriodStatus:
    return TrendResolvedPeriodStatus(status.value)


_RESTATEMENT_PROFILE = {
    "ORIGINAL": TrendRestatementProfile.ORIGINAL,
    "RESTATED": TrendRestatementProfile.RESTATED,
    "UNDECLARED_LEGACY": TrendRestatementProfile.UNDECLARED_LEGACY,
}


def _period(
    row: FinancialPeriod,
    company: Company,
    revision: FinancialAnalysisResultRevisionMetadata,
) -> TrendResolvedPeriod:
    reference = fiscal_calendar_reference(
        row.annual_reporting_period_start_date,
        row.annual_reporting_period_end_date,
    )
    if (
        row.accounting_basis_code is None
        or row.accounting_policy_version is None
        or row.cash_flow_coverage_kind is None
        or reference is None
    ):
        raise ValueError("period metadata is incomplete")
    return TrendResolvedPeriod(
        tenant_id=company.tenant_id,
        company_id=row.company_id,
        period_id=row.id,
        year=row.year,
        period_type=TrendResolvedPeriodType(row.period_type.value),
        fiscal_ordinal=row.period_number,
        start_date=row.start_date,
        end_date=row.end_date,
        months_covered=row.months_covered,
        status=_period_status(row.status),
        coverage_kind=TrendCoverageKind(row.cash_flow_coverage_kind.value),
        accounting_basis=row.accounting_basis_code,
        accounting_policy_version=row.accounting_policy_version,
        fiscal_calendar_reference=reference,
        currency=company.currency,
        monetary_unit_multiplier=Decimal("1"),
        restatement_profile=_RESTATEMENT_PROFILE[revision.restatement_state],
        restatement_revision=revision.restatement_revision,
        one_off_status=TrendOneOffStatus.UNKNOWN,
    )


def _plain_source_projection(
    row: FinancialAnalysisResult,
    definition: TrendMetricDefinition,
) -> tuple[Decimal | None, bool, TrendEvidenceLevel, str | None, str | None, str | None, str | None, bool]:
    payload = row.result_json
    if type(payload) is not dict:
        return None, False, TrendEvidenceLevel.UNAVAILABLE, None, None, None, None, False
    present, raw_value, parent = _path(payload, definition.source_field_path)
    value = _decimal(raw_value) if present and raw_value is not None else None
    if definition.source_engine_type in {
        TrendSourceEngineType.BALANCE_SHEET,
        TrendSourceEngineType.INCOME_STATEMENT,
    }:
        mode = payload.get("source_mode")
        evidence = (
            TrendEvidenceLevel.EXACT if mode == SourceMode.DIRECT_DOCUMENT.value
            else TrendEvidenceLevel.DERIVED if mode == SourceMode.TRIAL_BALANCE_DERIVED.value
            else TrendEvidenceLevel.UNAVAILABLE
        )
        provenance = (
            payload.get("analysis_type") == row.analysis_type.value
            and payload.get("engine_version") == row.engine_version
            and mode == row.source_mode.value
        )
        return value, present, evidence, mode, None, None, None, provenance
    status = parent.get("status") if type(parent) is dict else None
    reliability = parent.get("reliability") if type(parent) is dict else None
    calculable = status == "calculated" and value is not None
    ratio_status = "calculated" if calculable else "not_calculable"
    ratio_reliability = reliability if calculable and reliability in {"high", "medium", "medium_low", "low"} else "not_calculable"
    evidence = (
        TrendEvidenceLevel.EXACT if ratio_reliability == "high"
        else TrendEvidenceLevel.DERIVED if ratio_reliability in {"medium", "medium_low"}
        else TrendEvidenceLevel.ESTIMATED if ratio_reliability == "low"
        else TrendEvidenceLevel.UNAVAILABLE
    )
    provenance = (
        payload.get("analysis_type") == row.analysis_type.value
        and payload.get("engine_version") == row.engine_version
        and payload.get("source_mode") == row.source_mode.value
    )
    return value, present, evidence, None, ratio_status, ratio_reliability, payload.get("schema_version"), provenance


def _cash_flow_projection(
    row: FinancialAnalysisResult,
    definition: TrendMetricDefinition,
) -> tuple[Decimal | None, bool, TrendEvidenceLevel, str | None, str | None, str | None, str | None, bool]:
    if row.result_json is None or row.canonical_result_digest is None:
        return None, False, TrendEvidenceLevel.UNAVAILABLE, None, None, None, None, False
    result = decode_cash_flow_financial_result(row.result_json, row.canonical_result_digest)
    field = definition.source_field_path[0]
    value = getattr(result, field)
    line = next(item for item in result.line_items if item.line_code.value == field)
    if line.canonical_amount != value:
        raise ValueError("cash-flow summary/line evidence mismatch")
    evidence = TrendEvidenceLevel(line.evidence_kind.value)
    provenance = (
        result.cash_flow_model_version == row.engine_version
        and row.source_mode is SourceMode.MULTI_SOURCE_DERIVED
    )
    return value, True, evidence, None, None, None, result.cash_flow_schema_version, provenance


def _source(
    row: FinancialAnalysisResult,
    company: Company,
    definition: TrendMetricDefinition,
    *,
    authoritative_chain_head_verified: bool,
) -> TrendResolvedSourceCandidate:
    recomputed = (
        sha256(canonical_json_bytes(row.result_json)).hexdigest()
        if row.result_json is not None else None
    )
    digest_verified = (
        row.canonical_result_digest is not None
        and recomputed is not None
        and hmac.compare_digest(row.canonical_result_digest, recomputed)
    )
    projection = (
        _cash_flow_projection(row, definition)
        if definition.source_engine_type is TrendSourceEngineType.CASH_FLOW
        and digest_verified
        else _plain_source_projection(row, definition)
    )
    value, present, evidence, source_mode, ratio_status, ratio_reliability, schema_version, provenance = projection
    return TrendResolvedSourceCandidate(
        source_role=_ROLE_BY_ENGINE[definition.source_engine_type],
        analysis_result_id=row.id,
        tenant_id=company.tenant_id,
        company_id=row.company_id,
        period_id=row.period_id,
        source_engine_type=definition.source_engine_type,
        source_analysis_type=definition.source_analysis_type,
        source_status=_source_status(row.status),
        source_field_path=definition.source_field_path,
        source_schema_version=schema_version,
        source_model_version=row.engine_version,
        canonical_digest=row.canonical_result_digest,
        recomputed_digest=recomputed,
        digest_verified=digest_verified,
        provenance_verified=provenance,
        authoritative_chain_head_verified=authoritative_chain_head_verified,
        value=value,
        field_present=present,
        source_evidence=evidence,
        source_mode=source_mode,
        ratio_status=ratio_status,
        ratio_reliability=ratio_reliability,
    )


class SqlAlchemyTrendSeriesRepository:
    """One bounded transaction and one company advisory-lock namespace per load."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        registry: TrendMetricRegistry = TREND_METRIC_REGISTRY_V1,
        statement_timeout_seconds: float = 3.0,
        lock_timeout_seconds: float = 1.0,
    ) -> None:
        if not 0 < statement_timeout_seconds <= 5:
            raise ValueError("statement timeout must be in (0, 5]")
        if not 0 < lock_timeout_seconds <= statement_timeout_seconds:
            raise ValueError("lock timeout must be positive and bounded")
        self._sessions = session_factory
        self._registry = registry
        self._statement_timeout_ms = max(1, int(statement_timeout_seconds * 1000))
        self._lock_timeout_ms = max(1, int(lock_timeout_seconds * 1000))

    def _before_terminal_requery(self, session: Session, request: TrendSeriesResolutionRequest) -> None:
        """Deterministic race-test hook; production is a no-op."""

    def _timeouts_and_lock(self, session: Session, request: TrendSeriesResolutionRequest) -> None:
        session.execute(text("SELECT set_config('statement_timeout', :value, true)"), {"value": f"{self._statement_timeout_ms}ms"})
        session.execute(text("SELECT set_config('lock_timeout', :value, true)"), {"value": f"{self._lock_timeout_ms}ms"})
        session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": trend_company_lock_key(request.tenant_id, request.company_id)},
        )

    def _snapshot(
        self,
        session: Session,
        request: TrendSeriesResolutionRequest,
        definition: TrendMetricDefinition,
    ) -> TrendSeriesResolutionSnapshot:
        company = session.execute(select(Company).where(
            Company.id == request.company_id,
            Company.tenant_id == request.tenant_id,
        )).scalar_one_or_none()
        if company is None:
            raise TrendSeriesRepositoryError(TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND)
        period_rows = tuple(session.execute(
            select(FinancialPeriod).where(
                FinancialPeriod.company_id == request.company_id,
                FinancialPeriod.id.in_(request.explicit_period_ids),
            )
        ).scalars())
        if len(period_rows) != len(request.explicit_period_ids):
            raise TrendSeriesRepositoryError(TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND)
        expected_role = _ROLE_BY_ENGINE[definition.source_engine_type]
        if any(item.source_role is not expected_role for item in request.explicit_sources):
            raise TrendSeriesRepositoryError(TrendSeriesResolutionErrorCode.AMBIGUOUS_SOURCE)
        source_ids = tuple(item.analysis_result_id for item in request.explicit_sources)
        rows = tuple(session.execute(select(FinancialAnalysisResult).where(
            FinancialAnalysisResult.id.in_(source_ids),
            FinancialAnalysisResult.company_id == request.company_id,
            FinancialAnalysisResult.period_id.in_(request.explicit_period_ids),
            FinancialAnalysisResult.analysis_type == _ANALYSIS_TYPE[definition.source_analysis_type],
        )).scalars())
        if len(rows) != len(source_ids):
            raise TrendSeriesRepositoryError(TrendSeriesResolutionErrorCode.SOURCE_NOT_FOUND)
        revision_rows = tuple(session.execute(
            select(FinancialAnalysisResultRevisionMetadata).where(
                FinancialAnalysisResultRevisionMetadata.analysis_result_id.in_(source_ids)
            )
        ).scalars())
        if len(revision_rows) != len(source_ids):
            raise TrendSeriesRepositoryError(TrendSeriesResolutionErrorCode.INTEGRITY_FAILURE)
        revision_by_source = {item.analysis_result_id: item for item in revision_rows}
        if len(revision_by_source) != len(source_ids) or any(
            item.tenant_id != request.tenant_id
            or item.company_id != request.company_id
            or item.period_id != row.period_id
            or item.restatement_state not in _RESTATEMENT_PROFILE
            for row in rows
            for item in (revision_by_source[row.id],)
        ):
            raise TrendSeriesRepositoryError(TrendSeriesResolutionErrorCode.INTEGRITY_FAILURE)
        superseded_source_ids = set(session.execute(
            select(FinancialAnalysisResultRevisionMetadata.supersedes_analysis_result_id).where(
                FinancialAnalysisResultRevisionMetadata.supersedes_analysis_result_id.in_(source_ids)
            )
        ).scalars())
        source_row_by_period = {item.period_id: item for item in rows}
        if len(source_row_by_period) != len(rows):
            raise TrendSeriesRepositoryError(TrendSeriesResolutionErrorCode.AMBIGUOUS_SOURCE)
        periods = tuple(
            _period(row, company, revision_by_source[source_row_by_period[row.id].id])
            for row in period_rows
        )
        sources = tuple(
            _source(
                row,
                company,
                definition,
                authoritative_chain_head_verified=row.id not in superseded_source_ids,
            )
            for row in rows
        )
        digest = canonical_candidate_set_digest(request, periods, sources)
        return TrendSeriesResolutionSnapshot(periods, sources, digest)

    def load_resolution_snapshot(self, request: TrendSeriesResolutionRequest) -> TrendSeriesResolutionSnapshot:
        if type(request) is not TrendSeriesResolutionRequest:
            raise TrendSeriesRepositoryError(TrendSeriesResolutionErrorCode.INVALID_REQUEST)
        try:
            definition = self._registry.get(request.metric_code)
        except ValueError:
            raise TrendSeriesRepositoryError(TrendSeriesResolutionErrorCode.INVALID_REQUEST) from None
        try:
            with self._sessions() as session, session.begin():
                self._timeouts_and_lock(session, request)
                initial = self._snapshot(session, request, definition)
                self._before_terminal_requery(session, request)
                session.expire_all()
                terminal = self._snapshot(session, request, definition)
                if not hmac.compare_digest(initial.candidate_set_digest, terminal.candidate_set_digest):
                    raise TrendSeriesRepositoryError(TrendSeriesResolutionErrorCode.SOURCE_SET_CHANGED)
                return terminal
        except TrendSeriesRepositoryError:
            raise
        except DBAPIError as exc:
            sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
            code = (
                TrendSeriesResolutionErrorCode.STORE_TIMEOUT
                if sqlstate in {"57014", "55P03"}
                else TrendSeriesResolutionErrorCode.STORE_UNAVAILABLE
            )
            raise TrendSeriesRepositoryError(code) from None
        except (SQLAlchemyError, ValueError, TypeError, KeyError, AttributeError):
            raise TrendSeriesRepositoryError(TrendSeriesResolutionErrorCode.INTEGRITY_FAILURE) from None
