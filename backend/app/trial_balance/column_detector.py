import re
import unicodedata
from typing import Any


COLUMN_ALIASES = {
    "account_code": [
        "hesap kodu",
        "hesapkodu",
        "hesap no",
        "hesap numarasi",
        "account code",
        "account_code",
        "account no",
    ],
    "account_name": [
        "hesap adi",
        "hesap ismi",
        "hesap aciklamasi",
        "account name",
        "account_name",
        "description",
    ],
    "debit": [
        "borc",
        "borc tutari",
        "toplam borc",
        "debit",
        "debit amount",
        "dr",
    ],
    "credit": [
        "alacak",
        "alacak tutari",
        "toplam alacak",
        "credit",
        "credit amount",
        "cr",
    ],
    "opening_debit": [
        "acilis borc",
        "devir borc",
        "opening debit",
    ],
    "opening_credit": [
        "acilis alacak",
        "devir alacak",
        "opening credit",
    ],
    "closing_debit": [
        "bakiye borc",
        "borc bakiye",
        "closing debit",
    ],
    "closing_credit": [
        "bakiye alacak",
        "alacak bakiye",
        "closing credit",
    ],
}


def normalize_text(value: Any) -> str:
    text = str(value or "").strip().lower()

    replacements = {
        "ı": "i",
        "ş": "s",
        "ğ": "g",
        "ü": "u",
        "ö": "o",
        "ç": "c",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    text = text.replace("_", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def detect_columns(columns: list[Any]) -> dict[str, str]:
    normalized_columns = {
        normalize_text(column): str(column)
        for column in columns
    }

    detected: dict[str, str] = {}

    for standard_name, aliases in COLUMN_ALIASES.items():
        normalized_aliases = [
            normalize_text(alias)
            for alias in aliases
        ]

        for alias in normalized_aliases:
            if alias in normalized_columns:
                detected[standard_name] = normalized_columns[alias]
                break

    return detected
