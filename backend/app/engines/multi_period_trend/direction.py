"""Deterministic mathematical direction classification for Milestone 4.6D."""

from __future__ import annotations

from decimal import Decimal

from .contracts import TrendTransition
from .types import TrendDirection, TrendTransitionKind


def classify_pair_direction(
    absolute_change: Decimal | None,
    stable_tolerance: Decimal,
    transition_kind: TrendTransitionKind,
) -> TrendDirection:
    """Classify numeric direction without implying financial favorability."""

    if type(stable_tolerance) is not Decimal or not stable_tolerance.is_finite() or stable_tolerance < 0:
        raise ValueError("stable tolerance must be a non-negative finite Decimal")
    if type(transition_kind) is not TrendTransitionKind:
        raise ValueError("transition kind must be exact enum")
    if transition_kind is TrendTransitionKind.UNAVAILABLE_MISSING_INPUT:
        return TrendDirection.INSUFFICIENT_DATA
    if transition_kind is TrendTransitionKind.ABSOLUTE_ONLY_SIGN_CHANGE:
        return TrendDirection.SIGN_CHANGE
    if type(absolute_change) is not Decimal or not absolute_change.is_finite():
        raise ValueError("available transition requires finite Decimal change")
    if abs(absolute_change) <= stable_tolerance:
        return TrendDirection.STABLE
    return TrendDirection.INCREASING if absolute_change > 0 else TrendDirection.DECREASING


def aggregate_direction(transitions: tuple[TrendTransition, ...]) -> TrendDirection:
    """Apply the closed 4.6 direction precedence to one contiguous segment."""

    if type(transitions) is not tuple or any(type(item) is not TrendTransition for item in transitions):
        raise ValueError("transitions must be an exact immutable tuple")
    valid = tuple(
        item for item in transitions
        if item.direction is not TrendDirection.INSUFFICIENT_DATA
    )
    endpoint_ids = {item.from_period_id for item in valid} | {item.to_period_id for item in valid}
    if len(endpoint_ids) < 3 or len(valid) < 2:
        return TrendDirection.INSUFFICIENT_DATA
    if any(item.direction is TrendDirection.SIGN_CHANGE for item in valid):
        return TrendDirection.SIGN_CHANGE
    directions = {item.direction for item in valid}
    if directions == {TrendDirection.STABLE}:
        return TrendDirection.STABLE
    if directions <= {TrendDirection.STABLE, TrendDirection.INCREASING}:
        return TrendDirection.INCREASING
    if directions <= {TrendDirection.STABLE, TrendDirection.DECREASING}:
        return TrendDirection.DECREASING
    return TrendDirection.MIXED
