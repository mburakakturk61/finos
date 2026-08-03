"""Repository trial-balance fixture regression for Milestone 4.5B."""

from pathlib import Path

import pandas as pd
import pytest

from app.engines.cash_flow import (
    CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1,
    CashFlowAccountRole,
)


FIXTURE_DIR = Path(__file__).parent / "data" / "synthetic"


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    (
        (
            "synthetic_trial_balance.xlsx",
            {
                "100": CashFlowAccountRole.CASH_ON_HAND,
                "120": CashFlowAccountRole.OPERATING_RECEIVABLE,
                "320": CashFlowAccountRole.OPERATING_PAYABLE,
                "500": CashFlowAccountRole.EQUITY,
            },
        ),
        (
            "synthetic_trial_balance_matched_bs_is.xlsx",
            {
                "100": CashFlowAccountRole.CASH_ON_HAND,
                "252": CashFlowAccountRole.PPE,
                "320": CashFlowAccountRole.OPERATING_PAYABLE,
                "400": CashFlowAccountRole.BORROWING,
                "500": CashFlowAccountRole.EQUITY,
                "600": CashFlowAccountRole.UNCLASSIFIED,
                "611": CashFlowAccountRole.UNCLASSIFIED,
                "620": CashFlowAccountRole.UNCLASSIFIED,
                "630": CashFlowAccountRole.UNCLASSIFIED,
                "640": CashFlowAccountRole.DIVIDEND_INCOME_ACCRUAL,
                "653": CashFlowAccountRole.UNCLASSIFIED,
                "900": CashFlowAccountRole.UNCLASSIFIED,
            },
        ),
    ),
)
def test_repository_trial_balance_fixture_classification(fixture_name, expected):
    frame = pd.read_excel(FIXTURE_DIR / fixture_name, engine="openpyxl")
    observed = {
        str(code): CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.resolve(str(code)).resolved_account_role
        for code in frame["Hesap Kodu"]
    }
    assert observed == expected


def test_fixture_account_names_cannot_change_authoritative_mapping():
    frame = pd.read_excel(
        FIXTURE_DIR / "synthetic_trial_balance_matched_bs_is.xlsx",
        engine="openpyxl",
    )
    original = tuple(
        CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.resolve(str(code))
        for code in frame["Hesap Kodu"]
    )
    frame["Hesap Adi"] = tuple(
        "KASA" if index % 2 else "BANKALAR"
        for index in range(len(frame))
    )
    renamed = tuple(
        CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.resolve(str(code))
        for code in frame["Hesap Kodu"]
    )
    assert renamed == original


@pytest.mark.parametrize(
    ("code", "expected_role"),
    (
        ("101", CashFlowAccountRole.CHECK_RECEIVABLE),
        ("102.01", CashFlowAccountRole.BANK_ACCOUNT_CANDIDATE),
        ("108.05", CashFlowAccountRole.OTHER_LIQUID_ASSET_CANDIDATE),
        ("121", CashFlowAccountRole.OPERATING_RECEIVABLE),
        ("150", CashFlowAccountRole.INVENTORY),
        ("180", CashFlowAccountRole.OTHER_OPERATING_ASSET),
        ("280", CashFlowAccountRole.UNCLASSIFIED),
        ("321", CashFlowAccountRole.OPERATING_PAYABLE),
        ("335", CashFlowAccountRole.UNCLASSIFIED),
        ("360", CashFlowAccountRole.UNCLASSIFIED),
        ("361", CashFlowAccountRole.OTHER_OPERATING_LIABILITY),
        ("381", CashFlowAccountRole.UNCLASSIFIED),
        ("481", CashFlowAccountRole.UNCLASSIFIED),
        ("250", CashFlowAccountRole.PPE),
        ("251", CashFlowAccountRole.PPE),
        ("252", CashFlowAccountRole.PPE),
        ("257", CashFlowAccountRole.NON_CASH_ADJUSTMENT),
        ("260", CashFlowAccountRole.INTANGIBLE_ASSET),
        ("268", CashFlowAccountRole.NON_CASH_ADJUSTMENT),
        ("300", CashFlowAccountRole.BORROWING),
        ("400", CashFlowAccountRole.BORROWING),
        ("500", CashFlowAccountRole.EQUITY),
        ("570", CashFlowAccountRole.NON_CASH_EQUITY),
        ("999.99", CashFlowAccountRole.UNCLASSIFIED),
    ),
)
def test_design_manifest_account_family_regression(code, expected_role):
    assert CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.resolve(code).resolved_account_role is expected_role


def test_fixture_registry_stage_has_no_balance_period_or_cash_flow_calculation():
    result = CASH_FLOW_ACCOUNT_MAPPING_REGISTRY_V1.resolve("100")
    prohibited = {"amount", "balance", "movement", "period", "cash_flow_amount"}
    assert prohibited.isdisjoint(result.__dataclass_fields__)

