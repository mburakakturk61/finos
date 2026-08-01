"""Trusted SQLAlchemy-backed source materialization adapters."""

from __future__ import annotations

import hashlib
import hmac
import io
import uuid
import zipfile
from pathlib import Path

from sqlalchemy import select, text

from app.integrations.analysis_http.contracts import (
    AuthenticationContext,
    InputResolutionCode,
    InputResolutionError,
    ResolvedDocumentInput,
    ResolvedTrialBalanceInput,
)
from app.models.analysis_run_scope_claim import AnalysisRunScopeClaim
from app.models.enums import AnalysisStatus, AnalysisType, DocumentType, ProcessingStatus
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_document import FinancialDocument
from app.orchestration_persistence.codec import canonical_json_bytes
from app.integrations.analysis_http.contracts import RunOwnershipView


MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
_DOCUMENT_TYPES = {
    "fs_balance_sheet": DocumentType.BALANCE_SHEET,
    "fs_income_statement": DocumentType.INCOME_STATEMENT,
}


class FilesystemDocumentContentStore:
    """Configured external content adapter; uploads are not inferred from metadata."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def read_document_content(self, document_id: uuid.UUID, checksum: str) -> bytes:
        path = (self.root / str(document_id)).resolve()
        if self.root not in path.parents:
            raise ValueError("Document content key escapes configured root.")
        return path.read_bytes()

    def readiness_check(self, deadline) -> bool:
        return deadline.tzinfo is not None and self.root.is_dir()


class SqlAlchemyDocumentInputResolver:
    def __init__(self, session_factory, content_store, *, timeout_seconds: float = 3.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Resolver timeout must be positive.")
        self.session_factory = session_factory
        self.content_store = content_store
        self.timeout_seconds = timeout_seconds

    def resolve_document_input(
        self, *, document_id, company_id, financial_period_id,
        expected_engine_code, authentication: AuthenticationContext,
    ) -> ResolvedDocumentInput:
        if not authentication.subject_id:
            raise InputResolutionError(InputResolutionCode.SOURCE_UNAUTHORIZED)
        try:
            with self.session_factory() as session, session.begin():
                document = session.scalar(select(FinancialDocument).where(FinancialDocument.id == document_id))
                if document is None:
                    raise InputResolutionError(InputResolutionCode.SOURCE_NOT_FOUND)
                if (document.company_id, document.period_id) != (company_id, financial_period_id):
                    raise InputResolutionError(InputResolutionCode.SOURCE_SCOPE_MISMATCH)
                expected_type = _DOCUMENT_TYPES.get(
                    str(getattr(expected_engine_code, "value", expected_engine_code))
                )
                if expected_type is None or document.document_type is not expected_type:
                    raise InputResolutionError(InputResolutionCode.SOURCE_TYPE_INVALID)
                if document.processing_status is not ProcessingStatus.COMPLETED:
                    raise InputResolutionError(InputResolutionCode.SOURCE_STATUS_INVALID)
                metadata = (
                    document.original_filename, document.mime_type, document.file_size,
                    document.checksum, document.document_type.value,
                )
            try:
                content = self.content_store.read_document_content(document_id, metadata[3])
            except InputResolutionError:
                raise
            except FileNotFoundError as exc:
                raise InputResolutionError(InputResolutionCode.SOURCE_CONTENT_UNAVAILABLE) from exc
            except Exception as exc:
                raise InputResolutionError(InputResolutionCode.SOURCE_RESOLVER_UNAVAILABLE) from exc
            _validate_document_content(content, *metadata[:4])
            return ResolvedDocumentInput(
                document_id, company_id, financial_period_id, bytes(content),
                metadata[0], metadata[1], metadata[3], metadata[4],
            )
        except InputResolutionError:
            raise
        except Exception as exc:
            raise InputResolutionError(InputResolutionCode.SOURCE_RESOLVER_UNAVAILABLE) from exc

    def readiness_check(self, deadline) -> bool:
        if deadline.tzinfo is None:
            return False
        with self.session_factory() as session:
            session.execute(text("SELECT 1"))
        checker = getattr(self.content_store, "readiness_check", None)
        return bool(checker(deadline)) if checker is not None else False


class SqlAlchemyAnalysisResultInputResolver:
    def __init__(self, session_factory, *, timeout_seconds: float = 3.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Resolver timeout must be positive.")
        self.session_factory = session_factory
        self.timeout_seconds = timeout_seconds

    def resolve_trial_balance_input(
        self, *, analysis_result_id, company_id, financial_period_id,
        authentication: AuthenticationContext,
    ) -> ResolvedTrialBalanceInput:
        if not authentication.subject_id:
            raise InputResolutionError(InputResolutionCode.SOURCE_UNAUTHORIZED)
        try:
            with self.session_factory() as session, session.begin():
                result = session.scalar(select(FinancialAnalysisResult).where(
                    FinancialAnalysisResult.id == analysis_result_id
                ))
                if result is None:
                    raise InputResolutionError(InputResolutionCode.SOURCE_NOT_FOUND)
                if (result.company_id, result.period_id) != (company_id, financial_period_id):
                    raise InputResolutionError(InputResolutionCode.SOURCE_SCOPE_MISMATCH)
                if result.analysis_type is not AnalysisType.TRIAL_BALANCE:
                    raise InputResolutionError(InputResolutionCode.SOURCE_TYPE_INVALID)
                if result.status is not AnalysisStatus.COMPLETED or not isinstance(result.result_json, dict):
                    raise InputResolutionError(InputResolutionCode.SOURCE_STATUS_INVALID)
                if not result.canonical_result_digest:
                    raise InputResolutionError(InputResolutionCode.SOURCE_CANONICAL_DIGEST_MISMATCH)
                payload = result.result_json
                digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
                if not hmac.compare_digest(digest, result.canonical_result_digest):
                    raise InputResolutionError(InputResolutionCode.SOURCE_CANONICAL_DIGEST_MISMATCH)
                return ResolvedTrialBalanceInput(
                    result.id, result.company_id, result.period_id, payload,
                    digest, result.analysis_type.value, result.status.value,
                )
        except InputResolutionError:
            raise
        except Exception as exc:
            raise InputResolutionError(InputResolutionCode.SOURCE_RESOLVER_UNAVAILABLE) from exc

    def readiness_check(self, deadline) -> bool:
        if deadline.tzinfo is None:
            return False
        with self.session_factory() as session:
            session.execute(text("SELECT 1"))
        return True


class SqlAlchemyRunOwnershipInspector:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def load(self, run_id: str) -> RunOwnershipView | None:
        with self.session_factory() as session, session.begin():
            row = session.scalar(select(AnalysisRunScopeClaim).where(AnalysisRunScopeClaim.run_id == run_id))
            if row is None:
                return None
            return RunOwnershipView(
                row.run_id, row.company_id, row.financial_period_id, row.tenant_id,
                row.operation_kind, row.original_operation, row.previous_run_id,
                row.initiating_subject_id, row.status,
            )


def _validate_document_content(
    content: bytes, filename: str, mime_type: str, declared_size: int, checksum: str,
) -> None:
    if not content or len(content) > MAX_DOCUMENT_BYTES or len(content) != declared_size:
        raise InputResolutionError(InputResolutionCode.SOURCE_CONTENT_UNAVAILABLE)
    actual = hashlib.sha256(content).hexdigest()
    if len(checksum) != 64 or not hmac.compare_digest(actual, checksum):
        raise InputResolutionError(InputResolutionCode.SOURCE_CHECKSUM_MISMATCH)
    lowered = filename.lower()
    if lowered.endswith(".xlsx"):
        if mime_type != "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            raise InputResolutionError(InputResolutionCode.SOURCE_TYPE_INVALID)
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = frozenset(archive.namelist())
                if "[Content_Types].xml" not in names or not any(name.startswith("xl/") for name in names):
                    raise InputResolutionError(InputResolutionCode.SOURCE_TYPE_INVALID)
        except InputResolutionError:
            raise
        except Exception as exc:
            raise InputResolutionError(InputResolutionCode.SOURCE_TYPE_INVALID) from exc
        return
    if lowered.endswith(".pdf"):
        if mime_type != "application/pdf" or not content.startswith(b"%PDF-"):
            raise InputResolutionError(InputResolutionCode.SOURCE_TYPE_INVALID)
        return
    raise InputResolutionError(InputResolutionCode.SOURCE_TYPE_INVALID)
