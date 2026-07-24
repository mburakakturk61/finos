from io import BytesIO
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile

app = FastAPI(
    title="FINOS API",
    version="0.2.0",
    description="Financial Intelligence & Operating System",
)

COLUMN_ALIASES = {
    "account_code": [
        "hesap kodu",
        "hesapkodu",
        "hesap no",
        "account code",
        "account_code",
    ],
    "account_name": [
        "hesap adı",
        "hesap adi",
        "hesap ismi",
        "account name",
        "account_name",
    ],
    "debit": [
        "borç",
        "borc",
        "borç tutarı",
        "borc tutari",
        "debit",
        "dr",
    ],
    "credit": [
        "alacak",
        "alacak tutarı",
        "alacak tutari",
        "credit",
        "cr",
    ],
}


def normalize_header(value: Any) -> str:
    return " ".join(
        str(value)
        .strip()
        .lower()
        .replace("_", " ")
        .split()
    )


def detect_columns(columns: list[Any]) -> dict[str, str]:
    normalized_columns = {
        normalize_header(column): str(column)
        for column in columns
    }

    detected: dict[str, str] = {}

    for standard_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized_columns:
                detected[standard_name] = normalized_columns[alias]
                break

    return detected


def parse_number(value: Any) -> float:
    if pd.isna(value):
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().replace(" ", "")

    if not text:
        return 0.0

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return 0.0


def to_number(series: pd.Series) -> pd.Series:
    return series.apply(parse_number)


@app.get("/")
def root():
    return {
        "application": "FINOS",
        "status": "running",
        "version": "0.2.0",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/trial-balance/validate")
async def validate_trial_balance(
    file: UploadFile = File(...)
):
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Dosya adı bulunamadı.",
        )

    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Şimdilik yalnızca .xlsx dosyaları kabul edilir.",
        )

    content = await file.read()

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Dosya boyutu 10 MB sınırını aşıyor.",
        )

    try:
        dataframe = pd.read_excel(
            BytesIO(content),
            engine="openpyxl",
        )
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"Excel dosyası okunamadı: {error}",
        ) from error

    if dataframe.empty:
        raise HTTPException(
            status_code=400,
            detail="Excel dosyasında veri bulunamadı.",
        )

    detected_columns = detect_columns(
        list(dataframe.columns)
    )

    required_columns = {
        "account_code",
        "account_name",
        "debit",
        "credit",
    }

    missing_columns = sorted(
        required_columns - set(detected_columns)
    )

    if missing_columns:
        return {
            "status": "INVALID",
            "filename": file.filename,
            "row_count": len(dataframe),
            "detected_columns": detected_columns,
            "missing_columns": missing_columns,
            "errors": [
                "Zorunlu kolonlardan bazıları bulunamadı."
            ],
        }

    debit_values = to_number(
        dataframe[detected_columns["debit"]]
    )

    credit_values = to_number(
        dataframe[detected_columns["credit"]]
    )

    total_debit = round(float(debit_values.sum()), 2)
    total_credit = round(float(credit_values.sum()), 2)
    difference = round(total_debit - total_credit, 2)
    balanced = abs(difference) <= 0.01

    errors: list[str] = []
    warnings: list[str] = []

    if not balanced:
        errors.append(
            f"Mizan dengede değil. Borç-alacak farkı: {difference}"
        )

    account_code_column = detected_columns["account_code"]
    account_name_column = detected_columns["account_name"]

    empty_account_codes = int(
        dataframe[account_code_column].isna().sum()
    )

    empty_account_names = int(
        dataframe[account_name_column].isna().sum()
    )

    if empty_account_codes:
        errors.append(
            f"{empty_account_codes} satırda hesap kodu boş."
        )

    if empty_account_names:
        warnings.append(
            f"{empty_account_names} satırda hesap adı boş."
        )

    preview = dataframe[
        [
            account_code_column,
            account_name_column,
            detected_columns["debit"],
            detected_columns["credit"],
        ]
    ].head(10).fillna("").to_dict(orient="records")

    return {
        "status": "VALID" if not errors else "INVALID",
        "filename": file.filename,
        "row_count": len(dataframe),
        "detected_columns": detected_columns,
        "totals": {
            "total_debit": total_debit,
            "total_credit": total_credit,
            "difference": difference,
            "balanced": balanced,
        },
        "errors": errors,
        "warnings": warnings,
        "preview": preview,
    }
