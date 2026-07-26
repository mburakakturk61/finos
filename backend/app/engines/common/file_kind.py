"""
Milestone 4.2: dosya türü tespiti (magic bytes + uzantı). `app.classification.
orchestrator._sniff_kind` ile AYNI kavramsal yaklaşım -- ama o fonksiyon
`app/classification/**` içinde PRIVATE (alt çizgili) ve dışa açık bir
sözleşme değil, bu yüzden import edilmiyor; bağımsız, küçük bir kopyası
burada yazıldı.

Milestone 4.2 kapsam sınırı (onaylanan karar #6): yalnızca `.xlsx` ve PDF
tanınır -- legacy `.xls` (OLE2/BIFF) BİLEREK dışarıda bırakıldı (trial_balance
motorunun kendisi de yalnızca `.xlsx` okuyor, aynı tutarlılık).
"""

PDF_MAGIC = b"%PDF-"
XLSX_MAGIC = b"PK\x03\x04"  # .xlsx (zip tabanlı)


def sniff_file_kind(filename: str | None, content: bytes) -> str:
    """'xlsx' | 'pdf' | 'unknown' döner."""

    header = content[:8] if content else b""

    if header.startswith(PDF_MAGIC):
        return "pdf"
    if header.startswith(XLSX_MAGIC):
        return "xlsx"

    lower_name = (filename or "").lower()
    if lower_name.endswith(".pdf"):
        return "pdf"
    if lower_name.endswith(".xlsx"):
        return "xlsx"

    return "unknown"
