"""Safe synchronous facade for the Milestone 4.5D pure calculation core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from .analyzer import analyze_indirect_cash_flow
from .calculation import (
    CashFlowCoreDecimalError,
    CashFlowCoreIntegrityError,
    CashFlowCoreMappingVersionError,
    CashFlowCorePolicyError,
)
from .contracts import (
    CashFlowComputationDraft,
    CashFlowEngineOutcome,
    IndirectCashFlowInput,
)
from .errors import CashFlowContractError, CashFlowEngineFailure
from .reconciliation import CashFlowFinalizationIntegrityError, finalize_cash_flow_result
from .types import CashFlowErrorCode
from .types import CashFlowResultStatus


@final
@dataclass(frozen=True, repr=False)
class CashFlowCoreOutcome:
    success: bool
    draft: CashFlowComputationDraft | None
    error: CashFlowEngineFailure | None

    def __post_init__(self) -> None:
        if type(self.success) is not bool:
            raise CashFlowContractError("core outcome success must be bool")
        if self.success:
            if type(self.draft) is not CashFlowComputationDraft or self.error is not None:
                raise CashFlowContractError("successful core outcome invariant failed")
        elif self.draft is not None or type(self.error) is not CashFlowEngineFailure:
            raise CashFlowContractError("failed core outcome invariant failed")

    def __repr__(self) -> str:
        return "CashFlowCoreOutcome()"

    __str__ = __repr__


@final
class IndirectCashFlowCoreService:
    def analyze(self, inputs: object) -> CashFlowCoreOutcome:
        try:
            if type(inputs) is not IndirectCashFlowInput:
                raise CashFlowContractError("indirect cash-flow input is required")
            draft = analyze_indirect_cash_flow(inputs)
            return CashFlowCoreOutcome(True, draft, None)
        except CashFlowCoreDecimalError:
            code = CashFlowErrorCode.DECIMAL_NON_FINITE_OR_SCALE_INVALID
        except CashFlowCorePolicyError:
            code = CashFlowErrorCode.POLICY_VERSION_UNSUPPORTED
        except CashFlowCoreMappingVersionError:
            code = CashFlowErrorCode.MAPPING_REGISTRY_VERSION_UNSUPPORTED
        except CashFlowCoreIntegrityError:
            code = CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT
        except CashFlowContractError:
            code = CashFlowErrorCode.INVALID_CONTRACT
        except Exception:
            code = CashFlowErrorCode.INVALID_CONTRACT
        return CashFlowCoreOutcome(False, None, CashFlowEngineFailure(code))


@final
class CashFlowEngineService:
    """Synchronous pure 4.5E service; it does not persist or integrate engines."""

    def analyze(
        self,
        inputs: object,
        *,
        comparability_proof_digest: str | None,
    ) -> CashFlowEngineOutcome:
        try:
            if type(inputs) is not IndirectCashFlowInput:
                raise CashFlowContractError("indirect cash-flow input is required")
            draft = analyze_indirect_cash_flow(inputs)
            result = finalize_cash_flow_result(
                draft=draft,
                inputs=inputs,
                comparability_proof_digest=comparability_proof_digest,
            )
            return CashFlowEngineOutcome(result.status, True, result, None)
        except CashFlowCoreDecimalError:
            code = CashFlowErrorCode.DECIMAL_NON_FINITE_OR_SCALE_INVALID
            status = CashFlowResultStatus.INVALID_INPUT
        except CashFlowCorePolicyError:
            code = CashFlowErrorCode.POLICY_VERSION_UNSUPPORTED
            status = CashFlowResultStatus.INVALID_INPUT
        except CashFlowCoreMappingVersionError:
            code = CashFlowErrorCode.MAPPING_REGISTRY_VERSION_UNSUPPORTED
            status = CashFlowResultStatus.INVALID_INPUT
        except (CashFlowCoreIntegrityError, CashFlowFinalizationIntegrityError):
            code = CashFlowErrorCode.SOURCE_EVIDENCE_CONFLICT
            status = CashFlowResultStatus.INTEGRITY_FAILURE
        except CashFlowContractError:
            code = CashFlowErrorCode.INVALID_CONTRACT
            status = CashFlowResultStatus.INVALID_INPUT
        except Exception:
            code = CashFlowErrorCode.INVALID_CONTRACT
            status = CashFlowResultStatus.INVALID_INPUT
        return CashFlowEngineOutcome(status, False, None, CashFlowEngineFailure(code))
