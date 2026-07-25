from collections import defaultdict
from decimal import Decimal

from app.trial_balance.models import TrialBalanceAccount
from app.trial_balance.normalizer import decimal_to_float


ZERO = Decimal("0")


BALANCE_SHEET_SECTIONS = {
    "1": "current_assets",
    "2": "non_current_assets",
    "3": "short_term_liabilities",
    "4": "long_term_liabilities",
    "5": "equity",
}


INCOME_STATEMENT_SECTIONS = {
    "60": "gross_sales",
    "61": "sales_deductions",
    "62": "cost_of_sales",
    "63": "operating_expenses",
    "64": "other_operating_income",
    "65": "other_operating_expenses",
    "66": "financing_expenses",
    "67": "extraordinary_income",
    "68": "extraordinary_expenses",
    "69": "period_profit_loss_accounts",
}


def get_numeric_prefix(account_code: str) -> str:
    return "".join(
        character
        for character in account_code
        if character.isdigit()
    )


def asset_amount(account: TrialBalanceAccount) -> Decimal:
    return account.debit - account.credit


def liability_amount(account: TrialBalanceAccount) -> Decimal:
    return account.credit - account.debit


def debit_nature_amount(account: TrialBalanceAccount) -> Decimal:
    return account.debit - account.credit


def credit_nature_amount(account: TrialBalanceAccount) -> Decimal:
    return account.credit - account.debit


def build_balance_sheet(
    accounts: list[TrialBalanceAccount],
) -> dict:
    sections: dict[str, Decimal] = defaultdict(
        lambda: ZERO
    )

    account_details: dict[str, list[dict]] = defaultdict(list)

    for account in accounts:
        if not account.is_leaf:
            continue

        prefix = get_numeric_prefix(
            account.account_code
        )

        if not prefix:
            continue

        account_class = prefix[0]

        section = BALANCE_SHEET_SECTIONS.get(
            account_class
        )

        if not section:
            continue

        if account_class in {"1", "2"}:
            amount = asset_amount(account)
        else:
            amount = liability_amount(account)

        sections[section] += amount

        account_details[section].append(
            {
                "account_code": account.account_code,
                "account_name": account.account_name,
                "amount": decimal_to_float(amount),
            }
        )

    current_assets = sections["current_assets"]
    non_current_assets = sections["non_current_assets"]
    short_term_liabilities = sections[
        "short_term_liabilities"
    ]
    long_term_liabilities = sections[
        "long_term_liabilities"
    ]
    equity = sections["equity"]

    total_assets = (
        current_assets
        + non_current_assets
    )

    total_liabilities_and_equity = (
        short_term_liabilities
        + long_term_liabilities
        + equity
    )

    difference = (
        total_assets
        - total_liabilities_and_equity
    )

    balanced = abs(difference) <= Decimal("0.01")

    return {
        "current_assets": decimal_to_float(
            current_assets
        ),
        "non_current_assets": decimal_to_float(
            non_current_assets
        ),
        "total_assets": decimal_to_float(
            total_assets
        ),
        "short_term_liabilities": decimal_to_float(
            short_term_liabilities
        ),
        "long_term_liabilities": decimal_to_float(
            long_term_liabilities
        ),
        "equity": decimal_to_float(equity),
        "total_liabilities_and_equity": decimal_to_float(
            total_liabilities_and_equity
        ),
        "difference": decimal_to_float(difference),
        "balanced": balanced,
        "account_details": dict(account_details),
    }


def build_income_statement(
    accounts: list[TrialBalanceAccount],
) -> dict:
    sections: dict[str, Decimal] = defaultdict(
        lambda: ZERO
    )

    account_details: dict[str, list[dict]] = defaultdict(list)

    for account in accounts:
        if not account.is_leaf:
            continue

        prefix = get_numeric_prefix(
            account.account_code
        )

        if len(prefix) < 2:
            continue

        group_code = prefix[:2]

        section = INCOME_STATEMENT_SECTIONS.get(
            group_code
        )

        if not section:
            continue

        if group_code in {"60", "64", "67"}:
            amount = credit_nature_amount(account)
        elif group_code == "69":
            amount = account.credit - account.debit
        else:
            amount = debit_nature_amount(account)

        sections[section] += amount

        account_details[section].append(
            {
                "account_code": account.account_code,
                "account_name": account.account_name,
                "amount": decimal_to_float(amount),
            }
        )

    gross_sales = sections["gross_sales"]
    sales_deductions = sections["sales_deductions"]
    cost_of_sales = sections["cost_of_sales"]
    operating_expenses = sections[
        "operating_expenses"
    ]
    other_operating_income = sections[
        "other_operating_income"
    ]
    other_operating_expenses = sections[
        "other_operating_expenses"
    ]
    financing_expenses = sections[
        "financing_expenses"
    ]
    extraordinary_income = sections[
        "extraordinary_income"
    ]
    extraordinary_expenses = sections[
        "extraordinary_expenses"
    ]

    net_sales = (
        gross_sales
        - sales_deductions
    )

    gross_profit = (
        net_sales
        - cost_of_sales
    )

    operating_profit = (
        gross_profit
        - operating_expenses
        + other_operating_income
        - other_operating_expenses
    )

    profit_before_extraordinary_items = (
        operating_profit
        - financing_expenses
    )

    calculated_profit_before_tax = (
        profit_before_extraordinary_items
        + extraordinary_income
        - extraordinary_expenses
    )

    return {
        "gross_sales": decimal_to_float(
            gross_sales
        ),
        "sales_deductions": decimal_to_float(
            sales_deductions
        ),
        "net_sales": decimal_to_float(
            net_sales
        ),
        "cost_of_sales": decimal_to_float(
            cost_of_sales
        ),
        "gross_profit": decimal_to_float(
            gross_profit
        ),
        "operating_expenses": decimal_to_float(
            operating_expenses
        ),
        "other_operating_income": decimal_to_float(
            other_operating_income
        ),
        "other_operating_expenses": decimal_to_float(
            other_operating_expenses
        ),
        "operating_profit": decimal_to_float(
            operating_profit
        ),
        "financing_expenses": decimal_to_float(
            financing_expenses
        ),
        "extraordinary_income": decimal_to_float(
            extraordinary_income
        ),
        "extraordinary_expenses": decimal_to_float(
            extraordinary_expenses
        ),
        "calculated_profit_before_tax": decimal_to_float(
            calculated_profit_before_tax
        ),
        "reported_period_profit_loss": decimal_to_float(
            sections["period_profit_loss_accounts"]
        ),
        "account_details": dict(account_details),
    }


def build_financial_statements(
    accounts: list[TrialBalanceAccount],
) -> dict:
    return {
        "basis": "Turkish Uniform Chart of Accounts",
        "balance_sheet": build_balance_sheet(
            accounts
        ),
        "income_statement": build_income_statement(
            accounts
        ),
    }