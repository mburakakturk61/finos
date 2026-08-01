"""Finite process-local analysis admission control."""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from datetime import datetime

from app.integrations.analysis_http.contracts import AdmissionLease


class ProcessLocalAnalysisAdmissionControl:
    def __init__(
        self, *, global_limit: int, tenant_limit: int,
        subject_limit: int | None, retry_after_seconds: int,
    ) -> None:
        if global_limit < 1 or tenant_limit < 1 or tenant_limit > global_limit:
            raise ValueError("Analysis admission limits are invalid.")
        if subject_limit is not None and (subject_limit < 1 or subject_limit > tenant_limit):
            raise ValueError("Subject admission limit is invalid.")
        if not 1 <= retry_after_seconds <= 60:
            raise ValueError("Retry-After must be between 1 and 60 seconds.")
        self.global_limit = global_limit
        self.tenant_limit = tenant_limit
        self.subject_limit = subject_limit
        self.retry_after_seconds = retry_after_seconds
        self._lock = threading.Lock()
        self._leases: dict[str, AdmissionLease] = {}
        self._tenant_counts: Counter[str] = Counter()
        self._subject_counts: Counter[tuple[str, str]] = Counter()

    def try_acquire(self, *, tenant_id, subject_id, run_id, acquired_at):
        tenant_key = tenant_id if tenant_id is not None else "<none>"
        subject_key = (tenant_key, subject_id)
        with self._lock:
            if len(self._leases) >= self.global_limit:
                return None
            if self._tenant_counts[tenant_key] >= self.tenant_limit:
                return None
            if self.subject_limit is not None and self._subject_counts[subject_key] >= self.subject_limit:
                return None
            lease = AdmissionLease(uuid.uuid4().hex, tenant_key, subject_id, acquired_at)
            self._leases[lease.lease_id] = lease
            self._tenant_counts[tenant_key] += 1
            self._subject_counts[subject_key] += 1
            return lease

    def release(self, lease: AdmissionLease) -> None:
        with self._lock:
            existing = self._leases.pop(lease.lease_id, None)
            if existing is None:
                return
            subject_key = (existing.tenant_key, existing.subject_id)
            self._tenant_counts[existing.tenant_key] -= 1
            self._subject_counts[subject_key] -= 1
            if self._tenant_counts[existing.tenant_key] <= 0:
                del self._tenant_counts[existing.tenant_key]
            if self._subject_counts[subject_key] <= 0:
                del self._subject_counts[subject_key]

    def readiness_check(self, deadline: datetime) -> bool:
        return (
            deadline.tzinfo is not None
            and self.global_limit > 0
            and self.tenant_limit > 0
            and 1 <= self.retry_after_seconds <= 60
        )
