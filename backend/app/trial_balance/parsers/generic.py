import re
from typing import Any

import pandas as pd

from app.trial_balance.normalizer import (
    normalize_account_code,
    parse_decimal,
)
from app.trial_balance.structure_detector import is_total_row


def is_valid_account_code(account_code: str) -> bool:
    """
    Hesap kodunun gerçekten muhasebe hesabı olup olmadığını kontrol eder.
    '.', '-', '/' gibi bozuk satırları reddeder.
    """

    if not account_code:
        return False

    return bool(
        re.search(
            r"[A-Za-z0-9ÇĞİÖŞÜçğıöşü]",
            account_code,
        )
    )


def parse_generic_rows(
    dataframe: pd.DataFrame,
    detected_columns: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:

    rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []

    account_code_column = detected_columns["account_code"]
    account_name_column = detected_columns["account_name"]
    debit_column = detected_columns["debit"]
    credit_column = detected_columns["credit"]

    for row_number, (_, row) in enumerate(
        dataframe.iterrows(),
        start=2,
    ):

        account_code = normalize_account_code(
            row.get(account_code_column)
        )

        account_name_value = row.get(account_name_column)

        account_name = (
            ""
            if pd.isna(account_name_value)
            else str(account_name_value).strip()
        )

        debit = parse_decimal(
            row.get(debit_column)
        )

        credit = parse_decimal(
            row.get(credit_column)
        )

        # tamamen boş satırlar
        if not account_code and not account_name:
            continue

        # TOPLAM satırları
        if is_total_row(
            account_code,
            account_name,
        ):
            continue

        # geçersiz hesap kodu
        if not is_valid_account_code(account_code):

            rejected_rows.append(
                {
                    "row_number": row_number,
                    "account_code": account_code,
                    "account_name": account_name,
                    "debit": debit,
                    "credit": credit,
                    "reason": "Geçersiz hesap kodu",
                }
            )

            continue

        rows.append(
            {
                "row_number": row_number,
                "account_code": account_code,
                "account_name": account_name,
                "debit": debit,
                "credit": credit,
            }
        )

    return rows, rejected_rows