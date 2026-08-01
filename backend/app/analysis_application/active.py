"""Process-local cooperative cancellation registry; never an idempotency source."""

from __future__ import annotations

import threading
import uuid

from app.analysis_application.contracts import ApplicationScopeDTO, CancellationStatus
from app.analysis_application.internal_types import LocalCancelResult
from app.analysis_application.ports import LocalExecutionDiagnostics, LocalExecutionToken


class LocalActiveExecutionRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, object]] = {}

    def register(self, run_id: str, scope: ApplicationScopeDTO, correlation_id: str) -> LocalExecutionToken:
        token = LocalExecutionToken(uuid.uuid4().hex, run_id, scope)
        with self._lock:
            self._items[token.token_id] = {
                "token": token, "correlation_id": correlation_id,
                "phase": "registered", "cancelled": False,
            }
        return token

    def unregister(self, token: LocalExecutionToken) -> None:
        with self._lock:
            self._items.pop(token.token_id, None)

    def request_cancel(self, run_id: str, scope: ApplicationScopeDTO) -> LocalCancelResult:
        with self._lock:
            matches = [item for item in self._items.values() if item["token"].run_id == run_id and item["token"].scope == scope]
            if not matches:
                return LocalCancelResult(CancellationStatus.NOT_ACTIVE)
            if all(item["cancelled"] for item in matches):
                return LocalCancelResult(CancellationStatus.ALREADY_REQUESTED)
            for item in matches:
                item["cancelled"] = True
            return LocalCancelResult(CancellationStatus.ACCEPTED)

    def is_active(self, run_id: str, scope: ApplicationScopeDTO) -> bool:
        with self._lock:
            return any(item["token"].run_id == run_id and item["token"].scope == scope for item in self._items.values())

    def get_local_diagnostics(self, run_id: str, scope: ApplicationScopeDTO) -> LocalExecutionDiagnostics | None:
        with self._lock:
            for item in self._items.values():
                token = item["token"]
                if token.run_id == run_id and token.scope == scope:
                    return LocalExecutionDiagnostics(run_id, item["correlation_id"], item["phase"], bool(item["cancelled"]))
        return None
