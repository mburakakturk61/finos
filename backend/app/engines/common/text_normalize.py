"""
Milestone 4.2: Türkçe metin normalizasyonu (küçük harfe çevirme, aksanlı
karakterleri sadeleştirme, noktalama/boşluk sadeleştirme). `app.classification.
document_classifier`/`app.trial_balance.column_detector` içindeki AYNI
kavramsal yaklaşımın, `app/engines/**`'in kendi bağımsız kopyası (import
edilmiyor -- bkz. app/engines/common/chart_of_accounts.py docstring'i,
aynı gerekçe).
"""

import re
import unicodedata


_TURKISH_MAP = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ş": "s",
        "Ş": "s",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }
)


def normalize_text(text: str) -> str:
    """Küçük harfe çevirir, Türkçe aksanlı karakterleri sadeleştirir,
    alfanumerik olmayan karakterleri tek boşluğa indirger, baş/son
    boşlukları kırpar."""

    if text is None:
        return ""

    lowered = str(text).translate(_TURKISH_MAP).lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return normalized.strip()
