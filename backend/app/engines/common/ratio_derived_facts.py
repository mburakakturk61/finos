"""
Milestone 4.3A (Ratio Calculation Foundation) / Milestone 4.3B (Core
Financial Ratios): birden çok oranın ortak ihtiyaç duyduğu türetilmiş
("ara") mali büyüklüklerin TEK üretim noktası (onaylanan mimari doküman,
Bölüm C.0/R.5; 4.3B tasarım dokümanı Bölüm 4).

Milestone 4.3A yalnızca iki türetilmiş alanı kapsıyordu --
`total_liabilities` ve `days_in_period`. Milestone 4.3B (2. tur onay
kararları #4/#7/#8) bunlara ekler:
  - `average_*` fonksiyonları (average_inventory/average_trade_receivables/
    average_trade_payables/average_total_assets/average_equity/
    average_working_capital) -- ikisi de dolu ise `(current+prior)/2`
    (`reliability="high"`, `calculation_basis="two_period_average"`),
    yalnızca cari doluysa dönem-sonu bakiyeye düşülür (`reliability=
    "medium"`, `calculation_basis="ending_balance_fallback"`) -- ÖNCEKİ
    DÖNEMİN BULUNMAMASI NORMAL bir iş durumudur, bu yüzden WARNING
    ÜRETİLMEZ (days_in_period'in months_covered*30 fallback'inden
    BİLİNÇLİ OLARAK farklı bir politika).
  - `compute_tax_expense`/`compute_invested_capital` -- effective_tax_rate/
    return_on_invested_capital için saf ara büyüklükler (Bölüm 5.3 kuralı:
    kullanıcıya doğrudan sunulmayan bileşenler burada, RATIO_REGISTRY'de
    DEĞİL).
  - `compute_days_in_period`'in birincil formülü `(end_date-start_date).
    days` DEĞİL, `(end_date-start_date).days + 1` (KAPSAYICI/inclusive) --
    `FinancialPeriod.start_date`/`end_date` dönem sınırlarının ikisi de
    dahil olduğu içindir (2. tur onay karar #8 -- 01.01-31.12 artık
    olmayan bir yılda 365, artık yılda 366 üretmesi gerekir, 364 DEĞİL).

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

    Milestone 4.3B (2. tur onay karar #8) DÜZELTMESİ: `FinancialPeriod.
    start_date`/`end_date` KAPSAYICI (inclusive) dönem sınırlarıdır --
    birincil formül `(end_date - start_date).days + 1`'dir (4.3A'daki
    orijinal tasarımda `+1` YOKTU, bu 01.01-31.12 gibi tam-yıl aralıklarında
    364 üretiyordu, 365/366 DEĞİL -- bu, gün-bazlı 4.3B oranlarının
    [days_inventory_outstanding vb.] doğru çalışması için gerekliydi).

    `months_covered * 30`, yalnızca bu iki tarih çağıran bağlamda GERÇEKTEN
    erişilemezse, AÇIKÇA düşük-güven (`reliability="low"`) bir fallback
    olarak kullanılır -- SESSİZCE birincil kaynakmış gibi asla kullanılmaz;
    bu durumda dönen `warning` HER ZAMAN doludur.

    `end_date < start_date` (geçersiz tarih sırası): kontrollü
    `(None, "not_calculable", warning)` döner -- ASLA negatif bir gün
    sayısı veya ham exception üretilmez (2. tur onay karar #8, zorunlu
    test #4).

    İkisi de mevcut değilse VE `months_covered` de yoksa `(None,
    "not_calculable", None)` döner -- fabrike edilmiş bir gün sayısı ASLA
    üretilmez.
    """

    if start_date is not None and end_date is not None:
        if end_date < start_date:
            warning = {
                "code": "DAYS_IN_PERIOD_INVALID_DATE_ORDER",
                "severity": "high",
                "message": (
                    f"end_date ({end_date}) start_date'ten ({start_date}) "
                    "önce -- geçersiz tarih sırası, days_in_period "
                    "hesaplanamadı (fabrike edilmiş/negatif bir değer "
                    "ÜRETİLMEDİ)."
                ),
            }
            return None, "not_calculable", warning

        delta_days = (end_date - start_date).days + 1
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


def _average_or_ending_balance(
    current: Decimal | None, prior: Decimal | None
) -> tuple[Decimal | None, str, str]:
    """
    Milestone 4.3B (2. tur onay karar #4): ortak `average_*` deseni.

    Döner: `(value, reliability, calculation_basis)`.
      - ikisi de doluysa: `(current+prior)/2`, `"high"`,
        `"two_period_average"`.
      - yalnızca `current` doluysa (`prior=None`): `current`, `"medium"`,
        `"ending_balance_fallback"` -- WARNING ÜRETİLMEZ (önceki dönemin
        bulunmaması NORMAL bir iş durumudur, veri kalitesi sorunu DEĞİL --
        `compute_days_in_period`'in `months_covered*30` fallback'inden
        BİLİNÇLİ OLARAK farklı bir politika).
      - ikisi de yoksa: `(None, "not_calculable", "not_calculable")`.
    """

    if current is not None and prior is not None:
        return (current + prior) / Decimal("2"), "high", "two_period_average"
    if current is not None:
        return current, "medium", "ending_balance_fallback"
    return None, "not_calculable", "not_calculable"


