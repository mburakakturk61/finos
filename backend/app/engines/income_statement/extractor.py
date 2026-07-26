"""
Milestone 4.2: doğrudan yüklenen bir gelir tablosu belgesinden (`.xlsx` veya
metin tabanlı `.pdf`) `IncomeStatementFacts` çıkarımı.

`app.engines.balance_sheet.extractor` ile AYNI strateji/kapsam sınırları
(bkz. o dosyanın docstring'i) -- yalnızca kural tablosu ve hedef canonical
şekil farklı.
"""

from decimal import Decimal, InvalidOperation
from io import BytesIO

import pandas as pd

from app.classification.pdf_text_extractor import PdfExtractionError, extract_pdf_text
from app.engines.common.canonical_facts import IncomeStatementFacts
from app.engines.common.column_aliases import detect_bs_is_columns
from app.engines.common.file_kind import sniff_file_kind
from app.engines.common.label_line_parser import extract_labeled_amounts_from_text
from app.engines.common.statement_labels import INCOME_STATEMENT_LABEL_RULES
from app.engines.common.text_normalize import normalize_text


CORE_FIELDS_FOR_WARNING = ["net_sales", "gross_profit", "operating_profit"]


class IncomeStatementExtractionError(Exception):
    """Belge okunamadı/ayrıştırılamadı veya tanınan hiçbir kalem bulunamadı
    -- mesajı HER ZAMAN sabit, sanitize edilmiş bir metindir; ham exception
    asla dışarı sızmaz (onaylanan Milestone 4.2 kararı #6)."""


def extract_income_statement_facts(
    content: bytes, filename: str | None
) -> tuple[IncomeStatementFacts, list[str]]:
    kind = sniff_file_kind(filename, content)

    if kind == "xlsx":
        facts_dict = _extract_from_xlsx(content)
    elif kind == "pdf":
        facts_dict = _extract_from_pdf(content)
    else:
        raise IncomeStatementExtractionError(
            "Desteklenmeyen dosya türü -- yalnızca .xlsx ve metin tabanlı "
            ".pdf destekleniyor."
        )

    if not facts_dict:
        raise IncomeStatementExtractionError(
            "Belgede tanınan hiçbir gelir tablosu kalemi bulunamadı."
        )

    facts = IncomeStatementFacts(**facts_dict)

    warnings = [
        f"'{field_name}' alanı belgede tespit edilemedi."
        for field_name in CORE_FIELDS_FOR_WARNING
        if getattr(facts, field_name) is None
    ]

    return facts, warnings


def _extract_from_xlsx(content: bytes) -> dict[str, Decimal]:
    try:
        dataframe = pd.read_excel(BytesIO(content), engine="openpyxl")
    except Exception as error:
        raise IncomeStatementExtractionError(
            "Excel dosyası okunamadı veya bozuk."
        ) from error

    if dataframe.empty:
        raise IncomeStatementExtractionError("Excel dosyasında veri bulunamadı.")

    columns = detect_bs_is_columns(list(dataframe.columns))
    if "account_name" not in columns or "amount" not in columns:
        raise IncomeStatementExtractionError(
            "Beklenen kolon yapısı (kalem adı + tutar) tespit edilemedi."
        )

    name_col = columns["account_name"]
    amount_col = columns["amount"]

    facts_dict: dict[str, Decimal] = {}
    for _, row in dataframe.iterrows():
        label = normalize_text(str(row.get(name_col, "")))
        raw_amount = row.get(amount_col)
        if not label or raw_amount is None or (isinstance(raw_amount, float) and pd.isna(raw_amount)):
            continue

        try:
            amount = Decimal(str(raw_amount))
        except (InvalidOperation, ValueError):
            continue

        for keyword, field_name in INCOME_STATEMENT_LABEL_RULES:
            if field_name in facts_dict:
                continue
            if keyword in label:
                facts_dict[field_name] = amount
                break

    return facts_dict


def _extract_from_pdf(content: bytes) -> dict[str, Decimal]:
    try:
        text = extract_pdf_text(content)
    except PdfExtractionError as error:
        raise IncomeStatementExtractionError(
            "PDF'ten metin çıkarılamadı -- taranmış/görüntü tabanlı olabilir "
            "(OCR desteklenmiyor)."
        ) from error

    if not text.strip():
        raise IncomeStatementExtractionError(
            "PDF'ten metin çıkarılamadı -- taranmış/görüntü tabanlı olabilir "
            "(OCR desteklenmiyor)."
        )

    return extract_labeled_amounts_from_text(text, INCOME_STATEMENT_LABEL_RULES)
