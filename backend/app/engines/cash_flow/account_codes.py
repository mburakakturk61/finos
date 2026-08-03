"""Closed account-code grammar for the Milestone 4.5B registry."""

from __future__ import annotations

import re

from .errors import CashFlowContractError


_RAW_ACCOUNT_CODE_RE = re.compile(r"^[0-9]+(?:[.\-/ ][0-9]+)*$", re.ASCII)
_CANONICAL_ACCOUNT_CODE_RE = re.compile(r"^[0-9]{1,64}$", re.ASCII)
_SEPARATORS = str.maketrans("", "", ".-/ ")


def normalize_account_code(raw_account_code: str) -> str:
    """Return the explicit canonical form or fail without trimming/fuzzing."""

    if type(raw_account_code) is not str:
        raise CashFlowContractError("account code must be a string")
    if not 1 <= len(raw_account_code) <= 64:
        raise CashFlowContractError("account code length is outside the closed grammar")
    if not raw_account_code.isascii() or _RAW_ACCOUNT_CODE_RE.fullmatch(raw_account_code) is None:
        raise CashFlowContractError("account code does not match the closed ASCII grammar")
    canonical = raw_account_code.translate(_SEPARATORS)
    if _CANONICAL_ACCOUNT_CODE_RE.fullmatch(canonical) is None:
        raise CashFlowContractError("canonical account code is invalid")
    return canonical


def require_canonical_account_pattern(pattern: str) -> str:
    if type(pattern) is not str or _CANONICAL_ACCOUNT_CODE_RE.fullmatch(pattern) is None:
        raise CashFlowContractError("registry account pattern must be canonical ASCII digits")
    return pattern

