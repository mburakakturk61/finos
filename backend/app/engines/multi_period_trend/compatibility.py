"""Fail-closed source-version compatibility for the trend metric registry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TrendSourceCompatibilityStatus(str, Enum):
    ACCEPTED = "accepted"
    SCHEMA_VERSION_UNSUPPORTED = "schema_version_unsupported"
    MODEL_VERSION_UNSUPPORTED = "model_version_unsupported"
    VERSION_PAIR_UNSUPPORTED = "version_pair_unsupported"


class _SafeCompatibilityValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    __str__ = __repr__


def _version(value: object, name: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str or not value or len(value) > 64:
        raise ValueError(f"{name} must be bounded non-empty text")
    if any(part == "" or not part.isdigit() for part in value.split(".")):
        raise ValueError(f"{name} must be a numeric dotted version")
    return value


@dataclass(frozen=True, repr=False, order=True)
class TrendSourceVersion(_SafeCompatibilityValue):
    schema_version: str | None
    model_version: str

    def __post_init__(self) -> None:
        _version(self.schema_version, "schema_version", nullable=True)
        _version(self.model_version, "model_version")


@dataclass(frozen=True, repr=False)
class TrendSourceCompatibilityDecision(_SafeCompatibilityValue):
    status: TrendSourceCompatibilityStatus
    accepted: bool

    def __post_init__(self) -> None:
        if type(self.status) is not TrendSourceCompatibilityStatus:
            raise ValueError("status must be exact compatibility enum")
        if type(self.accepted) is not bool:
            raise ValueError("accepted must be bool")
        if self.accepted != (self.status is TrendSourceCompatibilityStatus.ACCEPTED):
            raise ValueError("compatibility decision is internally inconsistent")


def decide_source_compatibility(
    accepted_versions: tuple[TrendSourceVersion, ...],
    *,
    schema_version: str | None,
    model_version: str,
) -> TrendSourceCompatibilityDecision:
    """Match only an explicitly declared schema/model pair; never infer compatibility."""

    if type(accepted_versions) is not tuple or not accepted_versions:
        raise ValueError("accepted_versions must be a non-empty tuple")
    if any(type(item) is not TrendSourceVersion for item in accepted_versions):
        raise ValueError("accepted_versions must contain exact TrendSourceVersion values")
    _version(schema_version, "schema_version", nullable=True)
    _version(model_version, "model_version")
    candidate = TrendSourceVersion(schema_version, model_version)
    if candidate in accepted_versions:
        return TrendSourceCompatibilityDecision(TrendSourceCompatibilityStatus.ACCEPTED, True)
    if schema_version not in tuple(item.schema_version for item in accepted_versions):
        status = TrendSourceCompatibilityStatus.SCHEMA_VERSION_UNSUPPORTED
    elif model_version not in tuple(item.model_version for item in accepted_versions):
        status = TrendSourceCompatibilityStatus.MODEL_VERSION_UNSUPPORTED
    else:
        status = TrendSourceCompatibilityStatus.VERSION_PAIR_UNSUPPORTED
    return TrendSourceCompatibilityDecision(status, False)
