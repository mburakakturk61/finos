"""
Her tahminin (document_type, company_name, tax_number, year, period_type,
period_number) NEDENİNİ açıkça saklamak için küçük, saf yardımcılar.
Şekil, kullanıcının verdiği örnekle birebir:

{
  "document_type": {"value": "corporate_tax_return", "source": "pdf_text", "evidence": "..."},
  "tax_number": {"value": "3310523185", "source": "pdf_text"},
}
"""

from typing import Any


def new_evidence() -> dict[str, Any]:
    return {}


def add_evidence(
    evidence: dict[str, Any],
    *,
    field: str,
    value: Any,
    source: str,
    snippet: str | None = None,
) -> None:
    entry: dict[str, Any] = {"value": value, "source": source}
    if snippet:
        entry["evidence"] = snippet
    evidence[field] = entry


def new_warnings() -> list[dict[str, Any]]:
    return []


def add_warning(
    warnings: list[dict[str, Any]],
    *,
    code: str,
    message: str,
    **extra: Any,
) -> None:
    entry: dict[str, Any] = {"code": code, "message": message}
    entry.update(extra)
    warnings.append(entry)
