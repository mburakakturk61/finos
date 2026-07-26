"""
Milestone 4.3C (Benchmark Engine) -- `BENCHMARK_REGISTRY`'nin gerçek
girdileri. Onaylanan tasarım dokümanı: docs/
FINOS_MILESTONE_4_3C_BENCHMARK_ENGINE_DESIGN.md Bölüm 8 (2. tur onay,
9 bağlayıcı karar ile revize edilmiş sürüm).

**Adım 3 (bu commit'te eklenen):** Likidite (6) + Borçluluk (9) = 15
girdi.

**ÖNEMLİ DÜRÜSTLÜK NOTU (2. tur onay karar #1, bağlayıcı):** Aşağıdaki
sayısal eşik değerleri genel kurumsal finans/kredi analizi
literatüründen alınan PROVİZYONEL (geçici) sezgisel değerlerdir --
Türkiye'ye özgü, ampirik olarak kalibre edilmiş GERÇEK veriler DEĞİLDİR.
Her girdi `source="internal_heuristic"`, `provisional=True`,
`reliability_ceiling="medium"` (varsayılan) taşır. Health Score veya
Credit Score hesaplamasına BAĞLANMAYACAK; gerçek TCMB/KAP/İSO/BDDK veya
doğrulanmış sektör verisi gelmeden resmi/ampirik bir referansmış gibi
SUNULMAYACAK.

Bu modül `app/engines/common/benchmark_types.py`'nin `register_benchmark`
fonksiyonunu, `app/engines/common/ratio_formulas.py`'nin 4.3A/4.3B'de
kayıtlı 57 oranına karşı çağırır -- her `ratio_code`, kayıt anında
`RATIO_REGISTRY`'de zaten var olduğu için `register_benchmark`
tarafından doğrulanır (bkz. o modülün docstring'i).
"""

from decimal import Decimal

from app.engines.common.benchmark_types import (
    BenchmarkIdealDirection,
    BenchmarkMetadata,
    BenchmarkThresholds,
    effective_tax_rate_thresholds,
    register_benchmark,
)


# --- Likidite (6 benchmark, tasarım dokümanı Bölüm 8.1) -----------------

# current_ratio ve working_capital_ratio, RATIO_REGISTRY'de BİREBİR AYNI
# formülü paylaşır (current_assets / short_term_liabilities) -- bu yüzden
# ikisinin BenchmarkMetadata'sı da AYNI BenchmarkThresholds nesnesini
# referans alır (drift/tutarsızlık riskini yapısal olarak önlemek için,
# tasarım dokümanı Bölüm 8.1 notu).
_CURRENT_RATIO_THRESHOLDS = BenchmarkThresholds(
    excellent=(Decimal("1.5"), Decimal("1.8")),
    good=(Decimal("1.3"), Decimal("2.0")),
    average=(Decimal("1.0"), Decimal("2.5")),
    weak=(Decimal("0.8"), Decimal("3.5")),
    critical=None,
    warning_threshold=Decimal("1.0"),
)

