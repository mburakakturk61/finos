from decimal import Decimal
from io import BytesIO

import pandas as pd

from app.trial_balance.account_tree import build_account_tree
from app.trial_balance.column_detector import detect_columns
from app.trial_balance.financial_statements import (
    build_financial_statements,
)
from app.trial_balance.insights import build_insights
from app.trial_balance.normalizer import decimal_to_float
from app.trial_balance.parsers.generic import parse_generic_rows
from app.trial_balance.ratios import build_ratios
from app.trial_balance.structure_detector import (
    detect_account_structure,
)
from app.trial_balance.validator import validate_balance


REQUIRED_COLUMNS = {
    "account_code",
    "account_name",
    "debit",
    "credit",
}


def serialize_rejected_rows(
    rejected_rows: list[dict],
    limit: int = 20,
) -> list[dict]:
    return [
        {
            "row_number": row["row_number"],
            "account_code": row["account_code"],
            "account_name": row["account_name"],
            "debit": decimal_to_float(row["debit"]),
            "credit": decimal_to_float(row["credit"]),
            "reason": row["reason"],
        }
        for row in rejected_rows[:limit]
    ]


def analyze_trial_balance(
    content: bytes,
    filename: str,
) -> dict:
    dataframe = pd.read_excel(
        BytesIO(content),
        engine="openpyxl",
    )

    if dataframe.empty:
        raise ValueError(
            "Excel dosyasında veri bulunamadı."
        )

    detected_columns = detect_columns(
        list(dataframe.columns)
    )

    missing_columns = sorted(
        REQUIRED_COLUMNS - set(detected_columns)
    )

    if missing_columns:
        return {
            "status": "INVALID",
            "filename": filename,
            "vendor": "unknown",
            "parser": "generic",
            "format": "unknown",
            "source_row_count": len(dataframe),
            "row_count": 0,
            "rejected_row_count": 0,
            "calculation_row_count": 0,
            "detected_columns": detected_columns,
            "missing_columns": missing_columns,
            "errors": [
                "Zorunlu kolonlardan bazıları bulunamadı."
            ],
            "warnings": [],
            "rejected_rows": [],
        }

    rows, rejected_rows = parse_generic_rows(
        dataframe=dataframe,
        detected_columns=detected_columns,
    )

    if not rows:
        return {
            "status": "INVALID",
            "filename": filename,
            "vendor": "unknown",
            "parser": "generic",
            "format": "unknown",
            "source_row_count": len(dataframe),
            "row_count": 0,
            "rejected_row_count": len(rejected_rows),
            "calculation_row_count": 0,
            "detected_columns": detected_columns,
            "errors": [
                "Geçerli muhasebe hesabı bulunamadı."
            ],
            "warnings": [],
            "rejected_rows": serialize_rejected_rows(
                rejected_rows
            ),
        }

    structure = detect_account_structure(
        [
            row["account_code"]
            for row in rows
        ]
    )

    accounts = build_account_tree(
        rows=rows,
        parent_codes=structure["parent_codes"],
        leaf_codes=structure["leaf_codes"],
    )

    if structure["hierarchical"]:
        calculation_rows = [
            row
            for row in rows
            if row["account_code"]
            in structure["leaf_codes"]
        ]
    else:
        calculation_rows = rows

    total_debit = sum(
        (
            row["debit"]
            for row in calculation_rows
        ),
        Decimal("0"),
    )

    total_credit = sum(
        (
            row["credit"]
            for row in calculation_rows
        ),
        Decimal("0"),
    )

    validation = validate_balance(
        total_debit=total_debit,
        total_credit=total_credit,
    )

    financial_statements = build_financial_statements(
        accounts=accounts,
    )

    financial_ratios = build_ratios(
        financial_statements=financial_statements,
    )

    financial_insights = build_insights(
        financial_statements=financial_statements,
        financial_ratios=financial_ratios,
    )

    warnings: list[str] = []
    errors: list[str] = []

    errors.extend(validation["errors"])

    if rejected_rows:
        warnings.append(
            f"{len(rejected_rows)} bozuk veya geçersiz satır "
            "hesaplamaya dahil edilmedi."
        )

    empty_account_names = sum(
        1
        for row in rows
        if not row["account_name"]
    )

    if empty_account_names:
        warnings.append(
            f"{empty_account_names} satırda hesap adı boş."
        )

    if structure["hierarchical"]:
        warnings.append(
            f"{structure['parent_count']} özet/üst hesap "
            "hesaplamaya dahil edilmedi."
        )

    if not financial_statements[
        "balance_sheet"
    ]["balanced"]:
        warnings.append(
            "Oluşturulan bilanço denk değil. "
            "Hesap sınıflandırmaları kontrol edilmelidir."
        )

    if not financial_ratios[
        "data_quality"
    ]["income_statement_available"]:
        warnings.append(
            "Gelir tablosu hesapları bulunmadığı için "
            "kârlılık oranları hesaplanamadı."
        )

    preview = [
        {
            "row_number": row["row_number"],
            "account_code": row["account_code"],
            "account_name": row["account_name"],
            "debit": decimal_to_float(row["debit"]),
            "credit": decimal_to_float(row["credit"]),
            "is_summary": (
                row["account_code"]
                in structure["parent_codes"]
            ),
            "is_leaf": (
                row["account_code"]
                in structure["leaf_codes"]
            ),
        }
        for row in rows[:10]
    ]

    account_tree_preview = [
        account.to_dict()
        for account in accounts[:20]
    ]

    return {
        "status": (
            "VALID"
            if not errors
            else "INVALID"
        ),
        "filename": filename,
        "vendor": "unknown",
        "parser": "generic",
        "format": structure["type"],
        "source_row_count": len(dataframe),
        "row_count": len(rows),
        "rejected_row_count": len(rejected_rows),
        "calculation_row_count": len(calculation_rows),
        "detected_columns": detected_columns,
        "structure": {
            "hierarchical": structure["hierarchical"],
            "parent_accounts": structure["parent_count"],
            "leaf_accounts": structure["leaf_count"],
            "calculation_scope": (
                "leaf_accounts"
                if structure["hierarchical"]
                else "all_accounts"
            ),
        },
        "totals": {
            "total_debit": decimal_to_float(
                total_debit
            ),
            "total_credit": decimal_to_float(
                total_credit
            ),
            "difference": decimal_to_float(
                validation["difference"]
            ),
            "balanced": validation["balanced"],
        },
        "errors": errors,
        "warnings": warnings,
        "account_tree_preview": account_tree_preview,
        "financial_statements": financial_statements,
        "financial_ratios": financial_ratios,
        "financial_insights": financial_insights,
        "preview": preview,
        "rejected_rows": serialize_rejected_rows(
            rejected_rows
        ),
    }