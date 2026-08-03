"""Deterministic monetary helpers for the Milestone 4.5D pure core."""

from __future__ import annotations

from decimal import Decimal, Inexact, InvalidOperation, Overflow, Rounded, localcontext
from hashlib import sha256
import json

from .contracts import (
    CashFlowAccountEvidence,
    CashFlowEvidenceReference,
    CashFlowNonCashBridgeComponent,
    canonical_cash_flow_bytes,
    canonical_cash_flow_digest,
)
from .errors import CashFlowContractError
from .policy import quantize_money
from .types import CashFlowEvidenceKind


class CashFlowCoreIntegrityError(CashFlowContractError):
    """A safe internal signal for contradictory authoritative evidence."""


class CashFlowCoreDecimalError(CashFlowContractError):
    """A safe internal signal for unsupported monetary arithmetic."""


class CashFlowCorePolicyError(CashFlowContractError):
    """A safe internal signal for an unsupported accounting/presentation policy."""


class CashFlowCoreMappingVersionError(CashFlowContractError):
    """A safe internal signal for an unsupported mapping registry version."""


def exact_sum(values: tuple[Decimal, ...]) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 64
            context.Emax = 999999
            context.Emin = -999999
            context.traps[InvalidOperation] = True
            context.traps[Overflow] = True
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            return sum(values, Decimal("0"))
    except (InvalidOperation, Overflow, Inexact, Rounded) as exc:
        raise CashFlowCoreDecimalError("cash-flow arithmetic is not exact") from None


def exact_subtract(left: Decimal, right: Decimal) -> Decimal:
    return exact_sum((left, -right))


def finalize_leaves(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    try:
        return tuple(quantize_money(value) for value in values)
    except CashFlowContractError:
        raise CashFlowCoreDecimalError("cash-flow monetary leaf is invalid") from None


def finalized_sum(values: tuple[Decimal, ...]) -> Decimal:
    return exact_sum(finalize_leaves(values))


def weakest_evidence(kinds: tuple[CashFlowEvidenceKind, ...]) -> CashFlowEvidenceKind:
    if not kinds:
        return CashFlowEvidenceKind.UNAVAILABLE
    rank = {
        CashFlowEvidenceKind.EXACT: 0,
        CashFlowEvidenceKind.DERIVED: 1,
        CashFlowEvidenceKind.ESTIMATED: 2,
        CashFlowEvidenceKind.UNAVAILABLE: 3,
    }
    return max(kinds, key=rank.__getitem__)


def _canonical_node(value: object) -> object:
    return json.loads(canonical_cash_flow_bytes(value).decode("utf-8"))


def canonical_evidence_bundle_bytes(
    account_evidence: tuple[CashFlowAccountEvidence, ...],
    bridge_components: tuple[CashFlowNonCashBridgeComponent, ...],
) -> bytes:
    payload = {
        "schema": "cf.evidence_bundle.v1",
        "account_evidence": [_canonical_node(value) for value in account_evidence],
        "noncash_bridge_components": [_canonical_node(value) for value in bridge_components],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_evidence_bundle_digest(
    account_evidence: tuple[CashFlowAccountEvidence, ...],
    bridge_components: tuple[CashFlowNonCashBridgeComponent, ...],
) -> str:
    return sha256(
        b"cash-flow/evidence-bundle/v1\0"
        + canonical_evidence_bundle_bytes(account_evidence, bridge_components)
    ).hexdigest()


def computation_draft_digest(draft: object) -> str:
    return sha256(
        b"cash-flow/computation-draft/v1\0" + canonical_cash_flow_bytes(draft)
    ).hexdigest()


def canonical_references(
    references: tuple[CashFlowEvidenceReference, ...],
) -> tuple[CashFlowEvidenceReference, ...]:
    keyed = tuple(sorted(
        ((canonical_cash_flow_digest(value), value) for value in references),
        key=lambda item: item[0],
    ))
    if len({digest for digest, _value in keyed}) != len(keyed):
        raise CashFlowCoreIntegrityError("duplicate cash-flow evidence reference")
    return tuple(value for _digest, value in keyed)
