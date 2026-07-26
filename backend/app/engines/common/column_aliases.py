"""
Milestone 4.2: Balance Sheet/Income Statement Excel'lerinde kolon tespiti.
`app.trial_balance.column_detector` ile AYNI kavramsal yaklaşım (normalize
edilmiş başlık -> alias eşlemesi) ama BAĞIMSIZ, yeniden yazılmış bir kopya
(import edilmiyor -- bkz. app/engines/common/chart_of_accounts.py
docstring'i, aynı gerekçe). trial_balance'ın debit/credit ayrımına ihtiyaç
YOK -- resmi bilanço/gelir tablosu formatında tek bir "tutar" kolonu olur.
"""

from app.engines.common.text_normalize import normalize_text


ACCOUNT_NAME_ALIASES = {
    "hesap adi", "kalem", "kalem adi", "aciklama", "aktif pasif kalemleri",
    "account name", "line item", "description",
}

AMOUNT_ALIASES = {
    "tutar", "bakiye", "cari donem", "cari donem tutari", "amount", "balance", "value",
}


def detect_bs_is_columns(headers: list[str]) -> dict[str, str]:
    """Sütun başlıklarından `{"account_name": <orijinal başlık>, "amount":
    <orijinal başlık>}` eşlemesini döner -- eşleşmeyenler sözlükte yer
    almaz (fabrikasyon yok)."""

    detected: dict[str, str] = {}

    for header in headers:
        normalized = normalize_text(str(header))
        if not normalized:
            continue
        if normalized in ACCOUNT_NAME_ALIASES and "account_name" not in detected:
            detected["account_name"] = header
        elif normalized in AMOUNT_ALIASES and "amount" not in detected:
            detected["amount"] = header

    return detected
