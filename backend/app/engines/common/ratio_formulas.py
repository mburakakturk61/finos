"""
Milestone 4.1 (Analysis Foundation): Financial Ratio Engine'in (Milestone 4.3)
kullanacağı oran formülleri için ortak SÖZLEŞME katmanı.

BİLİNÇLİ OLARAK bu dosyada GERÇEK oran formülleri (current_ratio,
debt_to_equity vb.) YOK -- onaylanan Milestone 4.1 kararı #7 gereği, henüz
hiçbir motor bu formülleri çağırmayacakken "çalışan altyapı görünümü veren
ölü API" (çok sayıda NotImplementedError gövdeli public fonksiyon) BİLEREK
üretilmedi. Bu dosya yerine üç şey sağlar:

  1. RatioFormulaMetadata -- bir oran formülünün KİMLİĞİ ve sözleşmesi
     (Milestone 4.3'te gerçek hesaplama mantığı bu üstverilerle eşleşecek).
  2. register_ratio_formula / RATIO_REGISTRY -- formül kayıt mekanizması,
     GERÇEK ve şimdiden test edilebilir (boş başlar, Milestone 4.3 doldurur).
  3. safe_divide / decimal_to_json_safe -- GERÇEKTEN kullanılabilir, Decimal
     tabanlı, bugünden itibaren her motor tarafından çağrılabilecek ortak
     yardımcı fonksiyonlar (app.trial_balance.ratios::safe_divide'ın
     float yerine Decimal kullanan, motor-bağımsız kopyası -- aynı
     "trial_balance/**'e bağımlılık kurma" gerekçesiyle bağımsız yazıldı,
     bkz. app.engines.common.chart_of_accounts docstring'i).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


def safe_divide(
    numerator: Decimal | None,
    denominator: Decimal | None,
    *,
    quantize_exp: str = "0.0001",
) -> Decimal | None:
    """
    Decimal-güvenli bölme. `numerator` veya `denominator` None ise, ya da
    `denominator` 0 ise None döner -- asla 0 veya fabrike edilmiş bir değer
    üretmez (eksik veri politikası, onaylanan Milestone 4.1 kararı #6/#7 ile
    tutarlı). Sonuç `quantize_exp` hassasiyetinde (varsayılan 4 ondalık)
    yuvarlanır.
    """

    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return (numerator / denominator).quantize(
        Decimal(quantize_exp), rounding=ROUND_HALF_UP
    )


def decimal_to_json_safe(value: Decimal | None) -> float | None:
    """
    JSON serialization SINIRINDA kontrollü Decimal -> float dönüşümü.
    Yalnızca DIŞA (result_json'a yazarken) kullanılır -- hesaplama içi mantık
    HER ZAMAN Decimal kalmalı, bu fonksiyon yalnızca son adımda çağrılır.
    None girişte None döner (0 üretmez).
    """

    if value is None:
        return None
    return float(value)


@dataclass(frozen=True)
class RatioFormulaMetadata:
    """
    Bir oran formülünün kimliği ve veri sözleşmesi. Milestone 4.3'te gerçek
    hesaplama fonksiyonu bu üstveriyle EŞLEŞECEK ŞEKİLDE yazılacak --
    `numerator_fields`/`denominator_fields`, ilgili canonical facts
    dataclass'ındaki (app.engines.common.canonical_facts) alan adlarına
    karşılık gelir.

    Milestone 4 mimari dokümanının (B.4) istediği oran kategorileri:
    "liquidity" | "activity" | "profitability" | "leverage" | "cash".
    """

    key: str
    category: str
    display_name_tr: str
    numerator_fields: tuple[str, ...]
    denominator_fields: tuple[str, ...]
    unit: str  # "ratio" | "percentage" | "days" | "currency"


RATIO_REGISTRY: dict[str, RatioFormulaMetadata] = {}
# Milestone 4.1'de BİLEREK BOŞ -- gerçek oran formülleri (current_ratio,
# quick_ratio, debt_to_equity, roa, roe, cash_conversion_cycle vb., bkz.
# Milestone 4 mimari dokümanı B.4) Milestone 4.3'te register_ratio_formula
# ile buraya eklenecek.


def register_ratio_formula(metadata: RatioFormulaMetadata) -> None:
    """Bir oran formülü üstverisini RATIO_REGISTRY'ye ekler. Aynı `key` ile
    ikinci kez kayıt denemesi hatadır -- sessiz üzerine yazma yok."""

    if metadata.key in RATIO_REGISTRY:
        raise ValueError(f"Oran formülü zaten kayıtlı: {metadata.key!r}")
    RATIO_REGISTRY[metadata.key] = metadata


def get_ratio_formula(key: str) -> RatioFormulaMetadata | None:
    return RATIO_REGISTRY.get(key)


def list_ratio_formulas_by_category(category: str) -> list[RatioFormulaMetadata]:
    return [
        metadata
        for metadata in RATIO_REGISTRY.values()
        if metadata.category == category
    ]