register_benchmark(
    BenchmarkMetadata(
        benchmark_code="current_ratio",
        ratio_code="current_ratio",
        category="liquidity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.RANGE_IS_BETTER,
        default_thresholds=_CURRENT_RATIO_THRESHOLDS,
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="working_capital_ratio",
        ratio_code="working_capital_ratio",
        category="liquidity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.RANGE_IS_BETTER,
        default_thresholds=_CURRENT_RATIO_THRESHOLDS,
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="quick_ratio",
        ratio_code="quick_ratio",
        category="liquidity",
        benchmark_type="threshold_bands",
        unit="ratio",
        # 2. tur onay karar #3: quick_ratio MEVCUT higher_is_better
        # yaklaşımında kalır (RANGE_IS_BETTER'a ALINMADI).
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("1.5"),
            average=Decimal("1.0"),
            weak=Decimal("0.7"),
            critical=Decimal("0.4"),
            warning_threshold=Decimal("0.7"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="cash_ratio",
        ratio_code="cash_ratio",
        category="liquidity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("1.0"),
            average=Decimal("0.5"),
            weak=Decimal("0.2"),
            critical=Decimal("0.1"),
            warning_threshold=Decimal("0.2"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="defensive_interval_ratio",
        ratio_code="defensive_interval_ratio",
        category="liquidity",
        benchmark_type="threshold_bands",
        unit="days",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("180"),
            average=Decimal("90"),
            weak=Decimal("60"),
            critical=Decimal("30"),
            warning_threshold=Decimal("60"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="working_capital_to_total_assets",
        ratio_code="working_capital_to_total_assets",
        category="liquidity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.RANGE_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=(Decimal("0.10"), Decimal("0.20")),
            good=(Decimal("0.05"), Decimal("0.30")),
            average=(Decimal("0"), Decimal("0.35")),
            weak=(Decimal("-0.05"), Decimal("0.45")),
            critical=None,
            warning_threshold=Decimal("0.0"),
        ),
    )
)


# --- Borçluluk (9 benchmark, tasarım dokümanı Bölüm 8.2) ----------------
# `fixed_charge_coverage` DAHİL DEĞİL -- HER ZAMAN not_calculable
# döndüğü için benchmarklanacak hiçbir değer yok (tasarım dokümanı
# Bölüm 8 giriş notu).

register_benchmark(
    BenchmarkMetadata(
        benchmark_code="debt_ratio",
        ratio_code="debt_ratio",
        category="leverage",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("0.3"),
            average=Decimal("0.4"),
            weak=Decimal("0.6"),
            critical=Decimal("0.75"),
            warning_threshold=Decimal("0.6"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="equity_ratio",
        ratio_code="equity_ratio",
        category="leverage",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("0.6"),
            average=Decimal("0.5"),
            weak=Decimal("0.35"),
            critical=Decimal("0.2"),
            warning_threshold=Decimal("0.35"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="debt_to_equity",
        ratio_code="debt_to_equity",
        category="leverage",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("0.5"),
            average=Decimal("1.0"),
            weak=Decimal("2.0"),
            critical=Decimal("4.0"),
            warning_threshold=Decimal("2.0"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="long_term_debt_to_equity",
        ratio_code="long_term_debt_to_equity",
        category="leverage",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("0.25"),
            average=Decimal("0.5"),
            weak=Decimal("1.0"),
            critical=Decimal("2.0"),
            warning_threshold=Decimal("1.0"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="short_term_debt_ratio",
        ratio_code="short_term_debt_ratio",
        category="leverage",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("0.4"),
            average=Decimal("0.6"),
            weak=Decimal("0.75"),
            critical=Decimal("0.9"),
            warning_threshold=Decimal("0.75"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="financial_leverage_multiplier",
        ratio_code="financial_leverage_multiplier",
        category="leverage",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("1.5"),
            average=Decimal("2.0"),
            weak=Decimal("3.0"),
            critical=Decimal("5.0"),
            warning_threshold=Decimal("3.0"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="interest_coverage_ratio",
        ratio_code="interest_coverage_ratio",
        category="leverage",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("8"),
            average=Decimal("4"),
            weak=Decimal("2"),
            critical=Decimal("1"),
            warning_threshold=Decimal("1.5"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="ebitda_coverage_ratio",
        ratio_code="ebitda_coverage_ratio",
        category="leverage",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("10"),
            average=Decimal("6"),
            weak=Decimal("3"),
            critical=Decimal("1"),
            warning_threshold=Decimal("2"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="debt_to_ebitda",
        ratio_code="debt_to_ebitda",
        category="leverage",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("1.5"),
            average=Decimal("2.5"),
            weak=Decimal("4.0"),
            critical=Decimal("6.0"),
            warning_threshold=Decimal("4.0"),
        ),
    )
)


# --- Kârlılık (11 benchmark, tasarım dokümanı Bölüm 8.3) ----------------
# `effective_tax_rate`, 2. tur onay karar #9 gereği merkezi
# `STATUTORY_CORPORATE_TAX_RATE_TR` sabitinden türetilen
# `effective_tax_rate_thresholds()` yardımcı fonksiyonunu kullanır --
# ham sınır sayıları BURADA TEKRAR YAZILMAZ.

register_benchmark(
    BenchmarkMetadata(
        benchmark_code="gross_profit_margin",
        ratio_code="gross_profit_margin",
        category="profitability",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("40"),
            average=Decimal("25"),
            weak=Decimal("15"),
            critical=Decimal("5"),
            warning_threshold=Decimal("10"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="operating_profit_margin",
        ratio_code="operating_profit_margin",
        category="profitability",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("20"),
            average=Decimal("12"),
            weak=Decimal("6"),
            critical=Decimal("0"),
            warning_threshold=Decimal("3"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="net_profit_margin",
        ratio_code="net_profit_margin",
        category="profitability",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("15"),
            average=Decimal("8"),
            weak=Decimal("3"),
            critical=Decimal("0"),
            warning_threshold=Decimal("1"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="ebit_margin",
        ratio_code="ebit_margin",
        category="profitability",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("18"),
            average=Decimal("10"),
            weak=Decimal("5"),
            critical=Decimal("0"),
            warning_threshold=Decimal("2"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="ebitda_margin",
        ratio_code="ebitda_margin",
        category="profitability",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("22"),
            average=Decimal("14"),
            weak=Decimal("8"),
            critical=Decimal("0"),
            warning_threshold=Decimal("3"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="pretax_profit_margin",
        ratio_code="pretax_profit_margin",
        category="profitability",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("14"),
            average=Decimal("7"),
            weak=Decimal("3"),
            critical=Decimal("0"),
            warning_threshold=Decimal("1"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="return_on_capital_employed",
        ratio_code="return_on_capital_employed",
        category="profitability",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("20"),
            average=Decimal("12"),
            weak=Decimal("6"),
            critical=Decimal("0"),
            warning_threshold=Decimal("3"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="effective_tax_rate",
        ratio_code="effective_tax_rate",
        category="profitability",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.RANGE_IS_BETTER,
        # 2. tur onay karar #9: TEK merkezi kaynaktan türetilir --
        # STATUTORY_CORPORATE_TAX_RATE_TR değişirse bu bant OTOMATİK kayar.
        default_thresholds=effective_tax_rate_thresholds(),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="return_on_invested_capital",
        ratio_code="return_on_invested_capital",
        category="profitability",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("18"),
            average=Decimal("10"),
            weak=Decimal("5"),
            critical=Decimal("0"),
            warning_threshold=Decimal("2"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="return_on_assets",
        ratio_code="return_on_assets",
        category="profitability",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("10"),
            average=Decimal("5"),
            weak=Decimal("2"),
            critical=Decimal("0"),
            warning_threshold=Decimal("1"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="return_on_equity",
        ratio_code="return_on_equity",
        category="profitability",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("20"),
            average=Decimal("12"),
            weak=Decimal("6"),
            critical=Decimal("0"),
            warning_threshold=Decimal("2"),
        ),
    )
)


# --- Faaliyet (10 benchmark, tasarım dokümanı Bölüm 8.4) ----------------
# `payables_turnover`/`days_payables_outstanding`: 2. tur onay karar #3/#9
# gereği RANGE_IS_BETTER -- AŞIRI HIZLI (tedarikçi finansmanından
# yararlanılmıyor) VE AŞIRI YAVAŞ (ödeme güçlüğü sinyali) ödeme İKİ TARAFLI
# risk olarak modellenmiştir; `warning_threshold` da İKİ TARAFLI bir
# `(low, high)` tuple'ıdır.

register_benchmark(
    BenchmarkMetadata(
        benchmark_code="asset_turnover",
        ratio_code="asset_turnover",
        category="activity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("1.5"),
            average=Decimal("1.0"),
            weak=Decimal("0.6"),
            critical=Decimal("0.3"),
            warning_threshold=Decimal("0.5"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="inventory_turnover",
        ratio_code="inventory_turnover",
        category="activity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("8"),
            average=Decimal("5"),
            weak=Decimal("3"),
            critical=Decimal("1.5"),
            warning_threshold=Decimal("2"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="receivables_turnover",
        ratio_code="receivables_turnover",
        category="activity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("12"),
            average=Decimal("8"),
            weak=Decimal("5"),
            critical=Decimal("2"),
            warning_threshold=Decimal("3"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="payables_turnover",
        ratio_code="payables_turnover",
        category="activity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.RANGE_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=(Decimal("5"), Decimal("7")),
            good=(Decimal("4"), Decimal("9")),
            average=(Decimal("3"), Decimal("11")),
            weak=(Decimal("2"), Decimal("14")),
            critical=None,
            warning_threshold=(Decimal("4"), Decimal("9")),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="fixed_asset_turnover",
        ratio_code="fixed_asset_turnover",
        category="activity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("4"),
            average=Decimal("2.5"),
            weak=Decimal("1.5"),
            critical=Decimal("0.7"),
            warning_threshold=Decimal("1"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="working_capital_turnover",
        ratio_code="working_capital_turnover",
        category="activity",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("8"),
            average=Decimal("5"),
            weak=Decimal("3"),
            critical=Decimal("1"),
            warning_threshold=Decimal("2"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="days_inventory_outstanding",
        ratio_code="days_inventory_outstanding",
        category="activity",
        benchmark_type="threshold_bands",
        unit="days",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("30"),
            average=Decimal("45"),
            weak=Decimal("75"),
            critical=Decimal("120"),
            warning_threshold=Decimal("90"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="days_sales_outstanding",
        ratio_code="days_sales_outstanding",
        category="activity",
        benchmark_type="threshold_bands",
        unit="days",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("30"),
            average=Decimal("45"),
            weak=Decimal("60"),
            critical=Decimal("90"),
            warning_threshold=Decimal("75"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="days_payables_outstanding",
        ratio_code="days_payables_outstanding",
        category="activity",
        benchmark_type="threshold_bands",
        unit="days",
        ideal_direction=BenchmarkIdealDirection.RANGE_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=(Decimal("45"), Decimal("75")),
            good=(Decimal("30"), Decimal("95")),
            average=(Decimal("15"), Decimal("120")),
            weak=(Decimal("5"), Decimal("150")),
            critical=None,
            warning_threshold=(Decimal("15"), Decimal("95")),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="cash_conversion_cycle",
        ratio_code="cash_conversion_cycle",
        category="activity",
        benchmark_type="threshold_bands",
        unit="days",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("0"),
            average=Decimal("30"),
            weak=Decimal("60"),
            critical=Decimal("90"),
            warning_threshold=Decimal("60"),
        ),
    )
)


# --- Verimlilik (6 benchmark, tasarım dokümanı Bölüm 8.5) ---------------

register_benchmark(
    BenchmarkMetadata(
        benchmark_code="operating_expense_ratio",
        ratio_code="operating_expense_ratio",
        category="efficiency",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("10"),
            average=Decimal("15"),
            weak=Decimal("22"),
            critical=Decimal("30"),
            warning_threshold=Decimal("25"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="cost_of_sales_ratio",
        ratio_code="cost_of_sales_ratio",
        category="efficiency",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("50"),
            average=Decimal("65"),
            weak=Decimal("78"),
            critical=Decimal("90"),
            warning_threshold=Decimal("85"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="overhead_ratio",
        ratio_code="overhead_ratio",
        category="efficiency",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("8"),
            average=Decimal("13"),
            weak=Decimal("20"),
            critical=Decimal("28"),
            warning_threshold=Decimal("22"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="ebit_to_opex",
        ratio_code="ebit_to_opex",
        category="efficiency",
        benchmark_type="threshold_bands",
        unit="ratio",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("2.0"),
            average=Decimal("1.3"),
            weak=Decimal("0.8"),
            critical=Decimal("0.3"),
            warning_threshold=Decimal("0.6"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="non_operating_income_dependency",
        ratio_code="non_operating_income_dependency",
        category="efficiency",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("10"),
            average=Decimal("20"),
            weak=Decimal("35"),
            critical=Decimal("60"),
            warning_threshold=Decimal("40"),
        ),
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="financing_expense_to_sales",
        ratio_code="financing_expense_to_sales",
        category="efficiency",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.LOWER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("1"),
            average=Decimal("3"),
            weak=Decimal("6"),
            critical=Decimal("10"),
            warning_threshold=Decimal("6"),
        ),
    )
)


# --- Büyüme (6 benchmark, tasarım dokümanı Bölüm 8.6) -------------------
# 2. tur onay karar #7 (BAĞLAYICI): TÜMÜ nominal (TÜFE düzeltmesiz) --
# `inflation_adjusted=False` + `reliability_ceiling="medium_low"`
# (register_benchmark bu ikisini category="growth" için ZORUNLU kılar).
# `sustainable_growth_rate` DAHİL DEĞİL (HER ZAMAN not_calculable).

register_benchmark(
    BenchmarkMetadata(
        benchmark_code="sales_growth",
        ratio_code="sales_growth",
        category="growth",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("40"),
            average=Decimal("20"),
            weak=Decimal("10"),
            critical=Decimal("0"),
            warning_threshold=Decimal("5"),
        ),
        inflation_adjusted=False,
        reliability_ceiling="medium_low",
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="gross_profit_growth",
        ratio_code="gross_profit_growth",
        category="growth",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("40"),
            average=Decimal("20"),
            weak=Decimal("10"),
            critical=Decimal("0"),
            warning_threshold=Decimal("5"),
        ),
        inflation_adjusted=False,
        reliability_ceiling="medium_low",
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="ebitda_growth",
        ratio_code="ebitda_growth",
        category="growth",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("40"),
            average=Decimal("20"),
            weak=Decimal("10"),
            critical=Decimal("0"),
            warning_threshold=Decimal("5"),
        ),
        inflation_adjusted=False,
        reliability_ceiling="medium_low",
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="net_profit_growth",
        ratio_code="net_profit_growth",
        category="growth",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("50"),
            average=Decimal("20"),
            weak=Decimal("5"),
            critical=Decimal("-10"),
            warning_threshold=Decimal("0"),
        ),
        inflation_adjusted=False,
        reliability_ceiling="medium_low",
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="total_assets_growth",
        ratio_code="total_assets_growth",
        category="growth",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("30"),
            average=Decimal("15"),
            weak=Decimal("5"),
            critical=Decimal("0"),
            warning_threshold=Decimal("0"),
        ),
        inflation_adjusted=False,
        reliability_ceiling="medium_low",
    )
)
register_benchmark(
    BenchmarkMetadata(
        benchmark_code="equity_growth",
        ratio_code="equity_growth",
        category="growth",
        benchmark_type="threshold_bands",
        unit="percentage",
        ideal_direction=BenchmarkIdealDirection.HIGHER_IS_BETTER,
        default_thresholds=BenchmarkThresholds(
            excellent=None,
            good=Decimal("25"),
            average=Decimal("12"),
            weak=Decimal("5"),
            critical=Decimal("0"),
            warning_threshold=Decimal("0"),
        ),
        inflation_adjusted=False,
        reliability_ceiling="medium_low",
    )
)
