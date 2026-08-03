"""Version-isolated deterministic V3 request and engine fingerprints."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from uuid import UUID

from app.engines.cash_flow.contracts import CashFlowPreResolvedContext, canonical_cash_flow_digest
from app.engines.analysis_orchestrator.fingerprint import (
    canonical_hash as legacy_canonical_hash,
    compute_engine_input_fingerprint as legacy_engine_fingerprint,
)
from app.engines.analysis_orchestrator.types import (
    EngineCode as LegacyEngineCode,
    EngineRawInputs as LegacyEngineRawInputs,
    OrchestrationRunOptions as LegacyRunOptions,
)

from .types import (
    EngineRawInputsV3,
    OrchestrationEngineCodeV3,
    OrchestrationJsonObjectV3,
    OrchestrationRunOptionsV3,
    OrchestrationRunRequestV3,
)


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("non-finite Decimal")
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _node(value: object, *, engine_container: bool = False) -> object:
    if value is None or type(value) in {bool, str, int}:
        return value
    if type(value) is bytes:
        return {"$type": "bytes_sha256", "value": sha256(value).hexdigest()}
    if type(value) is Decimal:
        return {"$type": "decimal", "value": _decimal_text(value)}
    if type(value) is UUID:
        return {"$type": "uuid", "value": str(value)}
    if type(value) is date:
        return {"$type": "date", "value": value.isoformat()}
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetime is not canonical")
        return {"$type": "datetime", "value": value.isoformat()}
    if isinstance(value, Enum):
        return {"$type": "enum", "value": value.value}
    if type(value) is tuple:
        return {"$type": "tuple", "items": [_node(item, engine_container=engine_container) for item in value]}
    if engine_container and type(value) is list:
        return {"$type": "engine_list", "items": [_node(item, engine_container=True) for item in value]}
    if engine_container and type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError("engine result mappings require string keys")
        return {
            "$type": "engine_mapping",
            "items": [[key, _node(value[key], engine_container=True)] for key in sorted(value)],
        }
    if type(value) is OrchestrationJsonObjectV3:
        return {"$type": "object", "items": [[key, _node(item)] for key, item in value.items]}
    if type(value) is CashFlowPreResolvedContext:
        return {"$type": "cash_flow_context_digest", "value": canonical_cash_flow_digest(value)}
    if is_dataclass(value) and type(value) in {EngineRawInputsV3, OrchestrationRunOptionsV3}:
        return {
            "$type": type(value).__name__,
            "fields": [[field.name, _node(getattr(value, field.name))] for field in fields(value)],
        }
    if is_dataclass(value) and type(value).__module__.startswith("app.engines."):
        return {
            "$type": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": [
                [field.name, _node(getattr(value, field.name), engine_container=True)]
                for field in fields(value)
            ],
        }
    raise TypeError(f"unsupported V3 fingerprint value: {type(value).__name__}")


def _bytes(value: object) -> bytes:
    return json.dumps(_node(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _plain(value: OrchestrationJsonObjectV3 | None):
    if value is None:
        return None
    return {key: (_plain(item) if type(item) is OrchestrationJsonObjectV3 else item) for key, item in value.items}


def _legacy_inputs(value: EngineRawInputsV3) -> LegacyEngineRawInputs:
    return LegacyEngineRawInputs(
        balance_sheet_content=value.balance_sheet_content,
        balance_sheet_filename=value.balance_sheet_filename,
        income_statement_content=value.income_statement_content,
        income_statement_filename=value.income_statement_filename,
        trial_balance_result=_plain(value.trial_balance_result),
        prior_period_balance_sheet_facts=value.prior_period_balance_sheet_facts,
        prior_period_income_statement_facts=value.prior_period_income_statement_facts,
        prior_period_balance_sheet_result=_plain(value.prior_period_balance_sheet_result),
        prior_period_income_statement_result=_plain(value.prior_period_income_statement_result),
        period_start_date=value.period_start_date,
        period_end_date=value.period_end_date,
        period_months_covered=value.period_months_covered,
    )


def _legacy_options(value: OrchestrationRunOptionsV3) -> LegacyRunOptions:
    return LegacyRunOptions(**{field.name: getattr(value, field.name) for field in fields(LegacyRunOptions)})


def compute_request_fingerprint_v3(request: OrchestrationRunRequestV3) -> str:
    if type(request) is not OrchestrationRunRequestV3:
        raise TypeError("V3 fingerprint requires exact V3 request")
    order = tuple(OrchestrationEngineCodeV3)
    requested = tuple(sorted(request.requested_outputs, key=order.index))
    if OrchestrationEngineCodeV3.CASH_FLOW not in requested:
        return legacy_canonical_hash({
            "requested_outputs": tuple(LegacyEngineCode(item.value) for item in requested),
            "engine_inputs": _legacy_inputs(request.engine_inputs),
            "run_options": _legacy_options(request.run_options),
        })
    engine_digest = sha256(b"orchestration/engine-inputs/v3\0" + _bytes(request.engine_inputs)).hexdigest()
    options_digest = sha256(b"orchestration/run-options/v3\0" + _bytes(request.run_options)).hexdigest()
    projection = OrchestrationJsonObjectV3((
        ("contract_version", request.contract_version),
        ("engine_inputs_v3_digest", engine_digest),
        ("requested_outputs", tuple(item.value for item in requested)),
        ("run_options_v3_digest", options_digest),
    ))
    return sha256(b"orchestration/request-fingerprint/v3\0" + _bytes(projection)).hexdigest()


def compute_engine_input_fingerprint_v3(
    engine_code: OrchestrationEngineCodeV3,
    request: OrchestrationRunRequestV3,
    upstream_fingerprints: dict[OrchestrationEngineCodeV3, str],
) -> str:
    cash_requested = OrchestrationEngineCodeV3.CASH_FLOW in request.requested_outputs
    if engine_code is OrchestrationEngineCodeV3.CASH_FLOW:
        context = request.engine_inputs.cash_flow_pre_resolved_context
        projection = OrchestrationJsonObjectV3((
            ("cash_flow_contract_version", "1.0.0"),
            ("pre_resolved_context_digest", canonical_cash_flow_digest(context)),
            ("upstream_balance_sheet", upstream_fingerprints.get(OrchestrationEngineCodeV3.FS_BALANCE_SHEET)),
            ("upstream_income_statement", upstream_fingerprints.get(OrchestrationEngineCodeV3.FS_INCOME_STATEMENT)),
        ))
        return sha256(b"orchestration/cash-flow-input/v3\0" + _bytes(projection)).hexdigest()
    legacy_code = LegacyEngineCode(engine_code.value)
    legacy_upstream = {
        LegacyEngineCode(code.value): digest
        for code, digest in upstream_fingerprints.items()
        if code is not OrchestrationEngineCodeV3.CASH_FLOW
    }
    base = legacy_engine_fingerprint(
        legacy_code,
        raw_inputs=_legacy_inputs(request.engine_inputs),
        run_options=_legacy_options(request.run_options),
        upstream_fingerprints=legacy_upstream,
    )
    if not cash_requested or engine_code not in {
        OrchestrationEngineCodeV3.RATIO,
        OrchestrationEngineCodeV3.EXECUTIVE_REPORT,
    }:
        return base
    cash_digest = upstream_fingerprints.get(OrchestrationEngineCodeV3.CASH_FLOW)
    state = (
        "result", cash_digest
    ) if cash_digest is not None else (
        "no_result",
        compute_engine_input_fingerprint_v3(
            OrchestrationEngineCodeV3.CASH_FLOW, request, upstream_fingerprints,
        ),
    )
    return legacy_canonical_hash({"legacy_fingerprint": base, "cash_flow_state": state})


def canonical_v3_hash(value: object) -> str:
    return sha256(b"orchestration/value/v3\0" + _bytes(value)).hexdigest()
