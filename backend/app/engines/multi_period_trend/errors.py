"""Safe, immutable failure values for Milestone 4.6A."""

from __future__ import annotations

from typing import Final, final

from .contracts import TrendContractError
from .types import TrendComputationStatus, TrendErrorCode


TREND_ERROR_SAFE_MESSAGE_V1: Final = {
    TrendErrorCode.INVALID_CONTRACT: "Trend input contract is invalid.",
    TrendErrorCode.INVALID_PERIOD_SET: "Trend period set is invalid.",
    TrendErrorCode.PERIOD_OVERLAP: "Trend periods overlap.",
    TrendErrorCode.DUPLICATE_OBSERVATION: "Trend observations contain a duplicate.",
    TrendErrorCode.MIXED_COMPANY: "Trend observations do not share one company scope.",
    TrendErrorCode.MIXED_CURRENCY: "Trend observations do not share one currency.",
    TrendErrorCode.MIXED_MEASUREMENT_BASIS: "Trend observations do not share one measurement basis.",
    TrendErrorCode.SOURCE_NOT_FOUND: "A verified trend source was not found.",
    TrendErrorCode.SOURCE_SCOPE_MISMATCH: "A trend source does not match the requested scope.",
    TrendErrorCode.SOURCE_STATUS_INVALID: "A trend source is not in a usable state.",
    TrendErrorCode.SOURCE_VERSION_UNSUPPORTED: "A trend source version is unsupported.",
    TrendErrorCode.SOURCE_DIGEST_MISMATCH: "A trend source failed integrity verification.",
    TrendErrorCode.PERIOD_NOT_COMPARABLE: "Trend periods are not comparable.",
    TrendErrorCode.POLICY_VERSION_UNSUPPORTED: "The trend policy version is unsupported.",
    TrendErrorCode.DECIMAL_NON_FINITE_OR_SCALE_INVALID: "A trend numeric value is invalid.",
    TrendErrorCode.CANONICAL_REFERENCE_INVALID: "A trend canonical reference is invalid.",
    TrendErrorCode.CONTRACT_INTEGRITY_FAILURE: "Trend contract integrity verification failed.",
}

TREND_RETRYABLE_ERROR_CODES_V1: Final = frozenset()
TREND_INVALID_INPUT_ERROR_CODES_V1: Final = frozenset(
    {
        TrendErrorCode.INVALID_CONTRACT,
        TrendErrorCode.INVALID_PERIOD_SET,
        TrendErrorCode.PERIOD_OVERLAP,
        TrendErrorCode.DUPLICATE_OBSERVATION,
        TrendErrorCode.MIXED_COMPANY,
        TrendErrorCode.MIXED_CURRENCY,
        TrendErrorCode.MIXED_MEASUREMENT_BASIS,
        TrendErrorCode.PERIOD_NOT_COMPARABLE,
        TrendErrorCode.POLICY_VERSION_UNSUPPORTED,
        TrendErrorCode.DECIMAL_NON_FINITE_OR_SCALE_INVALID,
        TrendErrorCode.CANONICAL_REFERENCE_INVALID,
    }
)
TREND_INTEGRITY_ERROR_CODES_V1: Final = frozenset(TrendErrorCode).difference(
    TREND_INVALID_INPUT_ERROR_CODES_V1
)


@final
class TrendEngineFailure:
    """Closed failure value that cannot retain an exception cause or payload."""

    __slots__ = ("_code", "_sealed")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("TrendEngineFailure is final")

    def __init__(self, code: TrendErrorCode) -> None:
        if type(code) is not TrendErrorCode:
            raise TrendContractError("invalid trend error code")
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("TrendEngineFailure is immutable")
        object.__setattr__(self, name, value)

    @property
    def code(self) -> TrendErrorCode:
        return self._code

    @property
    def safe_message(self) -> str:
        return TREND_ERROR_SAFE_MESSAGE_V1[self._code]

    @property
    def retryable(self) -> bool:
        return self._code in TREND_RETRYABLE_ERROR_CODES_V1

    @property
    def args(self) -> tuple[()]:
        return ()

    def __str__(self) -> str:
        return f"TrendEngineFailure(code={self._code.value})"

    __repr__ = __str__


@final
class TrendResultAssemblyError(RuntimeError):
    """Terminal safe failure for invalid or integrity-broken final assembly."""

    __slots__ = ("_status", "_sealed")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("TrendResultAssemblyError is final")

    def __init__(self, status: TrendComputationStatus) -> None:
        if status not in {
            TrendComputationStatus.INVALID_INPUT,
            TrendComputationStatus.INTEGRITY_FAILURE,
        } or type(status) is not TrendComputationStatus:
            raise TypeError("assembly error requires a failure status")
        RuntimeError.__init__(self)
        object.__setattr__(self, "_status", status)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False) and name != "__traceback__":
            raise AttributeError("TrendResultAssemblyError is immutable")
        object.__setattr__(self, name, value)

    def __getattribute__(self, name: str) -> object:
        if name in {"__cause__", "__context__"}:
            return None
        return object.__getattribute__(self, name)

    @property
    def status(self) -> TrendComputationStatus:
        return self._status

    @property
    def args(self) -> tuple[()]:
        return ()

    def __str__(self) -> str:
        return f"TrendResultAssemblyError(status={self._status.value})"

    __repr__ = __str__
