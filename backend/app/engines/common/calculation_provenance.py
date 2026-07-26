"""
Milestone 4.2: `result_json` sözleşmesinin zorunlu `calculation_provenance`
alanı için ortak veri şekli (onaylanan Milestone 4.2 kararı #9). Her
türetilmiş metrik için formül/kullanılan alanlar/eksik girdiler/hesaplanıp
hesaplanmadığı AÇIKÇA kaydedilir -- bir metrik hesaplanamadıysa
(`calculated=False`) asla sahte bir değer üretilmez, yalnızca bu kayıt
"neden hesaplanamadığını" açıklar.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProvenanceEntry:
    metric: str
    derivation_rule: str
    input_fields: tuple[str, ...]
    missing_inputs: tuple[str, ...]
    calculated: bool


def provenance_to_dict(entry: ProvenanceEntry) -> dict:
    return {
        "metric": entry.metric,
        "formula": entry.derivation_rule,
        "input_fields": list(entry.input_fields),
        "missing_inputs": list(entry.missing_inputs),
        "calculated": entry.calculated,
    }


def provenance_list_to_dict(entries: list[ProvenanceEntry]) -> list[dict]:
    return [provenance_to_dict(entry) for entry in entries]
