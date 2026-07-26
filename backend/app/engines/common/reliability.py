"""
Milestone 4.3B (Core Financial Ratios) / Milestone 4.3C (Benchmark Engine):
`reliability` string'lerini karşılaştırmak için TEK, paylaşılan yardımcı
modül.

Bu fonksiyonlar önceden yalnızca `app/engines/financial_ratios/service.py`
içinde yerel (`_worse_reliability`/`_RELIABILITY_RANK`) olarak tanımlıydı
(Milestone 4.3B, Bölüm 8 "average hesaplarının tutarsızlığı" riskinin
giderilmesi için). Milestone 4.3C'nin Benchmark Engine'i de AYNI "iki
güvenilirlik seviyesinden kötüsünü al" ilkesine ihtiyaç duyduğu için (bir
oranın kendi reliability'si ile benchmark girdisinin
`reliability_ceiling`'i arasından kötüsü seçilir -- bkz.
docs/FINOS_MILESTONE_4_3C_BENCHMARK_ENGINE_DESIGN.md Bölüm 15), bu modül
buraya taşındı -- İKİ motor da (financial_ratios VE benchmarks) AYNI
fonksiyonu import eder, ikinci bir kopya YAZILMAZ.

`app/engines/financial_ratios/service.py`'nin DAVRANIŞI bu taşımayla
HİÇ DEĞİŞMEDİ -- yalnızca tanım yeri değişti (aynı sabitler, aynı mantık).

sqlalchemy/fastapi/pydantic'e SIFIR bağımlı (mevcut `app/engines/common/**`
deseniyle tutarlı).
"""

RELIABILITY_RANK: dict[str, int] = {
    "high": 3,
    "medium": 2,
    "medium_low": 1,
    "low": 1,
    "not_calculable": 0,
}


def worse_reliability(a: str, b: str) -> str:
    """
    İki reliability string'inden "daha kötü/daha düşük güvenilir" olanı
    döner. Eşitlik durumunda `a` döner (çağıranların davranışı
    `_worse_reliability`'nin eski yerel davranışıyla BİREBİR aynı kalır).
    """

    return a if RELIABILITY_RANK.get(a, 0) <= RELIABILITY_RANK.get(b, 0) else b
