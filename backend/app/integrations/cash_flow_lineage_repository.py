"""PostgreSQL adapter for immutable Cash Flow cross-period lineage."""

from __future__ import annotations

from hashlib import sha256
import hmac
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.engines.cash_flow.contracts import canonical_cash_flow_bytes
from app.engines.cash_flow.errors import CashFlowContractError
from app.engines.cash_flow.lineage import (
    CASH_FLOW_LINEAGE_POLICY_VERSION,
    CASH_FLOW_LINEAGE_SCHEMA_VERSION,
    CashFlowPortError,
    ResolvedCashFlowLineageEdge,
    VerifiedCashFlowLineage,
    canonical_cash_flow_lineage_set_digest,
    validate_cash_flow_lineage_role_set,
)
from app.engines.cash_flow.types import CashFlowErrorCode, CashFlowResultStatus, CashFlowSourceRole
from app.models.cash_flow_cross_period_lineage import CashFlowCrossPeriodLineage
from app.models.company import Company
from app.models.enums import AnalysisStatus, AnalysisType, SourceMode
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_analysis_result_source import FinancialAnalysisResultSource
from app.models.financial_document import FinancialDocument
from app.models.financial_period import FinancialPeriod
from app.orchestration_persistence.codec import canonical_json_bytes


_ROLE_TYPE = {
    CashFlowSourceRole.CURRENT_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    CashFlowSourceRole.PRIOR_BALANCE_SHEET: AnalysisType.BALANCE_SHEET,
    CashFlowSourceRole.CURRENT_INCOME_STATEMENT: AnalysisType.INCOME_STATEMENT,
    CashFlowSourceRole.CURRENT_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
    CashFlowSourceRole.PRIOR_TRIAL_BALANCE: AnalysisType.TRIAL_BALANCE,
}


def canonical_source_provenance_digest(
    source: FinancialAnalysisResult,
    bindings: tuple[FinancialAnalysisResultSource, ...],
) -> str:
    """Hash authoritative root semantics plus its frozen outbound bindings."""

    projection = (
        "cf.provenance_closure.v1",
        _source_semantics(source),
        tuple(
            sorted(
                (
                    item.role.value,
                    str(item.source_document_id) if item.source_document_id else None,
                    str(item.source_analysis_result_id) if item.source_analysis_result_id else None,
                )
                for item in bindings
            )
        ),
        (),
        (),
        (),
    )
    return sha256(b"cash-flow/source-provenance/v1\0" + canonical_cash_flow_bytes(projection)).hexdigest()


def _source_semantics(source: FinancialAnalysisResult) -> tuple:
    return (
        str(source.company_id),
        str(source.period_id),
        source.analysis_type.value,
        source.source_mode.value,
        source.status.value,
        source.engine_version,
        source.canonical_result_digest,
        str(source.document_id) if source.document_id else None,
    )


def authoritative_source_provenance_digest(
    session: Session,
    source: FinancialAnalysisResult,
) -> str:
    """Resolve the exact bounded recursive closure from authoritative rows."""

    root_bindings = tuple(session.scalars(
        select(FinancialAnalysisResultSource)
        .where(FinancialAnalysisResultSource.analysis_result_id == source.id)
        .order_by(FinancialAnalysisResultSource.id)
    ))
    root_edges = tuple(sorted(
        (
            item.role.value,
            str(item.source_document_id) if item.source_document_id else None,
            str(item.source_analysis_result_id) if item.source_analysis_result_id else None,
        )
        for item in root_bindings
    ))
    nodes: dict[UUID, tuple] = {}
    edges: set[tuple] = set()
    documents: dict[UUID, tuple] = {}

    def document(document_id: UUID) -> None:
        row = session.get(FinancialDocument, document_id)
        if row is None:
            raise _integrity()
        semantics = (
            str(row.id), str(row.company_id), str(row.period_id), row.document_type.value,
            row.processing_status.value, row.checksum, row.file_size,
        )
        previous = documents.setdefault(row.id, semantics)
        if previous != semantics:
            raise _integrity()

    def visit(owner: FinancialAnalysisResult, depth: int, path: tuple[UUID, ...]) -> None:
        if depth > 16 or owner.id in path:
            raise _integrity()
        bindings = tuple(session.scalars(
            select(FinancialAnalysisResultSource)
            .where(FinancialAnalysisResultSource.analysis_result_id == owner.id)
            .order_by(FinancialAnalysisResultSource.id)
        ))
        for binding in bindings:
            edge = (
                str(owner.id), binding.role.value,
                str(binding.source_document_id) if binding.source_document_id else None,
                str(binding.source_analysis_result_id) if binding.source_analysis_result_id else None,
            )
            if edge in edges:
                raise _integrity()
            edges.add(edge)
            if binding.source_document_id is not None:
                document(binding.source_document_id)
            else:
                child = session.get(FinancialAnalysisResult, binding.source_analysis_result_id)
                if child is None:
                    raise _integrity()
                if child.company_id != source.company_id:
                    raise _integrity()
                semantics = (str(child.id),) + _source_semantics(child)
                previous = nodes.setdefault(child.id, semantics)
                if previous != semantics:
                    raise _integrity()
                visit(child, depth + 1, path + (owner.id,))

    if source.document_id is not None:
        document(source.document_id)
    for binding in root_bindings:
        if binding.source_document_id is not None:
            document(binding.source_document_id)
        else:
            child = session.get(FinancialAnalysisResult, binding.source_analysis_result_id)
            if child is None or child.company_id != source.company_id:
                raise _integrity()
            nodes[child.id] = (str(child.id),) + _source_semantics(child)
            visit(child, 1, (source.id,))
    projection = (
        "cf.provenance_closure.v1",
        _source_semantics(source),
        root_edges,
        tuple(sorted(nodes.values())),
        tuple(sorted(edges)),
        tuple(sorted(documents.values())),
    )
    return sha256(
        b"cash-flow/source-provenance/v1\0" + canonical_cash_flow_bytes(projection)
    ).hexdigest()


