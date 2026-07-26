"""
Milestone 4.3C (Benchmark Engine) / Adım 2: migration'sız şirket ölçeği
proxy'si (onaylanan tasarım dokümanı Bölüm 12, 2. tur onay karar #4).

`Company` modelinde çalışan sayısı/ciro dilimi gibi bir "şirket ölçeği"
alanı BUGÜN HİÇ YOK (Milestone 2'de bilinçli olarak dışarıda bırakıldı).
Migration YAZILMAZ (bağlayıcı karar #4) -- bunun yerine, Financial Ratio
Engine'in ZATEN ürettiği `net_sales`/`total_assets` büyüklüklerinden saf
bir proxy türetilir.

**Bağlayıcı sınırlamalar (karar #4, kesinlikle uygulanmalı):**
  - `reliability` HİÇBİR ZAMAN `"high"` OLAMAZ -- bu yalnızca mali
    büyüklüğe dayalı, çalışan sayısını HİÇ dikkate almayan bir proxy'dir.
  - Çalışan sayısının eksik olduğu HER SONUÇTA açıkça belirtilir
    (`employee_count_available=False` + sabit bir `disclaimer` metni) --
    sessizce kaybolmaz.
  - Bu sınıflandırma resmi bir KOBİ sınıflandırması OLARAK SUNULMAZ
    (KGK/KOSGEB tanımıyla eşdeğer olduğu iddia edilmez) -- yalnızca
    dahili, yaklaşık bir "benchmark override anahtarı" adayıdır.

sqlalchemy/fastapi/pydantic'e SIFIR bağımlı (mevcut `app/engines/
common/**` deseniyle tutarlı).
"""

from dataclasses import dataclass
from decimal import Decimal


DISCLAIMER = (
    "Bu şirket ölçeği sınıflandırması yalnızca mali büyüklüklere (net "
    "satış hasılatı ve/veya toplam aktif) dayanır; çalışan sayısı verisi "
    "MEVCUT DEĞİLDİR ve bu sınıflandırma resmi bir KOBİ sınıflandırması "
    "(KGK/KOSGEB tanımı) OLARAK SUNULMAMALIDIR -- yaklaşık, dahili bir "
    "proxy'dir."
)

# Yaklaşık, resmi olmayan mali büyüklük eşikleri (TRY) -- KOBİ tanımının
# yalnızca mali bacağına gevşek biçimde yakın, Türkiye'ye özgü ampirik
# kalibrasyon YAPILMAMIŞTIR (2. tur onay karar #1'deki "provisional"
# dürüstlük ilkesiyle aynı ruh). `indicator < threshold` sıralı taraması.
_SIZE_THRESHOLDS: tuple[tuple[Decimal, str], ...] = (
    (Decimal("10000000"), "micro"),
    (Decimal("100000000"), "small"),
    (Decimal("500000000"), "medium"),
)
_LARGEST_BUCKET = "large"

VALID_COMPANY_SIZE_BUCKETS: tuple[str, ...] = (
    "micro",
    "small",
    "medium",
    _LARGEST_BUCKET,
)


@dataclass(frozen=True)
class CompanySizeClassification:
    bucket: "str | None"
    reliability: str
    employee_count_available: bool
    disclaimer: str
    is_official_sme_classification: bool = False


def classify_company_size(
    net_sales: "Decimal | None", total_assets: "Decimal | None"
) -> CompanySizeClassification:
    """
    `net_sales`/`total_assets`'ten (ikisinden en büyük olanı -- eldeki
    en iyimser/en kapsamlı gösterge kullanılır, ama HİÇBİRİ fabrike
    edilmez) yaklaşık bir şirket ölçeği bucket'ı türetir.

    İkisi de `None` ise `(bucket=None, reliability="not_calculable")`
    döner -- fabrike edilmiş bir sınıf ASLA üretilmez.
    """

    indicators = [v for v in (net_sales, total_assets) if v is not None]
    if not indicators:
        return CompanySizeClassification(
            bucket=None,
            reliability="not_calculable",
            employee_count_available=False,
            disclaimer=DISCLAIMER,
        )

    indicator = max(indicators)
    bucket = _LARGEST_BUCKET
    for threshold, label in _SIZE_THRESHOLDS:
        if indicator < threshold:
            bucket = label
            break

    return CompanySizeClassification(
        bucket=bucket,
        # 2. tur onay karar #4: çalışan sayısı verisi hiç olmadığı için
        # HİÇBİR ZAMAN "high" -- en fazla "medium".
        reliability="medium",
        employee_count_available=False,
        disclaimer=DISCLAIMER,
    )
