"""
Milestone 4.2: metin tabanlı PDF'lerden (veya etiketli düz metinden) satır
satır etiket + tutar çıkarımı. `app.engines.common.statement_labels`
içindeki kural tablolarıyla birlikte kullanılır.

Yalnızca metin çıkarılabilen PDF'ler desteklenir -- taranmış/görüntü
tabanlı PDF'ler (OCR) bu milestone'un KAPSAMI DIŞINDA (onaylanan Milestone
4.2 kararı #6); çağıran taraf (extractor) `content_text` boşsa bu modülü
hiç çağırmaz.
"""

import re
from decimal import Decimal, InvalidOperation

from app.engines.common.text_normalize import normalize_text


# Türkçe sayı biçimi (1.234.567,89) VE düz biçim (1234567.89) ikisini de
# yakalar -- kaynak belgenin hangi yerelleştirmeyi kullandığı önceden
# bilinmiyor.
_NUMBER_PATTERN = re.compile(r"-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|-?\d+(?:[.,]\d+)?")


def _parse_amount(raw: str) -> Decimal | None:
    cleaned = raw.strip()
    if not cleaned:
        return None

    negative = cleaned.startswith("-")
    if negative:
        cleaned = cleaned[1:]

    if "," in cleaned and "." in cleaned:
        # Türkçe biçim varsayımı: nokta bin ayracı, virgül ondalık.
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        # Yalnızca virgül var -- ondalık ayracı olarak kabul edilir.
        cleaned = cleaned.replace(",", ".")

    if negative:
        cleaned = "-" + cleaned

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def extract_labeled_amounts_from_text(
    text: str,
    label_rules: list[tuple[str, str]],
) -> dict[str, Decimal]:
    """
    Metni satır satır tarar; her satırda `label_rules` sırasıyla eşleşen
    İLK anahtar kelimeyi bulur ve o satırdaki SON sayıyı (genellikle en
    sağdaki "cari dönem" tutarı) o alana atar. Bir alan zaten dolduysa
    (metinde birden fazla eşleşme varsa) İLK bulunan değer korunur --
    ikinci eşleşme SESSİZCE üzerine yazmaz.

    Eşleşme bulunamayan alanlar sonuç sözlüğünde YER ALMAZ (0 değil, hiç
    yok) -- çağıran taraf bunu `getattr(facts, alan) is None` ile ayırt
    eder.
    """

    facts: dict[str, Decimal] = {}

    for raw_line in text.splitlines():
        normalized_line = normalize_text(raw_line)
        if not normalized_line:
            continue

        for keyword, field_name in label_rules:
            if field_name in facts:
                continue
            if keyword not in normalized_line:
                continue

            numbers = _NUMBER_PATTERN.findall(raw_line)
            if not numbers:
                continue

            amount = _parse_amount(numbers[-1])
            if amount is not None:
                facts[field_name] = amount
            break

    return facts