def _integrity() -> CashFlowPortError:
    return CashFlowPortError(CashFlowErrorCode.PERSISTENCE_INTEGRITY_FAILURE)


class SqlAlchemyCashFlowLineageRepository:
    """Stages rows in the caller-owned terminal transaction; never commits."""

    def __init__(
        self,
        session: Session,
        *,
        statement_timeout_seconds: float = 5.0,
        lock_timeout_seconds: float = 1.0,
    ) -> None:
        if not 0 < lock_timeout_seconds <= statement_timeout_seconds <= 10:
            raise ValueError("lineage timeouts must be positive and bounded")
        self._session = session
        self._statement_timeout_ms = max(1, int(statement_timeout_seconds * 1000))
        self._lock_timeout_ms = max(1, int(lock_timeout_seconds * 1000))

    def _set_timeouts(self) -> None:
        if self._session.bind is not None and self._session.bind.dialect.name == "postgresql":
            self._session.execute(
                text("SELECT set_config('statement_timeout', :value, true)"),
                {"value": f"{self._statement_timeout_ms}ms"},
            )
            self._session.execute(
                text("SELECT set_config('lock_timeout', :value, true)"),
                {"value": f"{self._lock_timeout_ms}ms"},
            )

    def _company_lock(self, company_id: UUID, tenant_id: UUID) -> Company:
        self._set_timeouts()
        company = self._session.execute(
            select(Company).where(Company.id == company_id).with_for_update()
        ).scalar_one_or_none()
        if company is None or company.tenant_id != tenant_id:
            raise _integrity()
        return company

    def _source_edges(
        self,
        owner: FinancialAnalysisResult,
        tenant_id: UUID,
        company_id: UUID,
        current_period_id: UUID,
        prior_period_id: UUID | None,
        cash_flow_status: CashFlowResultStatus,
        lineage: tuple[ResolvedCashFlowLineageEdge, ...],
    ) -> tuple[ResolvedCashFlowLineageEdge, ...]:
        ordered = validate_cash_flow_lineage_role_set(cash_flow_status, lineage)
        if (
            owner.analysis_type is not AnalysisType.CASH_FLOW
            or owner.company_id != company_id
            or owner.period_id != current_period_id
            or owner.source_mode is not SourceMode.MULTI_SOURCE_DERIVED
            or owner.document_id is not None
            or owner.status is not AnalysisStatus.COMPLETED
            or owner.result_json is None
            or owner.canonical_result_digest is None
        ):
            raise _integrity()
        periods = tuple(
            self._session.scalars(
                select(FinancialPeriod).where(
                    FinancialPeriod.company_id == company_id,
                    FinancialPeriod.id.in_(
                        tuple(value for value in (current_period_id, prior_period_id) if value is not None)
                    ),
                )
            )
        )
        if {item.id for item in periods} != {
            value for value in (current_period_id, prior_period_id) if value is not None
        }:
            raise _integrity()
        for edge in ordered:
            expected_period = (
                prior_period_id if edge.source_role.value.startswith("prior_") else current_period_id
            )
            if expected_period is None or edge.source_period_id != expected_period:
                raise _integrity()
            source = self._session.get(FinancialAnalysisResult, edge.source_analysis_result_id)
            if (
                source is None
                or source.company_id != company_id
                or source.period_id != edge.source_period_id
                or source.analysis_type is not _ROLE_TYPE[edge.source_role]
                or source.analysis_type is not edge.source_analysis_type
                or source.status is not AnalysisStatus.COMPLETED
                or source.result_json is None
                or source.canonical_result_digest is None
                or source.engine_version != edge.source_engine_version
            ):
                raise _integrity()
            recomputed = sha256(canonical_json_bytes(source.result_json)).hexdigest()
            if not hmac.compare_digest(recomputed, source.canonical_result_digest):
                raise _integrity()
            if not hmac.compare_digest(edge.source_canonical_digest, source.canonical_result_digest):
                raise _integrity()
            provenance = authoritative_source_provenance_digest(self._session, source)
            if not hmac.compare_digest(edge.source_provenance_digest, provenance):
                raise _integrity()
        if ordered:
            current_digests = {item.current_period_descriptor_digest for item in ordered}
            prior_digests = {item.prior_period_descriptor_digest for item in ordered}
            proofs = {item.comparability_proof_digest for item in ordered}
            if len(current_digests) != 1 or len(prior_digests) != 1 or len(proofs) != 1:
                raise _integrity()
            if cash_flow_status is not CashFlowResultStatus.INSUFFICIENT_DATA and (
                None in prior_digests or None in proofs or prior_period_id is None
            ):
                raise _integrity()
        return ordered

    @staticmethod
    def _row_semantics(row: CashFlowCrossPeriodLineage) -> tuple:
        return (
            row.source_role,
            row.source_analysis_result_id,
            row.source_period_id,
            row.source_canonical_digest,
            row.source_provenance_digest,
            row.source_analysis_type,
            row.source_engine_version,
            row.current_period_descriptor_digest,
            row.prior_period_descriptor_digest,
            row.comparability_proof_digest,
        )

    @staticmethod
    def _edge_semantics(edge: ResolvedCashFlowLineageEdge) -> tuple:
        return (
            edge.source_role.value,
            edge.source_analysis_result_id,
            edge.source_period_id,
            edge.source_canonical_digest,
            edge.source_provenance_digest,
            edge.source_analysis_type.value,
            edge.source_engine_version,
            edge.current_period_descriptor_digest,
            edge.prior_period_descriptor_digest,
            edge.comparability_proof_digest,
        )

    def stage_exact_lineage(
        self,
        *,
        cash_flow_owner_id: UUID,
        tenant_id: UUID,
        company_id: UUID,
        current_period_id: UUID,
        prior_period_id: UUID | None,
        cash_flow_status: CashFlowResultStatus,
        lineage: tuple[ResolvedCashFlowLineageEdge, ...],
    ) -> None:
        try:
            self._company_lock(company_id, tenant_id)
            owner = self._session.get(FinancialAnalysisResult, cash_flow_owner_id)
            if owner is None:
                raise _integrity()
            ordered = self._source_edges(
                owner,
                tenant_id,
                company_id,
                current_period_id,
                prior_period_id,
                cash_flow_status,
                lineage,
            )
            existing = tuple(
                self._session.scalars(
                    select(CashFlowCrossPeriodLineage)
                    .where(CashFlowCrossPeriodLineage.cash_flow_analysis_result_id == cash_flow_owner_id)
                    .order_by(CashFlowCrossPeriodLineage.source_role)
                )
            )
            if existing:
                if tuple(sorted(self._row_semantics(row) for row in existing)) != tuple(
                    sorted(self._edge_semantics(edge) for edge in ordered)
                ):
                    raise _integrity()
                return
            rows = tuple(
                CashFlowCrossPeriodLineage(
                    cash_flow_analysis_result_id=cash_flow_owner_id,
                    tenant_id=tenant_id,
                    company_id=company_id,
                    current_period_id=current_period_id,
                    prior_period_id=prior_period_id,
                    source_period_id=edge.source_period_id,
                    source_analysis_result_id=edge.source_analysis_result_id,
                    source_role=edge.source_role.value,
                    source_canonical_digest=edge.source_canonical_digest,
                    source_provenance_digest=edge.source_provenance_digest,
                    source_analysis_type=edge.source_analysis_type.value,
                    source_engine_version=edge.source_engine_version,
                    current_period_descriptor_digest=edge.current_period_descriptor_digest,
                    prior_period_descriptor_digest=edge.prior_period_descriptor_digest,
                    comparability_proof_digest=edge.comparability_proof_digest,
                    lineage_schema_version=CASH_FLOW_LINEAGE_SCHEMA_VERSION,
                    lineage_policy_version=CASH_FLOW_LINEAGE_POLICY_VERSION,
                )
                for edge in ordered
            )
            self._session.add_all(rows)
            self._session.flush()
        except CashFlowPortError:
            raise
        except CashFlowContractError:
            raise _integrity() from None
        except IntegrityError:
            raise _integrity() from None
        except (DBAPIError, SQLAlchemyError):
            raise CashFlowPortError(CashFlowErrorCode.PERSISTENCE_UNAVAILABLE) from None

    def load_verified_lineage(self, cash_flow_owner_id: UUID) -> VerifiedCashFlowLineage:
        try:
            owner = self._session.get(FinancialAnalysisResult, cash_flow_owner_id)
            if owner is None or owner.analysis_type is not AnalysisType.CASH_FLOW or owner.result_json is None:
                raise _integrity()
            try:
                status = CashFlowResultStatus(owner.result_json["status"])
            except (KeyError, TypeError, ValueError):
                raise _integrity() from None
            rows = tuple(
                self._session.scalars(
                    select(CashFlowCrossPeriodLineage)
                    .where(CashFlowCrossPeriodLineage.cash_flow_analysis_result_id == cash_flow_owner_id)
                    .order_by(CashFlowCrossPeriodLineage.source_role)
                )
            )
            if status is not CashFlowResultStatus.INSUFFICIENT_DATA and not rows:
                raise _integrity()
            if rows:
                first = rows[0]
                tenant_id, company_id = first.tenant_id, first.company_id
                current_period_id, prior_period_id = first.current_period_id, first.prior_period_id
                self._company_lock(company_id, tenant_id)
                if any(
                    (row.tenant_id, row.company_id, row.current_period_id, row.prior_period_id)
                    != (tenant_id, company_id, current_period_id, prior_period_id)
                    for row in rows
                ):
                    raise _integrity()
            else:
                company = self._session.get(Company, owner.company_id)
                if company is None or company.tenant_id is None:
                    raise _integrity()
                tenant_id, company_id = company.tenant_id, owner.company_id
                current_period_id, prior_period_id = owner.period_id, None
                self._company_lock(company_id, tenant_id)
            edges = tuple(
                ResolvedCashFlowLineageEdge(
                    source_role=CashFlowSourceRole(row.source_role),
                    source_analysis_result_id=row.source_analysis_result_id,
                    source_period_id=row.source_period_id,
                    source_canonical_digest=row.source_canonical_digest,
                    source_provenance_digest=row.source_provenance_digest,
                    source_analysis_type=AnalysisType(row.source_analysis_type),
                    source_engine_version=row.source_engine_version,
                    current_period_descriptor_digest=row.current_period_descriptor_digest,
                    prior_period_descriptor_digest=row.prior_period_descriptor_digest,
                    comparability_proof_digest=row.comparability_proof_digest,
                )
                for row in rows
            )
            ordered = self._source_edges(
                owner,
                tenant_id,
                company_id,
                current_period_id,
                prior_period_id,
                status,
                edges,
            )
            payload_digest = sha256(canonical_json_bytes(owner.result_json)).hexdigest()
            if owner.canonical_result_digest is None or not hmac.compare_digest(
                owner.canonical_result_digest, payload_digest
            ):
                raise _integrity()
            source_set_digest = canonical_cash_flow_lineage_set_digest(
                owner_analysis_result_id=owner.id,
                current_period_id=current_period_id,
                prior_period_id=prior_period_id,
                owner_payload_digest=payload_digest,
                lineage=ordered,
            )
            return VerifiedCashFlowLineage(
                cash_flow_owner_id=owner.id,
                tenant_id=tenant_id,
                company_id=company_id,
                current_period_id=current_period_id,
                prior_period_id=prior_period_id,
                cash_flow_status=status,
                owner_payload_digest=payload_digest,
                lineage=ordered,
                source_set_digest=source_set_digest,
            )
        except CashFlowPortError:
            raise
        except CashFlowContractError:
            raise _integrity() from None
        except (DBAPIError, SQLAlchemyError):
            raise CashFlowPortError(CashFlowErrorCode.PERSISTENCE_UNAVAILABLE) from None
