from typing import Any


def safe_divide(
    numerator: float,
    denominator: float,
) -> float | None:
    if denominator == 0:
        return None

    return round(numerator / denominator, 4)


def build_ratios(
    financial_statements: dict[str, Any],
) -> dict[str, Any]:
    balance_sheet = financial_statements["balance_sheet"]
    income_statement = financial_statements["income_statement"]

    current_assets = balance_sheet["current_assets"]
    non_current_assets = balance_sheet["non_current_assets"]
    total_assets = balance_sheet["total_assets"]

    short_term_liabilities = balance_sheet[
        "short_term_liabilities"
    ]
    long_term_liabilities = balance_sheet[
        "long_term_liabilities"
    ]
    equity = balance_sheet["equity"]

    total_liabilities = (
        short_term_liabilities
        + long_term_liabilities
    )

    net_sales = income_statement["net_sales"]
    gross_profit = income_statement["gross_profit"]
    operating_profit = income_statement["operating_profit"]
    financing_expenses = income_statement[
        "financing_expenses"
    ]
    profit_before_tax = income_statement[
        "calculated_profit_before_tax"
    ]

    net_working_capital = (
        current_assets
        - short_term_liabilities
    )

    return {
        "liquidity": {
            "current_ratio": safe_divide(
                current_assets,
                short_term_liabilities,
            ),
            "net_working_capital": round(
                net_working_capital,
                2,
            ),
        },
        "leverage": {
            "total_liabilities": round(
                total_liabilities,
                2,
            ),
            "debt_to_equity": safe_divide(
                total_liabilities,
                equity,
            ),
            "debt_ratio": safe_divide(
                total_liabilities,
                total_assets,
            ),
            "equity_ratio": safe_divide(
                equity,
                total_assets,
            ),
            "short_term_debt_ratio": safe_divide(
                short_term_liabilities,
                total_liabilities,
            ),
        },
        "profitability": {
            "gross_profit_margin": safe_divide(
                gross_profit,
                net_sales,
            ),
            "operating_profit_margin": safe_divide(
                operating_profit,
                net_sales,
            ),
            "profit_before_tax_margin": safe_divide(
                profit_before_tax,
                net_sales,
            ),
            "return_on_assets_pretax": safe_divide(
                profit_before_tax,
                total_assets,
            ),
            "return_on_equity_pretax": safe_divide(
                profit_before_tax,
                equity,
            ),
        },
        "coverage": {
            "financing_expense_coverage": safe_divide(
                operating_profit,
                financing_expenses,
            ),
        },
        "data_quality": {
            "balance_sheet_balanced": balance_sheet[
                "balanced"
            ],
            "income_statement_available": (
                net_sales != 0
            ),
        },
    }