"""SQLAlchemy adapter for immutable Multi-Period Trend lineage."""

from __future__ import annotations

from hashlib import sha256
import hmac
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.engines.multi_period_trend import (
    TREND_LINEAGE_SCHEMA_VERSION,
    TREND_METRIC_REGISTRY_V1,
    TrendContractVersion,
    TrendEvidenceLevel,
    TrendLineageEdge,
    TrendLineagePortError,
    TrendLineagePortErrorCode,
    TrendLineageSet,
    TrendLineageSourceAnalysisType,
    TrendLineageSourceEngineCode,
    TrendLineageSourceRole,
    TrendPolicyVersion,
    VerifiedTrendLineage,
    build_trend_lineage_set,
)
from app.integrations.trend_period_repository import trend_company_lock_key
from app.models.company import Company
from app.models.enums import AnalysisStatus, AnalysisType, SourceMode
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_revision_metadata import FinancialAnalysisResultRevisionMetadata
from app.models.financial_period import FinancialPeriod
from app.models.trend_analysis_lineage import TrendAnalysisLineage
from app.orchestration_persistence.codec import canonical_json_bytes


_ANALYSIS_TYPE = {
    TrendLineageSourceAnalysisType.BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    TrendLineageSourceAnalysisType.INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
    TrendLineageSourceAnalysisType.CASH_FLOW: AnalysisType.CASH_FLOW,
    TrendLineageSourceAnalysisType.FINANCIAL_RATIOS: AnalysisType.FINANCIAL_RATIOS,
}
_SOURCE_VERSION = {
    TrendLineageSourceRole.BALANCE_SHEET: (None, "1.0.0"),
    TrendLineageSourceRole.INCOME_STATEMENT: (None, "1.0.0"),
    TrendLineageSourceRole.CASH_FLOW: ("1.0.0", "1.0.0"),
    TrendLineageSourceRole.FINANCIAL_RATIOS: ("1.0", "1.1.0"),
}


def _error(code: TrendLineagePortErrorCode) -> TrendLineagePortError:
    return TrendLineagePortError(code)


