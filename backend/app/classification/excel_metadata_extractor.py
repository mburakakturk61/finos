"""
Excel (.xlsx/.xls) dosyalarından sınıflandırma için hafif metadata
çıkarımı: sheet adları, kolon başlıkları, ilk birkaç veri satırı. Tam
dosyayı finansal olarak ANALİZ ETMEZ (bu iş app.trial_balance'ta) --
yalnızca sınıflandırma ipuçları toplar.

.xls (legacy OLE2/BIFF) desteği kodda hazırdır (xlrd motoru) ancak xlrd
paketinin kurulu olmasını gerektirir -- requirements.txt'e eklendi.
"""

from dataclasses import dataclass, field
from io import BytesIO

import pandas as pd


MAX_SAMPLE_ROWS = 5


class ExcelExtractionError(Exception):
    """Excel dosyası açılamadı/parse edilemedi."""


@dataclass
class ExcelMetadata:
    sheet_names: list[str] = field(default_factory=list)
    column_headers: list[str] = field(default_factory=list)
    sample_rows_text: str = ""
    engine_used: str = ""


def _engine_for_filename(filename: str) -> str:
    if filename.lower().endswith(".xls"):
        return "xlrd"
    return "openpyxl"


def extract_excel_metadata(content: bytes, filename: str) -> ExcelMetadata:
    engine = _engine_for_filename(filename)

    try:
        excel_file = pd.ExcelFile(BytesIO(content), engine=engine)
        sheet_names = list(excel_file.sheet_names)
        first_sheet = sheet_names[0]
        dataframe = excel_file.parse(first_sheet, nrows=MAX_SAMPLE_ROWS)
    except ImportError as error:
        raise ExcelExtractionError(
            f"'{engine}' motoru kurulu değil, Excel dosyası okunamadı."
        ) from error
    except Exception as error:
        raise ExcelExtractionError(
            "Excel dosyası okunamadı veya ayrıştırılamadı."
        ) from error

    column_headers = [str(column) for column in dataframe.columns]
    sample_rows_text = dataframe.to_string(index=False)

    return ExcelMetadata(
        sheet_names=sheet_names,
        column_headers=column_headers,
        sample_rows_text=sample_rows_text,
        engine_used=engine,
    )
