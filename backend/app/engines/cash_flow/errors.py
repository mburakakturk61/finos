"""Safe, immutable errors for the Milestone 4.5A cash-flow contracts."""

from __future__ import annotations

from typing import Final, final

from .types import CashFlowErrorCode, CashFlowJsonObject


class CashFlowContractError(ValueError):
    """Programmer-facing invariant violation with a non-sensitive message."""

    __slots__ = ()


CASH_FLOW_ERROR_SAFE_MESSAGE_V1: Final = {
    CashFlowErrorCode.INVALID_CONTRACT: "Nakit akışı girdi sözleşmesi geçersiz.",
    CashFlowErrorCode.PERIOD_NOT_COMPARABLE: "Dönemler karşılaştırılabilir değil.",
    CashFlowErrorCode.PERIOD_SELECTION_AMBIGUOUS: "Karşılaştırma dönemi tekil olarak seçilemedi.",
    CashFlowErrorCode.SOURCE_NOT_FOUND: "Doğrulanmış finansal kaynak bulunamadı.",
    CashFlowErrorCode.SOURCE_SCOPE_MISMATCH: "Finansal kaynak kapsamla eşleşmiyor.",
    CashFlowErrorCode.SOURCE_STATUS_INVALID: "Finansal kaynak kullanılabilir durumda değil.",
    CashFlowErrorCode.SOURCE_DIGEST_MISMATCH: "Finansal kaynak bütünlük doğrulamasını geçemedi.",
    CashFlowErrorCode.SOURCE_CURRENCY_MISMATCH: "Parasal kaynak normalizasyonu doğrulanamadı.",
    CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT: "Finansal kaynak kanıtları birbiriyle çelişiyor.",
    CashFlowErrorCode.POLICY_VERSION_UNSUPPORTED: "Nakit akışı politika sürümü desteklenmiyor.",
    CashFlowErrorCode.MAPPING_REGISTRY_VERSION_UNSUPPORTED: "Hesap eşleştirme sürümü desteklenmiyor.",
    CashFlowErrorCode.MAPPING_CONFLICT: "Hesap eşleştirme kuralları çakışıyor.",
    CashFlowErrorCode.DECIMAL_NON_FINITE_OR_SCALE_INVALID: "Parasal değer biçimi desteklenmiyor.",
    CashFlowErrorCode.PERSISTENCE_INTEGRITY_FAILURE: "Nakit akışı kalıcılık bütünlüğü doğrulanamadı.",
    CashFlowErrorCode.SOURCE_RESOLUTION_UNAVAILABLE: "Finansal kaynak çözümleme servisi kullanılamıyor.",
    CashFlowErrorCode.PERSISTENCE_UNAVAILABLE: "Nakit akışı kalıcılık servisi kullanılamıyor.",
}
CASH_FLOW_RETRYABLE_ERROR_CODES_V1: Final = frozenset(
    {
        CashFlowErrorCode.SOURCE_RESOLUTION_UNAVAILABLE,
        CashFlowErrorCode.PERSISTENCE_UNAVAILABLE,
    }
)
CASH_FLOW_INVALID_INPUT_ERROR_CODES_V1: Final = frozenset(
    {
        CashFlowErrorCode.INVALID_CONTRACT,
        CashFlowErrorCode.PERIOD_NOT_COMPARABLE,
        CashFlowErrorCode.PERIOD_SELECTION_AMBIGUOUS,
        CashFlowErrorCode.POLICY_VERSION_UNSUPPORTED,
        CashFlowErrorCode.MAPPING_REGISTRY_VERSION_UNSUPPORTED,
        CashFlowErrorCode.DECIMAL_NON_FINITE_OR_SCALE_INVALID,
    }
)
CASH_FLOW_INTEGRITY_ERROR_CODES_V1: Final = frozenset(CashFlowErrorCode).difference(
    CASH_FLOW_INVALID_INPUT_ERROR_CODES_V1
)


@final
class CashFlowEngineFailure:
    """Closed public failure value; it intentionally cannot retain a cause."""

    __slots__ = ("_code", "_sealed")

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError("CashFlowEngineFailure is final")

    def __init__(self, code: CashFlowErrorCode) -> None:
        if type(code) is not CashFlowErrorCode:
            raise CashFlowContractError("invalid cash-flow error code")
        object.__setattr__(self, "_code", code)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("CashFlowEngineFailure is immutable")
        object.__setattr__(self, name, value)

    @property
    def code(self) -> CashFlowErrorCode:
        return self._code

    @property
    def safe_message(self) -> str:
        return CASH_FLOW_ERROR_SAFE_MESSAGE_V1[self._code]

    @property
    def safe_metadata(self) -> CashFlowJsonObject:
        return CashFlowJsonObject(items=())

    @property
    def retryable(self) -> bool:
        return self._code in CASH_FLOW_RETRYABLE_ERROR_CODES_V1

    def __str__(self) -> str:
        return f"CashFlowEngineFailure(code={self._code.value})"

    def __repr__(self) -> str:
        return str(self)
