"""
Milestone 4.3A (Ratio Calculation Foundation): birden çok oranın ortak
ihtiyaç duyduğu türetilmiş ("ara") mali büyüklüklerin TEK üretim noktası
(onaylanan mimari doküman, Bölüm C.0/R.5). Bu dosya BİLEREK yalnızca iki
türetilmiş alanı kapsar -- `total_liabilities` ve `days_in_period`;
`average_*` alanları (önceki döneme bağımlı devir hızı oranları için)
Milestone 4.3B'ye bırakılmıştır -- Milestone 4.3A'nın hiçbir oranı bunları
tüketmiyor.

app/engines/common/** deseniyle tutarlı: sqlalchemy/fastapi/pydantic'e
SIFIR bağımlı.
"""

from datetime import date
from decimal import Decimal
from typing import Any


def compute_total_liabilities(
    short_term_liabilities: Decimal | None,
    long_term_liabilities: Decimal | None,
) -> Decimal | None:
    """
    `total_liabilities = short_term_liabilities + long_term_liabilities`.

    İkisinden biri `None` ise sonuç `None`'dır -- kısmi toplam (bilinmeyen
    bir bileşeni 0 sayarak) ASLA üretilmez. `app.engines.balance_sheet.
    analyzer::compute_preliminary_structural_ratios`'un Milestone 4.2'deki
    yerel `total_liabilities` türetiminin (bkz. o dosyanın eski hâli)
    BİREBİR taşınmış, tek merkezi hâlidir -- artık BS analyzer'ı da bu
    fonksiyonu çağırır, kendi toplamını yeniden yazmaz.
    """

    if short_term_liabilities is None or long_term_liabilities is None:
        return None
    return short_term_liabilities + long_term_liabilities


def compute_days_in_period(
    *,
    start_date: date | None,
    end_date: date | None,
    months_covered: int | None,
) -> tuple[Decimal | None, str, dict[str, Any] | None]:
    """
    Döner: `(days_in_period, reliability, warning_dict_or_None)`.

    Onaylanan Milestone 4.3A kararı #8/#10: TEK birincil kaynak GERÇEK
    takvim günü farkı (`end_date - start_date`) -- `FinancialPeriod.
    start_date`/`end_date` şema seviyesinde NOT NULL olduğu için bu normal
    akışta HER ZAMAN mevcuttur. `months_covered * 30`, yalnızca bu iki
    tarih çağıran bağlamda GERÇEKTEN erişilemezse (ör. `FinancialPeriod`
    nesnesinin tam kendisi değil yalnızca kısmi alanları taşınan bir
    bağlam), AÇIKÇA düşük-güven (`reliability="low"`) bir fallback olarak
    kullanılır -- SESSİZCE birincil kaynakmış gibi asla kullanılmaz; bu
    durumda dönen `warning` HER ZAMAN doludur (provenance/warning'de açıkça
    görünür).

    İkisi de mevcut değilse `(None, "not_calculable", None)` döner --
    fabrike edilmiş bir gün sayısı ASLA üretilmez.

    NOT: Milestone 4.3A'nın 9 oranından HİÇBİRİ bu fonksiyonu henüz
    TÜKETMİYOR (gün-bazlı oranlar -- devir hızları -- Milestone 4.3B'de
    eklenecek); bu fonksiyon şimdiden altyapı olarak kuruluyor ve kendi
    başına test ediliyor.
    """

    if start_date is not None and end_date is not None:
        delta_days = (end_date - start_date).days
        return Decimal(delta_days), "high", None

    if months_covered is not None:
        warning = {
            "code": "DAYS_IN_PERIOD_LOW_CONFIDENCE_FALLBACK",
            "severity": "warning",
            "message": (
                "start_date/end_date bu bağlamda mevcut değil; "
                "days_in_period, months_covered * 30 ile DÜŞÜK GÜVENLİ bir "
                "yaklaşıklıkla hesaplandı (gerçek takvim günü farkı DEĞİL)."
            ),
        }
        return Decimal(months_covered) * Decimal("30"), "low", warning

    return None, "not_calculable", None
