"""
Milestone 4.2: `result_json` sözleşmesinin zorunlu `calculation_provenance`
alanı için ortak veri şekli (onaylanan Milestone 4.2 kararı #9). Her
türetilmiş metrik için formül/kullanılan alanlar/eksik girdiler/hesaplanıp
hesaplanmadığı AÇIKÇA kaydedilir -- bir metrik hesaplanamadıysa
(`calculated=False`) asla sahte bir değer üretilmez, yalnızca bu kayıt
"neden hesaplanamadığını" açıklar.

Milestone 4.3A (Ratio Calculation Foundation, onaylanan mimari doküman
Bölüm I.2/R.1): `ProvenanceEntry`'ye üç ADDITIVE, geriye uyumlu alan
eklendi (`source_analysis_result_ids`/`reliability`/`rounding_applied`).
KRİTİK: `provenance_to_dict()` BİLİNÇLİ OLARAK DEĞİŞTİRİLMEDİ -- hâlâ
yalnızca eski 5 anahtarı üretir. Balance Sheet/Income Statement
motorlarının `result_json["calculation_provenance"]` DIŞ SÖZLEŞMESİ
(bkz. tests/test_engine_balance_income_statement_unit.py::
test_analyze_income_statement_provenance_contract) bu fonksiyona
bağımlıdır ve Milestone 4.3A onayında "BS/IS result_json dış sözleşmesini
değiştirme" kesin sınırı verildi. Yeni alanlar yalnızca
`provenance_to_dict_extended()` ile açığa çıkar -- bu, YALNIZCA Financial
Ratio Engine'in KENDİ (yeni, henüz hiçbir dış tüketicisi olmayan)
result_json'u tarafından kullanılır.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProvenanceEntry:
    metric: str
    derivation_rule: str
    input_fields: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    calculated: bool
    # Milestone 4.3A: additive, geriye uyumlu (varsayılan değerli) alanlar.
    source_analysis_result_ids: tuple[str, ...] = ()
    reliability: str | None = None
    rounding_applied: str | None = None


def provenance_to_dict(entry: ProvenanceEntry) -> dict:
    """
    DEĞİŞMEDİ (Milestone 4.2'den beri) -- yalnızca eski 5 anahtarı üretir.
    Milestone 4.3A'da BİLİNÇLİ OLARAK genişletilmedi (bkz. modül
    docstring'i) -- BS/IS motorlarının dış sözleşmesini korumak için.
    """
    return {
        "metric": entry.metric,
        "formula": entry.derivation_rule,
        "input_fields": list(entry.input_fields),
        "missing_inputs": list(entry.missing_inputs),
        "calculated": entry.calculated,
    }


def provenance_to_dict_extended(entry: ProvenanceEntry) -> dict:
    """
    Milestone 4.3A: I.2'deki additive alanları DA içeren genişletilmiş
    serileştirme -- yalnızca Financial Ratio Engine'in KENDİ result_json'u
    tarafından kullanılır (`app/engines/financial_ratios/service.py`),
    BS/IS motorlarının mevcut sözleşmesini HİÇ etkilemez.
    """
    base = provenance_to_dict(entry)
    base["source_analysis_result_ids"] = list(entry.source_analysis_result_ids)
    base["reliability"] = entry.reliability
    base["rounding_applied"] = entry.rounding_applied
    return base


def provenance_list_to_dict(entries: list[ProvenanceEntry]) -> list[dict]:
    return [provenance_to_dict(entry) for entry in entries]


def provenance_list_to_dict_extended(entries: list[ProvenanceEntry]) -> list[dict]:
    return [provenance_to_dict_extended(entry) for entry in entries]
