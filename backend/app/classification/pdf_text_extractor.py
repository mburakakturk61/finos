"""
PDF'ten hafif, OCR'siz metin çıkarımı (pypdf). Yalnızca ilk birkaç sayfa
okunur -- kimlik/dönem bilgisi neredeyse her zaman ilk sayfa(lar)da
bulunur, tüm belgeyi taramaya gerek yok. Taranmış (görüntü tabanlı,
metin katmanı olmayan) PDF'ler bu aşamada desteklenmiyor -- OCR ayrı,
gelecekteki bir faz (bkz. Milestone 2 / Adım 3 planı, madde 11).
"""

from io import BytesIO

import pypdf


MAX_PAGES_TO_SCAN = 3


class PdfExtractionError(Exception):
    """PDF açılamadı/parse edilemedi (şifreli, bozuk, desteklenmeyen vb.)."""


def extract_pdf_text(content: bytes) -> str:
    try:
        reader = pypdf.PdfReader(BytesIO(content))

        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as error:
                raise PdfExtractionError("PDF şifreli, açılamadı.") from error

        page_count = len(reader.pages)
        texts: list[str] = []

        for index in range(min(page_count, MAX_PAGES_TO_SCAN)):
            texts.append(reader.pages[index].extract_text() or "")

        return "\n".join(texts)
    except PdfExtractionError:
        raise
    except Exception as error:
        raise PdfExtractionError(
            "PDF okunamadı veya ayrıştırılamadı."
        ) from error
