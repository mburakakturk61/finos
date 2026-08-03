"""Strict FinancialAnalysisResult codec for CashFlowResult V3 owners."""

from __future__ import annotations

from dataclasses import fields
from datetime import date
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import hmac
import json
from uuid import UUID

from app.engines.cash_flow import contracts as cf_contracts
from app.engines.cash_flow.contracts import CashFlowResult, canonical_cash_flow_bytes
from app.models.enums import AnalysisStatus, SourceMode
from app.orchestration_persistence.codec import canonical_json_bytes

CASH_FLOW_FINANCIAL_RESULT_CODEC_VERSION = "1.0.0"

_RECORD_BY_TAG = {tag: cls for cls, tag in cf_contracts._LOGICAL_TAGS.items()}
_ENUM_BY_TAG = {tag: cls for cls, tag in cf_contracts._ENUM_LOGICAL_TAGS.items()}

_MONEY_FIELDS_BY_TAG = {
    "cf.activity_allocation.v1": ("amount",),
    "cf.line_item.v1": ("canonical_amount",),
    "cf.cash_availability_observation.v1": ("amount",),
    "cf.endpoint_reconciliation.v1": (
        "policy_defined_cash_and_cash_equivalents",
        "reported_balance_sheet_cash_and_cash_equivalents",
        "difference",
    ),
    "cf.reconciliation.v1": (
        "balance_sheet_net_cash_change",
        "calculated_net_cash_change",
        "difference",
        "rounding_tolerance",
        "material_threshold",
    ),
    "cf.result.v1": (
        "opening_cash_and_cash_equivalents",
        "closing_cash_and_cash_equivalents",
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "authoritative_fx_effect",
        "authoritative_reclassification_effect",
        "calculated_net_cash_change",
        "balance_sheet_net_cash_change",
        "reconciliation_difference",
        "free_cash_flow",
    ),
}


class CashFlowFinancialResultCodecError(ValueError):
    pass


def encode_cash_flow_financial_result(result: CashFlowResult) -> tuple[dict, str]:
    if type(result) is not CashFlowResult:
        raise CashFlowFinancialResultCodecError("strict codec requires exact CashFlowResult")
    raw = canonical_cash_flow_bytes(result)
    node = json.loads(raw.decode("utf-8"))
    return node, sha256(raw).hexdigest()


def cash_flow_owner_content_digest(result: CashFlowResult) -> str:
    """Bind the strict payload to the frozen five-field owner semantics."""

    node, _canonical_result_digest = encode_cash_flow_financial_result(result)
    projection = {
        "status": AnalysisStatus.COMPLETED,
        "source_mode": SourceMode.MULTI_SOURCE_DERIVED,
        "result_json": node,
        "error_message": None,
        "trial_balance_usage": None,
    }
    return sha256(canonical_json_bytes(projection)).hexdigest()


def decode_cash_flow_financial_result(node: dict, expected_digest: str) -> CashFlowResult:
    if type(node) is not dict:
        raise CashFlowFinancialResultCodecError("strict Cash Flow JSONB root must be an object")
    if type(expected_digest) is not str or len(expected_digest) != 64:
        raise CashFlowFinancialResultCodecError("invalid expected Cash Flow digest")
    value = _decode(node)
    if type(value) is not CashFlowResult:
        raise CashFlowFinancialResultCodecError("strict Cash Flow root tag mismatch")
    raw = canonical_cash_flow_bytes(value)
    if not hmac.compare_digest(sha256(raw).hexdigest(), expected_digest):
        raise CashFlowFinancialResultCodecError("Cash Flow canonical digest mismatch")
    canonical_node = json.loads(raw.decode("utf-8"))
    if canonical_node != node:
        raise CashFlowFinancialResultCodecError("Cash Flow JSONB node is non-canonical")
    return value


def _exact(node: dict, keys: set[str]) -> None:
    if set(node) != keys:
        raise CashFlowFinancialResultCodecError("strict codec field set mismatch")


