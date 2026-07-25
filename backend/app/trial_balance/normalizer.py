from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd


ZERO = Decimal("0")


def normalize_account_code(value: Any) -> str:
    if pd.isna(value):
        return ""

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value).strip()


def parse_decimal(value: Any) -> Decimal:
    if value is None or pd.isna(value):
        return ZERO

    if isinstance(value, Decimal):
        return value

    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip()
    text = text.replace("₺", "")
    text = text.replace("TL", "")
    text = text.replace(" ", "")

    if not text or text in {"-", "—"}:
        return ZERO

    negative = False

    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        number = Decimal(text)
    except InvalidOperation:
        return ZERO

    return -number if negative else number


def decimal_to_float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))
