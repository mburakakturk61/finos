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


RATIO_REGISTRY: dict[str, RatioFormulaMetadata] = {}
RATIO_REGISTRY_VERSION = "1.0.0"
# Milestone 4.3A: J.2'deki cache-anahtarı tasarımının bir parçası (henüz
# hiçbir cache implementasyonu YOK -- yalnızca sürüm sabiti burada, formül
# değiştiğinde (implementasyon sonrası bir düzeltme) yükseltilecek).


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


# Milestone 4.3A: KAPALI strateji kümesi -- eval/exec/dinamik expression
# YOK. Gelecekteki stratejiler (average_balance_division/days_conversion/
# ratio_of_ratio/boolean_threshold -- Milestone 4.3B+) yalnızca mimari
# dokümanda İSİM olarak kayıtlıdır, burada YOKTUR.
CALCULATION_STRATEGIES: dict[
    str, Callable[[RatioFormulaMetadata, dict[str, Decimal | None]], ComputationOutcome]
] = {
    "sum_division": compute_sum_division,
    "linear_combination": compute_linear_combination,
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

    all_input_fields = (
        metadata.numerator_fields
        + metadata.denominator_fields
        + metadata.addend_fields
        + metadata.subtrahend_fields
    )
    rounding_applied = (
        f"quantize({metadata.quantize_exp}, ROUND_HALF_UP)"
        if metadata.calculation_strategy == "sum_division"
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