def compute_average_inventory(
    current_inventory: Decimal | None, prior_inventory: Decimal | None
) -> tuple[Decimal | None, str, str]:
    """`inventory_turnover` için ortalama stok. Bkz. `_average_or_ending_balance`."""

    return _average_or_ending_balance(current_inventory, prior_inventory)


def compute_average_trade_receivables(
    current: Decimal | None, prior: Decimal | None
) -> tuple[Decimal | None, str, str]:
    """`receivables_turnover` için ortalama ticari alacaklar."""

    return _average_or_ending_balance(current, prior)


def compute_average_trade_payables(
    current: Decimal | None, prior: Decimal | None
) -> tuple[Decimal | None, str, str]:
    """`payables_turnover` için ortalama ticari borçlar."""

    return _average_or_ending_balance(current, prior)


def compute_average_total_assets(
    current: Decimal | None, prior: Decimal | None
) -> tuple[Decimal | None, str, str]:
    """
    `return_on_assets` VE `asset_turnover` tarafından PAYLAŞILAN ortalama
    toplam aktif -- Bölüm 8 "average hesaplarının tutarsızlığı" riskinin
    giderilmesi için TEK üretim noktası; iki oran da AYNI facts-dict
    anahtarından (`average_total_assets`) okumalıdır, kendi hesaplarını
    YAPMAMALIDIR.
    """

    return _average_or_ending_balance(current, prior)


def compute_average_equity(
    current: Decimal | None, prior: Decimal | None
) -> tuple[Decimal | None, str, str]:
    """`return_on_equity` için ortalama özkaynak."""

    return _average_or_ending_balance(current, prior)


def compute_average_working_capital(
    current_net_working_capital: Decimal | None,
    prior_net_working_capital: Decimal | None,
) -> tuple[Decimal | None, str, str]:
    """
    Milestone 4.3B: hiçbir kayıtlı oran tarafından ZORUNLU tüketilmiyor
    (katalogdaki working_capital_turnover BİLİNÇLİ OLARAK dönem-sonu
    net_working_capital kullanıyor) -- gelecekteki bir "ortalama işletme
    sermayesi devir hızı" varyantı için hazır altyapı olarak tasarlandı.
    """

    return _average_or_ending_balance(current_net_working_capital, prior_net_working_capital)


def compute_quick_assets(
    current_assets: Decimal | None, inventory: Decimal | None
) -> Decimal | None:
    """
    `quick_ratio` için saf ara büyüklük: `quick_assets = current_assets -
    inventory`. Kullanıcıya doğrudan bir "oran" olarak SUNULMAZ (Bölüm 5.3
    kuralı). İkisinden biri `None` ise sonuç `None`'dır (yalnızca direct
    BS'de `inventory` doludur -- bkz. `RatioFormulaMetadata.
    direct_document_only_fields`).
    """

    if current_assets is None or inventory is None:
        return None
    return current_assets - inventory


def compute_capital_employed(
    total_assets: Decimal | None, short_term_liabilities: Decimal | None
) -> Decimal | None:
    """
    `return_on_capital_employed` için saf ara büyüklük: `capital_employed =
    total_assets - short_term_liabilities`. Kullanıcıya doğrudan bir "oran"
    olarak SUNULMAZ (Bölüm 5.3 kuralı). İkisinden biri `None` ise sonuç
    `None`'dır.
    """

    if total_assets is None or short_term_liabilities is None:
        return None
    return total_assets - short_term_liabilities


def compute_tax_expense(
    profit_before_tax: Decimal | None, net_profit: Decimal | None
) -> Decimal | None:
    """
    `effective_tax_rate` için saf ara büyüklük: `tax_expense =
    profit_before_tax - net_profit`. Kullanıcıya doğrudan bir "oran"
    olarak SUNULMAZ (Bölüm 5.3 kuralı) -- yalnızca `effective_tax_rate`'in
    `sum_division` formülünün numerator'ı için facts dict'e enjekte edilir.
    İkisinden biri `None` ise sonuç `None`'dır.
    """

    if profit_before_tax is None or net_profit is None:
        return None
    return profit_before_tax - net_profit


def compute_invested_capital(
    equity: Decimal | None, long_term_liabilities: Decimal | None
) -> Decimal | None:
    """
    `return_on_invested_capital` için saf ara büyüklük: `invested_capital =
    equity + long_term_liabilities`. Kullanıcıya doğrudan sunulmayan bir
    ara bileşendir (Bölüm 5.3 kuralı). İkisinden biri `None` ise sonuç
    `None`'dır.
    """

    if equity is None or long_term_liabilities is None:
        return None
    return equity + long_term_liabilities
