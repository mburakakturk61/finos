"""
Milestone 4.1 (Analysis Foundation) / Milestone 4.3A (Ratio Calculation
Foundation): Financial Ratio Engine'in (Milestone 4.3) TEK formül ve
explainability kaynağı.

Milestone 4.1'de bu dosya BİLİNÇLİ OLARAK boş bırakılmıştı (bkz. git
geçmişi). Milestone 4.3A'da (onaylanan mimari doküman
docs/FINOS_MILESTONE_4_3_FINANCIAL_RATIO_ENGINE_DESIGN.md, Bölüm R/S) artık
BOŞ DEĞİL -- ilk 9 ortak oran (Balance Sheet/Income Statement motorlarının
bugüne kadar KENDİ Decimal aritmetiğiyle hesapladığı current_ratio/
debt_ratio/equity_ratio/debt_to_equity/net_working_capital/
working_capital_ratio/gross_profit_margin/operating_profit_margin/
net_profit_margin) burada KAYITLIDIR ve BS/IS analyzer'ları artık kendi
aritmetiğini YAPMAZ, `compute_registered_ratio()`'ya yönlendirilir
(onaylanan Milestone 4.3A kararı #2 -- "her formül yalnızca RATIO_REGISTRY'de
bir kez tanımlanmalı, BS/IS motorlarında bağımsız ikinci bir aritmetik
formül kalmamalı").

Calculation Strategy sistemi (onaylanan Milestone 4.3A kararı #1): eval,
exec, dinamik expression veya kullanıcı girdisinden kod üretimi KESİNLİKLE
YASAK. Her `RatioFormulaMetadata.calculation_strategy` değeri,
`CALCULATION_STRATEGIES` sözlüğünde kayıtlı, KAPALI bir kümeden, saf ve
tek başına test edilebilir bir Python fonksiyonuna karşılık gelir.
Milestone 4.3A yalnızca iki strateji tanımlar: `"sum_division"` (alan(lar)ı
toplar, böler) ve `"linear_combination"` (alan(lar)ı toplar/çıkarır, bölme
yok). Gelecekteki stratejiler (ortalama bakiye, gün dönüşümü, oran-oranı,
boolean/kategorik sonuç -- Milestone 4.3B+) yalnızca isim olarak mimari
dokümanda kayıt altına alınmıştır, burada implemente EDİLMEMİŞTİR.

Computation Status sözleşmesi (onaylanan Milestone 4.3A kararı #2): `None`
girdi (`missing_input`) ile GERÇEK sıfır payda (`undefined_zero_denominator`/
`no_obligation`) KESİNLİKLE aynı sonuç olarak ele alınmaz. Hiçbir hesaplama
yapay `Infinity`/`NaN` üretmez -- tanımsız/eksik/no-obligation durumlarının
HEPSİNDE `value=None`, iş anlamı yalnızca `status` (ve gerekirse
`warnings`) üzerinden taşınır.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import enum
from typing import Any, Callable

from app.engines.common.calculation_provenance import ProvenanceEntry


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

    DEĞİŞMEDİ (Milestone 4.1'den beri) -- `compute_sum_division` bu
    fonksiyonun davranışını BİREBİR yeniden üretir (bkz. o fonksiyonun
    docstring'i), ama BS/IS motorları artık bu fonksiyonu DOĞRUDAN
    RATIO_REGISTRY'ye kayıtlı 9 oran için ÇAĞIRMIYOR -- yalnızca henüz
    registry'de olmayan (ebit_margin_pct/ebitda_margin_pct gibi) yerel
    hesaplamalar için kullanılmaya devam ediyor.
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


def json_safe_to_decimal(value: float | int | None) -> Decimal | None:
    """
    Milestone 4.3A: `decimal_to_json_safe`'in TERSİ -- Financial Ratio
    Engine'in başka bir motorun ZATEN KAYITLI/serileştirilmiş
    `result_json["facts"]`'ını (JSON-güvenli float) okuyup yeniden Decimal
    aritmetiğine sokması için gereklidir (Ratio Engine kendisi hiçbir belge
    ayrıştırmaz, yalnızca başka analiz sonuçlarını okur -- mimari doküman
    Bölüm B.3). `str(value)` üzerinden dönüştürülür -- doğrudan
    `Decimal(float)` ikili kayan-nokta hassasiyet hatalarını miras alır,
    `Decimal(str(value))` almaz. `None` girişte `None` döner.
    """

    if value is None:
        return None
    return Decimal(str(value))


class ComputationStatus(str, enum.Enum):
    """
    Milestone 4.3A (onaylanan mimari doküman kararı #2): bir oranın
    hesaplanıp hesaplanamadığını VE hesaplanamama NEDENİNİ ayırt eden
    sözleşme. `None` girdi (eksik veri) ile GERÇEK sıfır payda (tanımlı bir
    sayısal değer) KESİNLİKLE karıştırılmaz.

    CALCULATED: değer başarıyla hesaplandı, `value` doludur.
    MISSING_INPUT: gerekli alanlardan en az biri `None` -- veri eksik.
    UNDEFINED_ZERO_DENOMINATOR: tüm girdiler doluydu ama payda GERÇEKTEN 0
        ve bu, ilgili oran için tanımlı bir iş anlamı TAŞIMIYOR (matematiksel
        olarak tanımsız, ör. debt_to_equity için equity=0) -- yüksek önemli
        bir warning eşlik eder.
    NO_OBLIGATION: payda GERÇEKTEN 0 ve bu, ilgili oran için AÇIK, olumlu/
        nötr bir iş durumunu ifade ediyor (ör. current_ratio için
        short_term_liabilities=0 -- "kısa vadeli borç yok"). Değer yine
        `None`'dır (0'a bölme yapılmaz), yalnızca durum ayrıdır.
    NOT_APPLICABLE: formül, mevcut kaynak/bağlam için yapısal olarak hiç
        uygulanamaz (ör. quick_ratio, trial_balance_derived modda -- mizan
        motoru inventory'yi hiçbir zaman üretmez). Milestone 4.3A'nın 9
        oranı bu durumu HİÇ tetiklemez (hepsi her modda yapısal olarak
        uygulanabilir); gelecekteki oranlar için kayıt altına alınmıştır.
    NOT_CALCULABLE: formülün ihtiyaç duyduğu alan hiçbir motorda/
        canonical_facts'te tanımlı değil (katalogdaki ~15 "girdisi hiç yok"
        oranı), ya da desteklenmeyen/bilinmeyen bir calculation_strategy
        (kontrollü domain hatası -- exception fırlatılmaz).
    """

    CALCULATED = "calculated"
    MISSING_INPUT = "missing_input"
    UNDEFINED_ZERO_DENOMINATOR = "undefined_zero_denominator"
    NO_OBLIGATION = "no_obligation"
    NOT_APPLICABLE = "not_applicable"
    NOT_CALCULABLE = "not_calculable"


@dataclass(frozen=True)
class ComputationOutcome:
    """
    Bir hesaplama stratejisi çağrısının VEYA `compute_registered_ratio()`
    çağrısının TAM sonucu -- `status`, `value`, `missing_inputs`,
    `warnings`, `reliability` ve `provenance` HER ZAMAN birlikte, tutarlı
    biçimde üretilir (onaylanan Milestone 4.3A kararı #3). `value` yalnızca
    `status=CALCULATED` iken doludur; diğer TÜM durumlarda `None`'dır --
    asla `Decimal("Infinity")`/`NaN` üretilmez.

    `provenance`, strateji fonksiyonları (`compute_sum_division`/
    `compute_linear_combination`) tarafından DOLDURULMAZ (henüz hangi
    `RatioFormulaMetadata.key`'e ait olduklarını bilmiyorlar) -- yalnızca
    `compute_registered_ratio()` tarafından, strateji sonucu üzerine
    eklenerek doldurulur.
    """

    status: ComputationStatus
    value: Decimal | None
    missing_inputs: tuple[str, ...] = ()
    warnings: tuple[dict[str, Any], ...] = ()
    reliability: str = "not_calculable"
    provenance: ProvenanceEntry | None = None


@dataclass(frozen=True)
class RatioFormulaMetadata:
    """
    Bir oran formülünün kimliği ve veri sözleşmesi.

    `calculation_strategy`: `CALCULATION_STRATEGIES` sözlüğündeki bir
    anahtar -- hangi SAF fonksiyonun bu formülü hesaplayacağını belirler.
    `numerator_fields`/`denominator_fields`: yalnızca `"sum_division"`
    stratejisi tarafından okunur (toplanıp bölünür). `addend_fields`/
    `subtrahend_fields`: yalnızca `"linear_combination"` stratejisi
    tarafından okunur (toplanıp çıkarılır). Her strateji yalnızca kendi
    ilgili alanlarını okur -- birkaç kullanılmayan alan pahasına (kabul
    edilen basitlik ödünleşimi), `Union`/discriminated-type karmaşıklığı
    olmadan tip-güvenli bir tasarım.

    `zero_denominator_status`: yalnızca `"sum_division"` için anlamlıdır --
    payda GERÇEKTEN 0 olduğunda hangi `ComputationStatus`'un
    kullanılacağını belirler (`UNDEFINED_ZERO_DENOMINATOR` varsayılan;
    `NO_OBLIGATION`, sıfır paydanın iş anlamı olarak olumlu/nötr olduğu
    oranlar için AÇIKÇA atanır -- bkz. modülün alt kısmındaki kayıtlar).
    """

    key: str
    category: str
    display_name_tr: str
    unit: str  # "ratio" | "percentage" | "days" | "currency"
    calculation_strategy: str
    numerator_fields: tuple[str, ...] = ()
    denominator_fields: tuple[str, ...] = ()
    addend_fields: tuple[str, ...] = ()
    subtrahend_fields: tuple[str, ...] = ()
    zero_denominator_status: ComputationStatus = ComputationStatus.UNDEFINED_ZERO_DENOMINATOR
    quantize_exp: str = "0.0001"

    # --- Milestone 4.3B: additive, geriye uyumlu (varsayılan değerli) ----
    # alanlar (onaylanan 4.3B tasarım dokümanı, Bölüm 5, 2. tur onay).
    #
    # `depends_on_ratios`: yalnızca `"sum_division"`/`"linear_combination"`
    # tarafından, SIRADAN bir facts-alanı gibi okunur -- bu oranın hangi
    # BAŞKA RATIO_REGISTRY anahtarlarının ZATEN HESAPLANMIŞ değerine
    # ihtiyaç duyduğunu belirtir (ör. days_inventory_outstanding ->
    # inventory_turnover). Orkestrasyon (financial_ratios/service.py),
    # bağımlı oranı hesaplamadan ÖNCE bağımlılığın değerini facts dict'e
    # KENDİ key'iyle enjekte eder (Bölüm 3.2). `register_ratio_formula`,
    # buradaki her key'in kayıt ANINDA RATIO_REGISTRY'de zaten var
    # olduğunu doğrular -- döngüsel bağımlılık yapısal olarak imkansızdır.
    depends_on_ratios: tuple[str, ...] = ()

    # `current_field`/`prior_field`: yalnızca `"growth_rate"` stratejisi
    # tarafından okunur (Bölüm 3.3).
    current_field: str | None = None
    prior_field: str | None = None

    # `scale_field`: yalnızca `"scaled_division"` stratejisi tarafından
    # okunur (Bölüm 3.4, 2. tur onay karar #1).
    scale_field: str | None = None

    # `engine_dependency`: bu oranın ihtiyaç duyduğu bir motorun adı (ör.
    # "cash_flow") -- `EngineRunContext`'te bu motorun sonucu YOKSA,
    # orkestrasyon `compute_registered_ratio`'yu HİÇ ÇAĞIRMADAN doğrudan
    # NOT_CALCULABLE üretir (2. tur onay karar #3, Bölüm 5.5). `None` ise
    # bu kontrol hiç uygulanmaz (4.3A'nın 9 oranı gibi).
    engine_dependency: str | None = None

    # `direct_document_only_fields`: bu formülün kullandığı, yalnızca
    # `source_mode="direct_document"` iken GERÇEKTEN dolu olabilen alanlar
    # (ör. quick_ratio -> ("inventory",)). Orkestrasyon, ilgili BS/IS
    # sonucunun `source_mode`'u farklıysa `compute_registered_ratio`'yu HİÇ
    # ÇAĞIRMADAN doğrudan NOT_APPLICABLE üretir (Bölüm 6).
    direct_document_only_fields: tuple[str, ...] = ()


RATIO_REGISTRY: dict[str, RatioFormulaMetadata] = {}
RATIO_REGISTRY_VERSION = "1.1.0"
# Milestone 4.3B: RatioFormulaMetadata'nın şekli değişti (yukarıdaki 6 yeni
# additive alan + growth_rate/scaled_division stratejileri) -- J.2'deki
# cache-anahtarı tasarımının gerektirdiği disiplinle "1.0.0" -> "1.1.0"
# yükseltildi.


def _resolve_fields(
    fields: tuple[str, ...], facts: dict[str, "Decimal | None"]
) -> tuple[Decimal | None, tuple[str, ...]]:
    """
    Alan listesini toplar; herhangi biri `facts`'te `None` ya da hiç yoksa
    toplam `None` döner, eksik alan adları ayrıca raporlanır (kısmi toplam
    -- bilinmeyen bir bileşeni 0 sayarak -- ASLA üretilmez).
    """

    missing: list[str] = []
    total = Decimal("0")
    for field_name in fields:
        value = facts.get(field_name)
        if value is None:
            missing.append(field_name)
            continue
        total += value
    if missing:
        return None, tuple(missing)
    return total, ()


def _zero_denominator_warning(metadata: "RatioFormulaMetadata") -> tuple[dict[str, Any], ...]:
    if metadata.zero_denominator_status == ComputationStatus.UNDEFINED_ZERO_DENOMINATOR:
        return (
            {
                "code": "UNDEFINED_ZERO_DENOMINATOR",
                "severity": "high",
                "message": (
                    f"'{metadata.key}' için payda gerçekten sıfır ve bu, "
                    "matematiksel olarak tanımsız bir durumdur (eksik veri "
                    "değildir)."
                ),
            },
        )
    return ()


def compute_sum_division(
    metadata: RatioFormulaMetadata, facts: dict[str, Decimal | None]
) -> ComputationOutcome:
    """
    `"sum_division"` stratejisi: `value = sum(numerator_fields) /
    sum(denominator_fields)`. `safe_divide`'ın Decimal-güvenli quantize
    davranışını (ROUND_HALF_UP, `metadata.quantize_exp`) BİREBİR korur --
    Milestone 4.2'nin BS/IS motorlarının ürettiği sayısal değerlerle
    bit-bir aynı sonucu üretmesi gerekir (mimari doküman D.3 invariant'ı).
    `unit="percentage"` ise quantize SONRASI 100 ile çarpılır (eski
    `_pct()` deseninin birebir sırası).

    Hiçbir ham Decimal exception dışarı sızmaz (onaylanan Milestone 4.3A
    kararı #4) -- beklenmeyen bir sayısal hata kontrollü `NOT_CALCULABLE`
    + tanılama warning'ine dönüştürülür.
    """

    try:
        numerator, num_missing = _resolve_fields(metadata.numerator_fields, facts)
        denominator, den_missing = _resolve_fields(metadata.denominator_fields, facts)
        missing = num_missing + den_missing
        if missing:
            return ComputationOutcome(
                status=ComputationStatus.MISSING_INPUT,
                value=None,
                missing_inputs=missing,
            )

        if denominator == 0:
            return ComputationOutcome(
                status=metadata.zero_denominator_status,
                value=None,
                warnings=_zero_denominator_warning(metadata),
            )

        quantized = (numerator / denominator).quantize(
            Decimal(metadata.quantize_exp), rounding=ROUND_HALF_UP
        )
        value = quantized * Decimal("100") if metadata.unit == "percentage" else quantized

        return ComputationOutcome(status=ComputationStatus.CALCULATED, value=value)
    except (InvalidOperation, OverflowError, ArithmeticError) as error:
        return ComputationOutcome(
            status=ComputationStatus.NOT_CALCULABLE,
            value=None,
            warnings=(
                {
                    "code": "CALCULATION_STRATEGY_INTERNAL_ERROR",
                    "severity": "high",
                    "message": (
                        f"'{metadata.key}' hesaplanırken beklenmeyen bir "
                        f"sayısal hata oluştu: {error}"
                    ),
                },
            ),
        )


def compute_linear_combination(
    metadata: RatioFormulaMetadata, facts: dict[str, Decimal | None]
) -> ComputationOutcome:
    """
    `"linear_combination"` stratejisi: `value = sum(addend_fields) -
    sum(subtrahend_fields)`. Bölme/payda kavramı YOK -- `zero_denominator_
    status` bu strateji için hiç okunmaz. Sonuç QUANTIZE EDİLMEZ (eski
    `net_working_capital` davranışıyla birebir tutarlı -- "currency" birimi
    hiç yuvarlanmaz, kaynak tutarların doğal hassasiyetinde kalır).
    """

    try:
        addends, add_missing = _resolve_fields(metadata.addend_fields, facts)
        subtrahends, sub_missing = _resolve_fields(metadata.subtrahend_fields, facts)
        missing = add_missing + sub_missing
        if missing:
            return ComputationOutcome(
                status=ComputationStatus.MISSING_INPUT,
                value=None,
                missing_inputs=missing,
            )

        value = addends - subtrahends
        return ComputationOutcome(status=ComputationStatus.CALCULATED, value=value)
    except (InvalidOperation, OverflowError, ArithmeticError) as error:
        return ComputationOutcome(
            status=ComputationStatus.NOT_CALCULABLE,
            value=None,
            warnings=(
                {
                    "code": "CALCULATION_STRATEGY_INTERNAL_ERROR",
                    "severity": "high",
                    "message": (
                        f"'{metadata.key}' hesaplanırken beklenmeyen bir "
                        f"sayısal hata oluştu: {error}"
                    ),
                },
            ),
        )


def compute_growth_rate(
    metadata: RatioFormulaMetadata, facts: dict[str, Decimal | None]
) -> ComputationOutcome:
    """
    `"growth_rate"` stratejisi (Milestone 4.3B, onaylanan tasarım Bölüm 3.3):
    `value = (current - prior) / abs(prior) * 100`. Yalnızca
    `current_field`/`prior_field` okunur -- `numerator_fields`/
    `denominator_fields` bu strateji için hiç kullanılmaz.

    `prior == 0` -> `UNDEFINED_ZERO_DENOMINATOR` (NO_OBLIGATION DEĞİL --
    "büyüme yok" ile "geçen dönem sıfırdı" karıştırılmaz, onaylanan
    tasarım kararı). Hiçbir ham Decimal exception dışarı sızmaz.
    """

    try:
        if metadata.current_field is None or metadata.prior_field is None:
            return ComputationOutcome(
                status=ComputationStatus.NOT_CALCULABLE,
                value=None,
                warnings=(
                    {
                        "code": "GROWTH_RATE_FIELD_CONFIG_MISSING",
                        "severity": "high",
                        "message": (
                            f"'{metadata.key}' için current_field/prior_field "
                            "tanımlı değil (metadata hatası)."
                        ),
                    },
                ),
            )

        current = facts.get(metadata.current_field)
        prior = facts.get(metadata.prior_field)

        missing: list[str] = []
        if current is None:
            missing.append(metadata.current_field)
        if prior is None:
            missing.append(metadata.prior_field)
        if missing:
            return ComputationOutcome(
                status=ComputationStatus.MISSING_INPUT,
                value=None,
                missing_inputs=tuple(missing),
            )

        if prior == 0:
            return ComputationOutcome(
                status=ComputationStatus.UNDEFINED_ZERO_DENOMINATOR,
                value=None,
                warnings=(
                    {
                        "code": "UNDEFINED_ZERO_DENOMINATOR",
                        "severity": "high",
                        "message": (
                            f"'{metadata.key}' için önceki dönem değeri "
                            "gerçekten sıfır; büyüme oranı sıfırdan "
                            "tanımsızdır (eksik veri değildir)."
                        ),
                    },
                ),
            )

        quantized = ((current - prior) / abs(prior)).quantize(
            Decimal(metadata.quantize_exp), rounding=ROUND_HALF_UP
        )
        value = quantized * Decimal("100")
        return ComputationOutcome(status=ComputationStatus.CALCULATED, value=value)
    except (InvalidOperation, OverflowError, ArithmeticError) as error:
        return ComputationOutcome(
            status=ComputationStatus.NOT_CALCULABLE,
            value=None,
            warnings=(
                {
                    "code": "CALCULATION_STRATEGY_INTERNAL_ERROR",
                    "severity": "high",
                    "message": (
                        f"'{metadata.key}' hesaplanırken beklenmeyen bir "
                        f"sayısal hata oluştu: {error}"
                    ),
                },
            ),
        )


def compute_scaled_division(
    metadata: RatioFormulaMetadata, facts: dict[str, Decimal | None]
) -> ComputationOutcome:
    """
    `"scaled_division"` stratejisi (Milestone 4.3B, 2. tur onay karar #1):
    `value = (sum(numerator_fields) / sum(denominator_fields)) *
    scale_field`. `defensive_interval_ratio` gibi "oran x gün/katsayı"
    formülleri için -- eval/exec/expression parser YOK, yalnızca açıkça
    kayıtlı metadata alanlarını okuyan saf bir fonksiyon.
    """

    try:
        numerator, num_missing = _resolve_fields(metadata.numerator_fields, facts)
        denominator, den_missing = _resolve_fields(metadata.denominator_fields, facts)
        missing = list(num_missing) + list(den_missing)

        scale_value: Decimal | None = None
        if metadata.scale_field is None:
            return ComputationOutcome(
                status=ComputationStatus.NOT_CALCULABLE,
                value=None,
                warnings=(
                    {
                        "code": "SCALED_DIVISION_FIELD_CONFIG_MISSING",
                        "severity": "high",
                        "message": (
                            f"'{metadata.key}' için scale_field tanımlı "
                            "değil (metadata hatası)."
                        ),
                    },
                ),
            )
        scale_value = facts.get(metadata.scale_field)
        if scale_value is None:
            missing.append(metadata.scale_field)

        if missing:
            return ComputationOutcome(
                status=ComputationStatus.MISSING_INPUT,
                value=None,
                missing_inputs=tuple(missing),
            )

        if denominator == 0:
            return ComputationOutcome(
                status=metadata.zero_denominator_status,
                value=None,
                warnings=_zero_denominator_warning(metadata),
            )

        raw = (numerator / denominator) * scale_value
        quantized = raw.quantize(Decimal(metadata.quantize_exp), rounding=ROUND_HALF_UP)
        # sum_division ile TUTARLI davranış: unit="percentage" ise quantize
        # SONRASI 100 ile çarpılır (ör. return_on_invested_capital).
        value = quantized * Decimal("100") if metadata.unit == "percentage" else quantized
        return ComputationOutcome(status=ComputationStatus.CALCULATED, value=value)
    except (InvalidOperation, OverflowError, ArithmeticError) as error:
        return ComputationOutcome(
            status=ComputationStatus.NOT_CALCULABLE,
            value=None,
            warnings=(
                {
                    "code": "CALCULATION_STRATEGY_INTERNAL_ERROR",
                    "severity": "high",
                    "message": (
                        f"'{metadata.key}' hesaplanırken beklenmeyen bir "
                        f"sayısal hata oluştu: {error}"
                    ),
                },
            ),
        )


# Milestone 4.3A: KAPALI strateji kümesi -- eval/exec/dinamik expression
# YOK. Milestone 4.3B (onaylanan tasarım Bölüm 3): `average_balance_
# division`/`ratio_of_ratio`/`boolean_threshold` GEREKSİZ bulundu (mevcut
# stratejiler + `depends_on_ratios` orkestrasyonu yeterli) -- yalnızca
# `growth_rate` ve `scaled_division` GERÇEKTEN gerekli bulunup eklendi.
CALCULATION_STRATEGIES: dict[
    str, Callable[[RatioFormulaMetadata, dict[str, Decimal | None]], ComputationOutcome]
] = {
    "sum_division": compute_sum_division,
    "linear_combination": compute_linear_combination,
    "growth_rate": compute_growth_rate,
    "scaled_division": compute_scaled_division,
}


def register_ratio_formula(metadata: RatioFormulaMetadata) -> None:
    """
    Bir oran formülü üstverisini RATIO_REGISTRY'ye ekler. Aynı `key` ile
    ikinci kez kayıt denemesi hatadır -- sessiz üzerine yazma yok.
    Milestone 4.3A: `calculation_strategy`'nin `CALCULATION_STRATEGIES`'te
    GERÇEKTEN kayıtlı olduğu da kayıt ANINDA doğrulanır -- desteklenmeyen
    bir strateji ile kayıt denemesi de erken, kontrollü bir `ValueError`
    ile reddedilir (kayıt sonrası çalışma zamanında sessizce `not_calculable`
    dönmek yerine, geliştirme zamanında YAKALANIR).
    """

    if metadata.key in RATIO_REGISTRY:
        raise ValueError(f"Oran formülü zaten kayıtlı: {metadata.key!r}")
    if metadata.calculation_strategy not in CALCULATION_STRATEGIES:
        raise ValueError(
            f"Bilinmeyen calculation_strategy: {metadata.calculation_strategy!r} "
            f"(oran: {metadata.key!r}). CALCULATION_STRATEGIES'de kayıtlı olmalı."
        )
    # Milestone 4.3B (onaylanan tasarım Bölüm 5.1): `depends_on_ratios`'taki
    # her key, kayıt ANINDA RATIO_REGISTRY'de ZATEN var olmalı --
    # bağımlılıklar kendilerinden SONRA tanımlanan bir orana işaret edemez.
    # Bu, modül-seviyesi kayıt sırasını bir topolojik sıralamaya zorlar;
    # döngüsel bağımlılık yapısal olarak İMKANSIZDIR.
    for dependency_key in metadata.depends_on_ratios:
        if dependency_key not in RATIO_REGISTRY:
            raise ValueError(
                f"'{metadata.key}' oranı, henüz kayıtlı olmayan "
                f"'{dependency_key}' oranına bağımlı (depends_on_ratios). "
                "Bağımlılıklar KENDİLERİNDEN ÖNCE kayıtlı olmalı."
            )
    RATIO_REGISTRY[metadata.key] = metadata


def get_ratio_formula(key: str) -> RatioFormulaMetadata | None:
    return RATIO_REGISTRY.get(key)


def list_ratio_formulas_by_category(category: str) -> list[RatioFormulaMetadata]:
    return [
        metadata
        for metadata in RATIO_REGISTRY.values()
        if metadata.category == category
    ]


def _join_terms(fields: tuple[str, ...]) -> str:
    if len(fields) == 1:
        return fields[0]
    return "(" + " + ".join(fields) + ")"


def _build_derivation_rule(metadata: RatioFormulaMetadata) -> str:
    if metadata.calculation_strategy == "sum_division":
        rule = f"{_join_terms(metadata.numerator_fields)} / {_join_terms(metadata.denominator_fields)}"
        if metadata.unit == "percentage":
            rule += " * 100"
        return rule
    if metadata.calculation_strategy == "linear_combination":
        parts: list[str] = []
        for index, field_name in enumerate(metadata.addend_fields):
            parts.append(field_name if index == 0 else f"+ {field_name}")
        for field_name in metadata.subtrahend_fields:
            parts.append(f"- {field_name}")
        return " ".join(parts) if parts else "(tanımsız)"
    if metadata.calculation_strategy == "growth_rate":
        return (
            f"({metadata.current_field} - {metadata.prior_field}) / "
            f"abs({metadata.prior_field}) * 100"
        )
    if metadata.calculation_strategy == "scaled_division":
        return (
            f"{_join_terms(metadata.numerator_fields)} / "
            f"{_join_terms(metadata.denominator_fields)} * {metadata.scale_field}"
        )
    return f"(bilinmeyen strateji: {metadata.calculation_strategy})"


def compute_registered_ratio(
    key: str,
    facts: dict[str, Decimal | None],
    *,
    reliability: str = "high",
) -> ComputationOutcome:
    """
    Mimari doküman D.2 Karar 4 / Bölüm R.1'in somutlaşmış hali -- BS/IS
    motorlarının ve (ileride) Financial Ratio Engine'in TEK giriş noktası.
    `RATIO_REGISTRY[key]`'i okur, `CALCULATION_STRATEGIES`'ten ilgili SAF
    fonksiyonu çağırır, `ProvenanceEntry`'yi AYNI çağrıda üretir -- Decimal
    aritmetiği hiçbir çağıran motorda TEKRAR yazılmaz.

    `reliability`: yalnızca `status=CALCULATED` iken `ComputationOutcome.
    reliability`'ye yazılır (çağıran, kaynak önceliğine göre "high"/
    "medium"/"medium_low" geçebilir) -- hesaplanamayan durumlarda HER ZAMAN
    "not_calculable"'a sabitlenir (bir değeri olmayan bir şeyin
    "güvenilirliği" olmaz).

    `key` RATIO_REGISTRY'de yoksa VEYA kayıtlı `calculation_strategy`
    (teorik olarak, `register_ratio_formula` bunu zaten engellese de)
    `CALCULATION_STRATEGIES`'te bulunamazsa: kontrollü `NOT_CALCULABLE`
    döner, ASLA exception fırlatmaz/eval denemez.
    """

    metadata = RATIO_REGISTRY.get(key)
    if metadata is None:
        return ComputationOutcome(
            status=ComputationStatus.NOT_CALCULABLE,
            value=None,
            reliability="not_calculable",
            warnings=(
                {
                    "code": "RATIO_NOT_REGISTERED",
                    "severity": "high",
                    "message": f"'{key}' RATIO_REGISTRY'de kayıtlı değil.",
                },
            ),
            provenance=ProvenanceEntry(
                metric=key,
                derivation_rule="RATIO_REGISTRY'de kayıtlı değil",
                input_fields=(),
                missing_inputs=(),
                calculated=False,
                reliability="not_calculable",
            ),
        )

    strategy_fn = CALCULATION_STRATEGIES.get(metadata.calculation_strategy)
    if strategy_fn is None:
        outcome = ComputationOutcome(
            status=ComputationStatus.NOT_CALCULABLE,
            value=None,
            warnings=(
                {
                    "code": "UNSUPPORTED_CALCULATION_STRATEGY",
                    "severity": "high",
                    "message": (
                        f"'{metadata.calculation_strategy}' stratejisi kayıtlı "
                        f"değil (oran: {key!r})."
                    ),
                },
            ),
        )
    else:
        outcome = strategy_fn(metadata, facts)

    final_reliability = (
        reliability if outcome.status == ComputationStatus.CALCULATED else "not_calculable"
    )

    extra_fields: tuple[str, ...] = ()
    if metadata.current_field:
        extra_fields += (metadata.current_field,)
    if metadata.prior_field:
        extra_fields += (metadata.prior_field,)
    if metadata.scale_field:
        extra_fields += (metadata.scale_field,)
    # Milestone 4.3B: `depends_on_ratios`'taki key'ler de provenance'ın
    # `input_fields`'ına eklenir -- bağımlı bir oranın ZİNCİRİNİ takip
    # etmek isteyen bir kullanıcı en azından ADI görebilir (Bölüm 8
    # "provenance bozulması" riskinin kısmi azaltımı).
    extra_fields += metadata.depends_on_ratios

    all_input_fields = (
        metadata.numerator_fields
        + metadata.denominator_fields
        + metadata.addend_fields
        + metadata.subtrahend_fields
        + extra_fields
    )
    rounding_applied = (
        f"quantize({metadata.quantize_exp}, ROUND_HALF_UP)"
        if metadata.calculation_strategy
        in ("sum_division", "growth_rate", "scaled_division")
        else "yuvarlama yok (linear_combination)"
    )

    provenance = ProvenanceEntry(
        metric=key,
        derivation_rule=_build_derivation_rule(metadata),
        input_fields=all_input_fields,
        missing_inputs=outcome.missing_inputs,
        calculated=outcome.status == ComputationStatus.CALCULATED,
        reliability=final_reliability,
        rounding_applied=rounding_applied,
    )

    return ComputationOutcome(
        status=outcome.status,
        value=outcome.value,
        missing_inputs=outcome.missing_inputs,
        warnings=outcome.warnings,
        reliability=final_reliability,
        provenance=provenance,
    )


# --- Milestone 4.3A: ilk 9 ortak oranın kaydı --------------------------
# (onaylanan mimari doküman, Bölüm R.5/S) -- BS/IS motorlarının bugüne
# kadar KENDİ hesapladığı 9 oran, artık TEK kaynak burasıdır.

register_ratio_formula(
    RatioFormulaMetadata(
        key="current_ratio",
        category="liquidity",
        display_name_tr="Cari Oran",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("current_assets",),
        denominator_fields=("short_term_liabilities",),
        zero_denominator_status=ComputationStatus.NO_OBLIGATION,
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="working_capital_ratio",
        category="liquidity",
        display_name_tr="İşletme Sermayesi Oranı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("current_assets",),
        denominator_fields=("short_term_liabilities",),
        zero_denominator_status=ComputationStatus.NO_OBLIGATION,
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="net_working_capital",
        category="liquidity",
        display_name_tr="Net İşletme Sermayesi",
        unit="currency",
        calculation_strategy="linear_combination",
        addend_fields=("current_assets",),
        subtrahend_fields=("short_term_liabilities",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="debt_ratio",
        category="leverage",
        display_name_tr="Borç Oranı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("total_liabilities",),
        denominator_fields=("total_assets",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="equity_ratio",
        category="leverage",
        display_name_tr="Özkaynak Oranı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("equity",),
        denominator_fields=("total_assets",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="debt_to_equity",
        category="leverage",
        display_name_tr="Borç/Özkaynak Oranı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("total_liabilities",),
        denominator_fields=("equity",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="gross_profit_margin",
        category="profitability",
        display_name_tr="Brüt Kâr Marjı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("gross_profit",),
        denominator_fields=("net_sales",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="operating_profit_margin",
        category="profitability",
        display_name_tr="Faaliyet Kâr Marjı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("operating_profit",),
        denominator_fields=("net_sales",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="net_profit_margin",
        category="profitability",
        display_name_tr="Net Kâr Marjı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("net_profit",),
        denominator_fields=("net_sales",),
    )
)

# --- Milestone 4.3B / Step 3: Likidite + Borçluluk'un kalan oranları -------
# (onaylanan 4.3B tasarım dokümanı Bölüm 2.1/2.3/3.4, 2. tur onay kararları
# #1/#2). Bağımlılığı OLMAYAN 9 oran -- average_*/depends_on_ratios
# gerektirmiyor.

register_ratio_formula(
    RatioFormulaMetadata(
        key="quick_ratio",
        category="liquidity",
        display_name_tr="Asit-Test Oranı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("quick_assets",),
        denominator_fields=("short_term_liabilities",),
        zero_denominator_status=ComputationStatus.NO_OBLIGATION,
        direct_document_only_fields=("inventory",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="cash_ratio",
        category="liquidity",
        display_name_tr="Nakit Oranı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("cash_and_equivalents",),
        denominator_fields=("short_term_liabilities",),
        zero_denominator_status=ComputationStatus.NO_OBLIGATION,
        direct_document_only_fields=("cash_and_equivalents",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="defensive_interval_ratio",
        category="liquidity",
        display_name_tr="Savunma Aralığı Oranı",
        unit="days",
        calculation_strategy="scaled_division",
        numerator_fields=("cash_and_equivalents", "trade_receivables"),
        denominator_fields=("operating_expenses", "cost_of_sales"),
        scale_field="days_in_period",
        direct_document_only_fields=("cash_and_equivalents", "trade_receivables"),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="long_term_debt_to_equity",
        category="leverage",
        display_name_tr="Uzun Vadeli Borç/Özkaynak",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("long_term_liabilities",),
        denominator_fields=("equity",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="short_term_debt_ratio",
        category="leverage",
        display_name_tr="Kısa Vadeli Borç Oranı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("short_term_liabilities",),
        denominator_fields=("total_liabilities",),
        # 2. tur onay karar #2: total_liabilities=0 -> NO_OBLIGATION,
        # value=None (sahte 0/Infinity ASLA üretilmez).
        zero_denominator_status=ComputationStatus.NO_OBLIGATION,
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="financial_leverage_multiplier",
        category="leverage",
        display_name_tr="Finansal Kaldıraç Çarpanı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("total_assets",),
        denominator_fields=("equity",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="interest_coverage_ratio",
        category="leverage",
        display_name_tr="Faiz Karşılama Oranı (EBIT)",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("ebit",),
        denominator_fields=("financing_expenses",),
        # finansman gideri=0 -> "karşılanacak bir şey yok" (olumlu iş
        # anlamı) -- NO_OBLIGATION, current_ratio'daki mantığın borç
        # servisi bağlamına genellenmiş hâli.
        zero_denominator_status=ComputationStatus.NO_OBLIGATION,
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="ebitda_coverage_ratio",
        category="leverage",
        display_name_tr="EBITDA ile Faiz Karşılama",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("ebitda",),
        denominator_fields=("financing_expenses",),
        zero_denominator_status=ComputationStatus.NO_OBLIGATION,
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="debt_to_ebitda",
        category="leverage",
        display_name_tr="Borç/EBITDA",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("total_liabilities",),
        denominator_fields=("ebitda",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="fixed_charge_coverage",
        category="leverage",
        display_name_tr="Sabit Ödeme Karşılama Oranı",
        unit="ratio",
        # Katalog/dokümantasyon amaçlı formül -- kiralama gideri
        # (lease_payments) ayrıştırması HİÇBİR motorda/canonical_facts'te
        # yok. Orkestrasyon (financial_ratios/service.py) bu oranı HER
        # ZAMAN, bu strateji hiç çağrılmadan, NOT_CALCULABLE olarak kısa
        # devre yaptırır (sustainable_growth_rate ile AYNI desen, bkz.
        # service.py::_fixed_charge_coverage_not_calculable_outcome).
        calculation_strategy="sum_division",
        numerator_fields=("ebit", "lease_payments"),
        denominator_fields=("financing_expenses", "lease_payments"),
    )
)

# --- Milestone 4.3B / Step 4: Kârlılık'ın kalan oranları + effective_tax_
# rate / ROIC düzeltmesi (onaylanan tasarım Bölüm 2.2/3.5, 2. tur onay
# karar #7). `effective_tax_rate` KENDİSİ kullanıcıya anlamlı, bağımsız bir
# metriktir (Bölüm 5.3 kuralı gereği RATIO_REGISTRY'de) -- kanuni vergi
# oranı ASLA varsayılmaz, yalnızca gerçek IS verisinden (profit_before_tax/
# net_profit) türetilir. `return_on_invested_capital`, `effective_tax_rate`e
# `depends_on_ratios` ile bağlanır; scaled_division stratejisi
# `(ebit/invested_capital) * (1-effective_tax_rate)` şeklinde matematiksel
# olarak eşdeğer bir hesaplama yapar (bkz. tasarım Bölüm 3.5) -- YENİ bir
# strateji GEREKTİRMEZ. `unit="ratio"` (percentage DEĞİL) BİLİNÇLİ bir
# seçimdir -- ROIC formülündeki "(1 - effective_tax_rate)" çarpanının
# 0-1 ölçeğinde anlamlı olması için (percentage/100 ölçeğinde olsaydı bu
# çarpan yanlış olurdu).

register_ratio_formula(
    RatioFormulaMetadata(
        key="ebit_margin",
        category="profitability",
        display_name_tr="EBIT Marjı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("ebit",),
        denominator_fields=("net_sales",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="ebitda_margin",
        category="profitability",
        display_name_tr="EBITDA Marjı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("ebitda",),
        denominator_fields=("net_sales",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="pretax_profit_margin",
        category="profitability",
        display_name_tr="Vergi Öncesi Kâr Marjı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("profit_before_tax",),
        denominator_fields=("net_sales",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="return_on_capital_employed",
        category="profitability",
        display_name_tr="Kullanılan Sermaye Getirisi (ROCE)",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("ebit",),
        denominator_fields=("capital_employed",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="effective_tax_rate",
        category="profitability",
        display_name_tr="Efektif Vergi Oranı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("tax_expense",),
        denominator_fields=("profit_before_tax",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="return_on_invested_capital",
        category="profitability",
        display_name_tr="Yatırılan Sermaye Getirisi (ROIC)",
        unit="percentage",
        calculation_strategy="scaled_division",
        numerator_fields=("ebit",),
        denominator_fields=("invested_capital",),
        scale_field="one_minus_effective_tax_rate",
        depends_on_ratios=("effective_tax_rate",),
    )
)

# --- Milestone 4.3B / Step 5: ortalama-bakiye bağımlı oranlar (onaylanan
# tasarım Bölüm 2.2/2.4, Bölüm 4). `average_total_assets`/`average_equity`/
# `average_inventory`/`average_trade_receivables`/`average_trade_payables`
# facts dict'e orkestrasyon (financial_ratios/service.py) tarafından TEK
# noktadan enjekte edilir -- Bölüm 8 "average hesaplarının tutarsızlığı"
# riskinin giderilmesi (return_on_assets/asset_turnover AYNI
# `average_total_assets` anahtarını okur).

register_ratio_formula(
    RatioFormulaMetadata(
        key="return_on_assets",
        category="profitability",
        display_name_tr="Aktif Kârlılığı (ROA)",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("net_profit",),
        denominator_fields=("average_total_assets",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="return_on_equity",
        category="profitability",
        display_name_tr="Özkaynak Kârlılığı (ROE)",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("net_profit",),
        denominator_fields=("average_equity",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="asset_turnover",
        category="activity",
        display_name_tr="Aktif Devir Hızı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("net_sales",),
        denominator_fields=("average_total_assets",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="inventory_turnover",
        category="activity",
        display_name_tr="Stok Devir Hızı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("cost_of_sales",),
        denominator_fields=("average_inventory",),
        direct_document_only_fields=("inventory",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="receivables_turnover",
        category="activity",
        display_name_tr="Alacak Devir Hızı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("net_sales",),
        denominator_fields=("average_trade_receivables",),
        direct_document_only_fields=("trade_receivables",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="payables_turnover",
        category="activity",
        display_name_tr="Borç Devir Hızı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("cost_of_sales",),
        denominator_fields=("average_trade_payables",),
        direct_document_only_fields=("trade_payables",),
    )
)

# --- Milestone 4.3B / Step 6: depends_on_ratios orkestrasyonu + Faaliyet
# kategorisinin kalan 6 oranı + working_capital_to_total_assets (onaylanan
# tasarım Bölüm 2.1/2.4, Bölüm 3.2). `depends_on_ratios`'taki her key,
# `register_ratio_formula` tarafından kayıt ANINDA RATIO_REGISTRY'de zaten
# var olduğu doğrulanır -- bu yüzden bağımlılık sırası KAYIT SIRASIYLA
# (aşağıdaki register_ratio_formula çağrılarının sırasıyla) UYUMLU olmalı.
# Orkestrasyon (financial_ratios/service.py) ayrıca kategori-tuple sırasının
# bağımlılıkları GERÇEKTEN önce hesapladığından emin olmalıdır (bkz. Step 6
# service.py değişikliği).

register_ratio_formula(
    RatioFormulaMetadata(
        key="fixed_asset_turnover",
        category="activity",
        display_name_tr="Duran Varlık Devir Hızı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("net_sales",),
        denominator_fields=("non_current_assets",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="working_capital_to_total_assets",
        category="liquidity",
        display_name_tr="İşletme Sermayesi / Toplam Aktif",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("net_working_capital",),
        denominator_fields=("total_assets",),
        depends_on_ratios=("net_working_capital",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="working_capital_turnover",
        category="activity",
        display_name_tr="İşletme Sermayesi Devir Hızı",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("net_sales",),
        denominator_fields=("net_working_capital",),
        depends_on_ratios=("net_working_capital",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="days_inventory_outstanding",
        category="activity",
        display_name_tr="Stokta Kalma Süresi",
        unit="days",
        calculation_strategy="sum_division",
        numerator_fields=("days_in_period",),
        denominator_fields=("inventory_turnover",),
        depends_on_ratios=("inventory_turnover",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="days_sales_outstanding",
        category="activity",
        display_name_tr="Alacak Tahsil Süresi",
        unit="days",
        calculation_strategy="sum_division",
        numerator_fields=("days_in_period",),
        denominator_fields=("receivables_turnover",),
        depends_on_ratios=("receivables_turnover",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="days_payables_outstanding",
        category="activity",
        display_name_tr="Borç Ödeme Süresi",
        unit="days",
        calculation_strategy="sum_division",
        numerator_fields=("days_in_period",),
        denominator_fields=("payables_turnover",),
        depends_on_ratios=("payables_turnover",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="cash_conversion_cycle",
        category="activity",
        display_name_tr="Nakit Dönüşüm Süresi",
        unit="days",
        calculation_strategy="linear_combination",
        addend_fields=("days_inventory_outstanding", "days_sales_outstanding"),
        subtrahend_fields=("days_payables_outstanding",),
        depends_on_ratios=(
            "days_inventory_outstanding",
            "days_sales_outstanding",
            "days_payables_outstanding",
        ),
    )
)

# --- Milestone 4.3B / Step 7: Verimlilik kategorisi (6 oran, bağımlılık
# YOK -- onaylanan tasarım Bölüm 2.5). Tümü sum_division, hiçbiri
# average_*/depends_on_ratios/scaled_division gerektirmiyor.

register_ratio_formula(
    RatioFormulaMetadata(
        key="operating_expense_ratio",
        category="efficiency",
        display_name_tr="Faaliyet Gideri Oranı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("operating_expenses",),
        denominator_fields=("net_sales",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="cost_of_sales_ratio",
        category="efficiency",
        display_name_tr="Satışların Maliyeti Oranı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("cost_of_sales",),
        denominator_fields=("net_sales",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="overhead_ratio",
        category="efficiency",
        display_name_tr="Genel Gider Oranı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("operating_expenses", "other_operating_expenses"),
        denominator_fields=("net_sales",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="ebit_to_opex",
        category="efficiency",
        display_name_tr="EBIT / Faaliyet Gideri",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("ebit",),
        denominator_fields=("operating_expenses",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="non_operating_income_dependency",
        category="efficiency",
        display_name_tr="Faaliyet Dışı Gelir Bağımlılığı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("other_operating_income",),
        denominator_fields=("operating_profit",),
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="financing_expense_to_sales",
        category="efficiency",
        display_name_tr="Finansman Gideri / Satış",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("financing_expenses",),
        denominator_fields=("net_sales",),
    )
)

# --- Milestone 4.3B / Step 8: Büyüme kategorisi -- `growth_rate` stratejisi
# (Bölüm 3.3) ilk kez GERÇEK verilerle kullanılıyor (onaylanan tasarım
# Bölüm 2.6). `prior_*` alanları orkestrasyon (financial_ratios/service.py)
# tarafından `prior_period_balance_sheet_result`/`prior_period_income_
# statement_result`'tan enjekte edilir.

register_ratio_formula(
    RatioFormulaMetadata(
        key="sales_growth",
        category="growth",
        display_name_tr="Satış Büyümesi",
        unit="percentage",
        calculation_strategy="growth_rate",
        current_field="net_sales",
        prior_field="prior_net_sales",
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="gross_profit_growth",
        category="growth",
        display_name_tr="Brüt Kâr Büyümesi",
        unit="percentage",
        calculation_strategy="growth_rate",
        current_field="gross_profit",
        prior_field="prior_gross_profit",
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="ebitda_growth",
        category="growth",
        display_name_tr="EBITDA Büyümesi",
        unit="percentage",
        calculation_strategy="growth_rate",
        current_field="ebitda",
        prior_field="prior_ebitda",
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="net_profit_growth",
        category="growth",
        display_name_tr="Net Kâr Büyümesi",
        unit="percentage",
        calculation_strategy="growth_rate",
        current_field="net_profit",
        prior_field="prior_net_profit",
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="total_assets_growth",
        category="growth",
        display_name_tr="Toplam Aktif Büyümesi",
        unit="percentage",
        calculation_strategy="growth_rate",
        current_field="total_assets",
        prior_field="prior_total_assets",
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="equity_growth",
        category="growth",
        display_name_tr="Özkaynak Büyümesi",
        unit="percentage",
        calculation_strategy="growth_rate",
        current_field="equity",
        prior_field="prior_equity",
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="operating_cash_flow_margin",
        category="cash_flow",
        display_name_tr="Faaliyet Nakit Akışı Marjı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("operating_cash_flow",),
        denominator_fields=("net_sales",),
        # Milestone 4.3B / Step 9 (2. tur onay karar #3): Cash Flow Engine
        # (Milestone 4.4) henüz YOK -- bu 6 oran HER ZAMAN, compute_
        # registered_ratio HİÇ ÇAĞRILMADAN, NOT_CALCULABLE döner (bkz.
        # service.py::_engine_dependency_not_calculable_outcome).
        # MISSING_INPUT yalnızca Cash Flow Engine GERÇEKTEN mevcutken (4.4)
        # kullanılacaktır.
        engine_dependency="cash_flow",
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="free_cash_flow_margin",
        category="cash_flow",
        display_name_tr="Serbest Nakit Akışı Marjı",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("free_cash_flow",),
        denominator_fields=("net_sales",),
        engine_dependency="cash_flow",
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="cash_flow_to_debt",
        category="cash_flow",
        display_name_tr="Nakit Akışı / Toplam Borç",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("operating_cash_flow",),
        denominator_fields=("total_liabilities",),
        engine_dependency="cash_flow",
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="cash_return_on_assets",
        category="cash_flow",
        display_name_tr="Nakit Bazlı Aktif Getirisi",
        unit="percentage",
        calculation_strategy="sum_division",
        numerator_fields=("operating_cash_flow",),
        denominator_fields=("average_total_assets",),
        engine_dependency="cash_flow",
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="cash_interest_coverage",
        category="cash_flow",
        display_name_tr="Nakit Bazlı Faiz Karşılama",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("operating_cash_flow",),
        denominator_fields=("financing_expenses",),
        engine_dependency="cash_flow",
    )
)
register_ratio_formula(
    RatioFormulaMetadata(
        key="operating_cash_flow_ratio",
        category="cash_flow",
        display_name_tr="Faaliyet Nakit Akışı / Kısa Vadeli Borç",
        unit="ratio",
        calculation_strategy="sum_division",
        numerator_fields=("operating_cash_flow",),
        denominator_fields=("short_term_liabilities",),
        engine_dependency="cash_flow",
    )
)

register_ratio_formula(
    RatioFormulaMetadata(
        key="sustainable_growth_rate",
        category="growth",
        display_name_tr="Sürdürülebilir Büyüme Oranı",
        unit="percentage",
        # Katalog/dokümantasyon amaçlı formül -- kâr dağıtım/temettü verisi
        # HİÇBİR motorda yok, kanuni/varsayılan bir oran (%0 dağıtım gibi)
        # FABRİKE EDİLMEZ. Orkestrasyon (financial_ratios/service.py) bu
        # oranı HER ZAMAN, bu strateji hiç çağrılmadan, NOT_CALCULABLE
        # olarak kısa devre yaptırır (bkz. service.py::
        # _sustainable_growth_rate_not_calculable_outcome).
        calculation_strategy="sum_division",
        numerator_fields=("return_on_equity",),
        denominator_fields=("dividend_payout_ratio",),
        depends_on_ratios=("return_on_equity",),
    )
)