class SqlAlchemyTrendLineageRepository:
    """Stages lineage in the caller-owned terminal transaction; never commits."""

    def __init__(
        self,
        session: Session,
        *,
        statement_timeout_seconds: float = 5.0,
        lock_timeout_seconds: float = 1.0,
    ) -> None:
        if not 0 < lock_timeout_seconds <= statement_timeout_seconds <= 10:
            raise ValueError("trend lineage timeouts must be positive and bounded")
        self._session = session
        self._statement_timeout_ms = max(1, int(statement_timeout_seconds * 1000))
        self._lock_timeout_ms = max(1, int(lock_timeout_seconds * 1000))

    def _timeouts_and_lock(self, tenant_id: UUID, company_id: UUID) -> None:
        if self._session.bind is None or self._session.bind.dialect.name != "postgresql":
            raise _error(TrendLineagePortErrorCode.PERSISTENCE_UNAVAILABLE)
        self._session.execute(
            text("SELECT set_config('statement_timeout', :value, true)"),
            {"value": f"{self._statement_timeout_ms}ms"},
        )
        self._session.execute(
            text("SELECT set_config('lock_timeout', :value, true)"),
            {"value": f"{self._lock_timeout_ms}ms"},
        )
        self._session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": trend_company_lock_key(tenant_id, company_id)},
        )
        company = self._session.execute(
            select(Company).where(Company.id == company_id, Company.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if company is None:
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)

    @staticmethod
    def _payload_digest(owner: FinancialAnalysisResult) -> str:
        if owner.result_json is None or owner.canonical_result_digest is None:
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
        recomputed = sha256(canonical_json_bytes(owner.result_json)).hexdigest()
        if not hmac.compare_digest(recomputed, owner.canonical_result_digest):
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
        return recomputed

    @staticmethod
    def _validate_owner(owner: FinancialAnalysisResult, lineage_set: TrendLineageSet) -> str:
        if (
            owner.id != lineage_set.trend_analysis_result_id
            or owner.company_id != lineage_set.company_id
            or owner.period_id != lineage_set.anchor_period_id
            or owner.analysis_type is not AnalysisType.MULTI_PERIOD_TREND
            or owner.source_mode is not SourceMode.MULTI_SOURCE_DERIVED
            or owner.document_id is not None
            or owner.status is not AnalysisStatus.COMPLETED
            or owner.error_message is not None
            or owner.engine_version != "1.0.0"
        ):
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
        digest = SqlAlchemyTrendLineageRepository._payload_digest(owner)
        payload = owner.result_json
        expected = {
            "source_set_digest": lineage_set.source_set_digest,
            "lineage_count": len(lineage_set.lineage),
            "metric_registry_version": lineage_set.metric_registry_version,
            "metric_registry_digest": lineage_set.metric_registry_digest,
            "policy_version": lineage_set.policy_version.value,
            "contract_version": lineage_set.contract_version.value,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
        if (
            lineage_set.metric_registry_version != TREND_METRIC_REGISTRY_V1.registry_version
            or lineage_set.metric_registry_digest != TREND_METRIC_REGISTRY_V1.digest
            or lineage_set.policy_version is not TrendPolicyVersion.V1
            or lineage_set.contract_version is not TrendContractVersion.V1
        ):
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
        return digest

    def _validate_period_order(self, lineage_set: TrendLineageSet) -> None:
        period_by_ordinal = {
            edge.ordinal: edge.source_period_id for edge in lineage_set.lineage
        }
        rows = tuple(self._session.scalars(
            select(FinancialPeriod).where(
                FinancialPeriod.company_id == lineage_set.company_id,
                FinancialPeriod.id.in_(tuple(period_by_ordinal.values())),
            ).with_for_update()
        ))
        if len(rows) != len(set(period_by_ordinal.values())):
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
        by_id = {item.id: item for item in rows}
        ordered = tuple(by_id[period_by_ordinal[index]] for index in range(len(period_by_ordinal)))
        if any(
            left.start_date >= right.start_date
            or left.end_date >= right.end_date
            or left.end_date >= right.start_date
            for left, right in zip(ordered, ordered[1:])
        ):
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
        if ordered[-1].id != lineage_set.anchor_period_id:
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)

    def _validate_sources(self, lineage_set: TrendLineageSet) -> None:
        source_ids = tuple(item.source_analysis_result_id for item in lineage_set.lineage)
        sources = tuple(self._session.scalars(
            select(FinancialAnalysisResult)
            .where(FinancialAnalysisResult.id.in_(source_ids))
            .with_for_update()
        ))
        if len(sources) != len(source_ids):
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
        source_by_id = {item.id: item for item in sources}
        metadata = tuple(self._session.scalars(
            select(FinancialAnalysisResultRevisionMetadata).where(
                FinancialAnalysisResultRevisionMetadata.analysis_result_id.in_(source_ids)
            )
        ))
        metadata_by_id = {item.analysis_result_id: item for item in metadata}
        if len(metadata_by_id) != len(source_ids):
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
        superseded = set(self._session.scalars(
            select(FinancialAnalysisResultRevisionMetadata.supersedes_analysis_result_id).where(
                FinancialAnalysisResultRevisionMetadata.supersedes_analysis_result_id.in_(source_ids)
            )
        ))
        for edge in lineage_set.lineage:
            source = source_by_id[edge.source_analysis_result_id]
            if (
                source.company_id != lineage_set.company_id
                or source.period_id != edge.source_period_id
                or source.analysis_type is not _ANALYSIS_TYPE[edge.source_analysis_type]
                or source.status is not AnalysisStatus.COMPLETED
                or source.result_json is None
                or source.canonical_result_digest is None
                or source.engine_version != edge.source_model_version
                or _SOURCE_VERSION[edge.source_role]
                != (edge.source_schema_version, edge.source_model_version)
                or edge.source_analysis_result_id in superseded
            ):
                raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
            recomputed = sha256(canonical_json_bytes(source.result_json)).hexdigest()
            if not hmac.compare_digest(recomputed, source.canonical_result_digest) or not hmac.compare_digest(
                edge.source_canonical_digest, source.canonical_result_digest
            ):
                raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)

    @staticmethod
    def _row_semantics(row: TrendAnalysisLineage) -> tuple:
        return (
            row.ordinal, row.source_period_id, row.source_analysis_result_id,
            row.source_role, row.source_engine_code, row.source_analysis_type,
            row.source_canonical_digest, row.source_schema_version,
            row.source_model_version, row.observation_evidence,
            row.comparability_proof_digest, row.resolution_proof_reference,
            row.source_set_digest, row.lineage_schema_version,
        )

    @staticmethod
    def _edge_semantics(edge: TrendLineageEdge, source_set_digest: str) -> tuple:
        return (
            edge.ordinal, edge.source_period_id, edge.source_analysis_result_id,
            edge.source_role.value, edge.source_engine_code.value,
            edge.source_analysis_type.value, edge.source_canonical_digest,
            edge.source_schema_version, edge.source_model_version,
            edge.observation_evidence.value, edge.comparability_proof_digest,
            edge.resolution_proof_reference, source_set_digest,
            edge.lineage_schema_version,
        )

    def _existing_rows(self, owner_id: UUID) -> tuple[TrendAnalysisLineage, ...]:
        return tuple(self._session.scalars(
            select(TrendAnalysisLineage)
            .where(TrendAnalysisLineage.trend_analysis_result_id == owner_id)
            .order_by(TrendAnalysisLineage.ordinal, TrendAnalysisLineage.source_role)
        ))

    def stage_exact_lineage(self, lineage_set: TrendLineageSet) -> VerifiedTrendLineage:
        if type(lineage_set) is not TrendLineageSet:
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
        try:
            self._timeouts_and_lock(lineage_set.tenant_id, lineage_set.company_id)
            owner = self._session.get(FinancialAnalysisResult, lineage_set.trend_analysis_result_id)
            if owner is None:
                raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
            existing = self._existing_rows(owner.id)
            if existing and (
                owner.result_json is None
                or owner.result_json.get("source_set_digest") != lineage_set.source_set_digest
            ):
                raise _error(TrendLineagePortErrorCode.CONFLICT)
            owner_digest = self._validate_owner(owner, lineage_set)
            self._validate_period_order(lineage_set)
            self._validate_sources(lineage_set)
            expected_semantics = tuple(
                sorted(self._edge_semantics(item, lineage_set.source_set_digest) for item in lineage_set.lineage)
            )
            if existing:
                if tuple(sorted(self._row_semantics(item) for item in existing)) != expected_semantics:
                    raise _error(TrendLineagePortErrorCode.CONFLICT)
                return VerifiedTrendLineage(owner_digest, lineage_set)
            metadata = self._session.get(FinancialAnalysisResultRevisionMetadata, owner.id)
            if metadata is None:
                self._session.add(FinancialAnalysisResultRevisionMetadata(
                    analysis_result_id=owner.id,
                    tenant_id=lineage_set.tenant_id,
                    company_id=lineage_set.company_id,
                    period_id=lineage_set.anchor_period_id,
                    restatement_state="ORIGINAL",
                    restatement_revision=0,
                    restatement_reason="NONE",
                    supersedes_analysis_result_id=None,
                    metadata_schema_version="1.0.0",
                ))
            self._session.add_all(tuple(
                TrendAnalysisLineage(
                    trend_analysis_result_id=owner.id,
                    tenant_id=lineage_set.tenant_id,
                    company_id=lineage_set.company_id,
                    anchor_period_id=lineage_set.anchor_period_id,
                    ordinal=edge.ordinal,
                    source_period_id=edge.source_period_id,
                    source_analysis_result_id=edge.source_analysis_result_id,
                    source_role=edge.source_role.value,
                    source_engine_code=edge.source_engine_code.value,
                    source_analysis_type=edge.source_analysis_type.value,
                    source_canonical_digest=edge.source_canonical_digest,
                    source_schema_version=edge.source_schema_version,
                    source_model_version=edge.source_model_version,
                    observation_evidence=edge.observation_evidence.value,
                    comparability_proof_digest=edge.comparability_proof_digest,
                    resolution_proof_reference=edge.resolution_proof_reference,
                    source_set_digest=lineage_set.source_set_digest,
                    lineage_schema_version=TREND_LINEAGE_SCHEMA_VERSION,
                )
                for edge in lineage_set.lineage
            ))
            self._session.flush()
            return VerifiedTrendLineage(owner_digest, lineage_set)
        except TrendLineagePortError:
            raise
        except IntegrityError:
            raise _error(TrendLineagePortErrorCode.CONFLICT) from None
        except OperationalError as exc:
            code = getattr(getattr(exc, "orig", None), "sqlstate", None)
            mapped = (
                TrendLineagePortErrorCode.LOCK_TIMEOUT
                if code in {"55P03", "57014"}
                else TrendLineagePortErrorCode.PERSISTENCE_UNAVAILABLE
            )
            raise _error(mapped) from None
        except (DBAPIError, SQLAlchemyError):
            raise _error(TrendLineagePortErrorCode.PERSISTENCE_UNAVAILABLE) from None
        except Exception:
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE) from None

    def load_verified_lineage(self, trend_analysis_result_id: UUID) -> VerifiedTrendLineage:
        if type(trend_analysis_result_id) is not UUID:
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
        try:
            owner = self._session.get(FinancialAnalysisResult, trend_analysis_result_id)
            if owner is None or owner.analysis_type is not AnalysisType.MULTI_PERIOD_TREND:
                raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
            company = self._session.get(Company, owner.company_id)
            if company is None or company.tenant_id is None:
                raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
            self._timeouts_and_lock(company.tenant_id, owner.company_id)
            rows = self._existing_rows(owner.id)
            if not rows:
                raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
            tenant_id, company_id, anchor_period_id = rows[0].tenant_id, rows[0].company_id, rows[0].anchor_period_id
            if any(
                (row.tenant_id, row.company_id, row.anchor_period_id)
                != (tenant_id, company_id, anchor_period_id)
                for row in rows
            ):
                raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
            payload = owner.result_json or {}
            if any(
                row.source_set_digest != payload.get("source_set_digest")
                or row.lineage_schema_version != TREND_LINEAGE_SCHEMA_VERSION
                for row in rows
            ):
                raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
            edges = tuple(
                TrendLineageEdge(
                    ordinal=row.ordinal,
                    source_period_id=row.source_period_id,
                    source_analysis_result_id=row.source_analysis_result_id,
                    source_role=TrendLineageSourceRole(row.source_role),
                    source_engine_code=TrendLineageSourceEngineCode(row.source_engine_code),
                    source_analysis_type=TrendLineageSourceAnalysisType(row.source_analysis_type),
                    source_canonical_digest=row.source_canonical_digest,
                    source_schema_version=row.source_schema_version,
                    source_model_version=row.source_model_version,
                    observation_evidence=TrendEvidenceLevel(row.observation_evidence),
                    comparability_proof_digest=row.comparability_proof_digest,
                    resolution_proof_reference=row.resolution_proof_reference,
                    lineage_schema_version=row.lineage_schema_version,
                )
                for row in rows
            )
            lineage_set = build_trend_lineage_set(
                trend_analysis_result_id=owner.id,
                tenant_id=tenant_id,
                company_id=company_id,
                anchor_period_id=anchor_period_id,
                metric_registry_version=payload.get("metric_registry_version"),
                metric_registry_digest=payload.get("metric_registry_digest"),
                policy_version=TrendPolicyVersion(payload.get("policy_version")),
                contract_version=TrendContractVersion(payload.get("contract_version")),
                lineage=edges,
            )
            if not hmac.compare_digest(lineage_set.source_set_digest, payload.get("source_set_digest", "")):
                raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE)
            owner_digest = self._validate_owner(owner, lineage_set)
            self._validate_period_order(lineage_set)
            self._validate_sources(lineage_set)
            return VerifiedTrendLineage(owner_digest, lineage_set)
        except TrendLineagePortError:
            raise
        except OperationalError as exc:
            code = getattr(getattr(exc, "orig", None), "sqlstate", None)
            mapped = (
                TrendLineagePortErrorCode.LOCK_TIMEOUT
                if code in {"55P03", "57014"}
                else TrendLineagePortErrorCode.PERSISTENCE_UNAVAILABLE
            )
            raise _error(mapped) from None
        except (DBAPIError, SQLAlchemyError):
            raise _error(TrendLineagePortErrorCode.PERSISTENCE_UNAVAILABLE) from None
        except Exception:
            raise _error(TrendLineagePortErrorCode.INTEGRITY_FAILURE) from None