def _decode(node):
    if node is None or type(node) in {bool, str, int}:
        return node
    if type(node) is list or type(node) is float:
        raise CashFlowFinancialResultCodecError("mutable/float node is forbidden")
    if type(node) is not dict or type(node.get("$type")) is not str:
        raise CashFlowFinancialResultCodecError("unknown strict codec node")
    kind = node["$type"]
    if kind == "decimal":
        _exact(node, {"$type", "value"})
        try:
            value = Decimal(node["value"])
        except Exception:
            raise CashFlowFinancialResultCodecError("invalid Decimal node") from None
        if not value.is_finite():
            raise CashFlowFinancialResultCodecError("non-finite Decimal node")
        return value
    if kind == "uuid":
        _exact(node, {"$type", "value"})
        try:
            value = UUID(node["value"])
        except Exception:
            raise CashFlowFinancialResultCodecError("invalid UUID node") from None
        if str(value) != node["value"]:
            raise CashFlowFinancialResultCodecError("non-canonical UUID node")
        return value
    if kind == "date":
        _exact(node, {"$type", "value"})
        try:
            value = date.fromisoformat(node["value"])
        except Exception:
            raise CashFlowFinancialResultCodecError("invalid date node") from None
        if value.isoformat() != node["value"]:
            raise CashFlowFinancialResultCodecError("non-canonical date node")
        return value
    if kind == "enum":
        _exact(node, {"$type", "name", "value"})
        enum_type = _ENUM_BY_TAG.get(node["name"])
        if enum_type is None:
            raise CashFlowFinancialResultCodecError("unknown enum tag")
        try:
            return enum_type(node["value"])
        except ValueError:
            raise CashFlowFinancialResultCodecError("unknown enum value") from None
    if kind == "tuple":
        _exact(node, {"$type", "items"})
        if type(node["items"]) is not list:
            raise CashFlowFinancialResultCodecError("tuple node items must be JSON array")
        return tuple(_decode(item) for item in node["items"])
    if kind == "object":
        _exact(node, {"$type", "items"})
        if type(node["items"]) is not list:
            raise CashFlowFinancialResultCodecError("object node items must be JSON array")
        items = []
        for item in node["items"]:
            if type(item) is not list or len(item) != 2 or type(item[0]) is not str:
                raise CashFlowFinancialResultCodecError("invalid object entry")
            items.append((item[0], _decode(item[1])))
        return cf_contracts.CashFlowJsonObject(tuple(items))
    if kind == "record":
        _exact(node, {"$type", "name", "fields"})
        record_type = _RECORD_BY_TAG.get(node["name"])
        if record_type is None or type(node["fields"]) is not list:
            raise CashFlowFinancialResultCodecError("unknown record tag")
        expected = tuple(item.name for item in fields(record_type))
        actual = tuple(item[0] for item in node["fields"] if type(item) is list and len(item) == 2)
        if actual != expected or len(actual) != len(node["fields"]):
            raise CashFlowFinancialResultCodecError("record field order mismatch")
        try:
            values = {
                name: _decode(item[1]) for name, item in zip(expected, node["fields"])
            }
            # The v1 canonical byte domain normalizes Decimal text.  Restore
            # the one contract field whose scale is itself an invariant.
            if node["name"] == "cf.completeness.v1" and type(values.get("available_ratio")) is Decimal:
                values["available_ratio"] = values["available_ratio"].quantize(Decimal("0.0001"))
            for name in _MONEY_FIELDS_BY_TAG.get(node["name"], ()):
                if type(values.get(name)) is Decimal:
                    values[name] = values[name].quantize(Decimal("0.01"))
            return record_type(**values)
        except Exception as error:
            raise CashFlowFinancialResultCodecError(
                f"record invariant failure: {node['name']}"
            ) from error
    raise CashFlowFinancialResultCodecError("unknown strict codec tag")
