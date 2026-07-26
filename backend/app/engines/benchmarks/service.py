"""
Milestone 4.3C (Benchmark Engine) -- Adım 7: `evaluate_benchmarks()`
orkestrasyonu.

Onaylanan tasarım dokümanı: docs/FINOS_MILESTONE_4_3C_BENCHMARK_ENGINE_DESIGN.md
(2. tur onay, bağlayıcı karar #6): bu fonksiyon SAF, BAĞIMSIZ bir Python
kütüphane fonksiyonudur -- HİÇBİR `EngineAdapter`/`AnalysisType`/DB
kaydına/API'ye/bulk upload akışına BAĞLI DEĞİLDİR. Girdisi, Financial
Ratio Engine'in (`app.engines.financial_ratios.service.
analyze_financial_ratios`) ZATEN ÜRETTİĞİ `result_json`'dur -- hiçbir
oran YENİDEN HESAPLANMAZ (B.3 ilkesinin benchmark'a genellemesi).

Persistence ve gerçek akışa bağlanma (adapter/AnalysisType/migration/API)
AYRI bir gelecek milestone'un VE ayrı bir onayın konusudur -- bu dosyada
YOKTUR.

sqlalchemy/fastapi/pydantic'e SIFIR bağımlı.
"""

from typing import Any

from app.engines.common.benchmark_types import (
    BENCHMARK_REGISTRY_VERSION,
    evaluate_benchmark,
)
from app.engines.common.ratio_formulas import json_safe_to_decimal


ENGINE_VERSION = "1.0.0"


def evaluate_benchmarks(
    ratio_result_json: dict[str, Any],
    *,
    industry_code: "str | None" = None,
    company_size_bucket: "str | None" = None,
) -> dict[str, Any]:
    """
    `ratio_result_json` -- `analyze_financial_ratios()`'un DOĞRUDAN
    çıktısı (`result_json["categories"][cat]["ratios"][ratio_key]`
    şeklini bekler: her ratio_key için `value`/`status`/`reliability`
    alanları). Bu fonksiyon o yapıyı YENİDEN HESAPLAMAZ, yalnızca OKUR.

    Her ratio_key için `evaluate_benchmark(benchmark_code=ratio_key, ...)`
    çağrılır -- 4.3C'de `benchmark_code == ratio_code` (Bölüm 7) olduğu
    için bu eşleme doğrudandır. Kayıtlı bir benchmark yoksa (ör.
    `net_working_capital`, `sustainable_growth_rate`,
    `fixed_charge_coverage`, `cash_flow` kategorisinin 6 oranı)
    `evaluate_benchmark` zaten kontrollü `BENCHMARK_NOT_REGISTERED`
    döner -- burada ayrıca bir kontrol GEREKMEZ.

    `industry_code`/`company_size_bucket` -- override çözümlemesi için
    (Bölüm 6.1: industry > company_size > default). 4.3C'de gerçek
    override verisi BOŞ olduğu için (Bölüm 11/12) bu parametreler
    şimdilik yalnızca sözleşmeyi TEST ETMEK için kullanılabilir; gerçek
    veri geldiğinde davranış DEĞİŞMEDEN çalışmaya devam eder.

    `country`/`country_code` parametresi BİLİNÇLİ OLARAK YOKTUR (2. tur
    onay karar #5 -- YAGNI, hiçbir iskelet bile eklenmez).
    """

    categories_out: dict[str, Any] = {}

    for category, category_data in (ratio_result_json.get("categories") or {}).items():
        ratios_out: dict[str, Any] = {}
        for ratio_key, ratio_data in (category_data.get("ratios") or {}).items():
            ratio_status = ratio_data.get("status", "not_calculable")
            ratio_value = json_safe_to_decimal(ratio_data.get("value"))
            ratio_reliability = ratio_data.get("reliability", "not_calculable")

            evaluation = evaluate_benchmark(
                ratio_key,
                ratio_status,
                ratio_value,
                ratio_reliability,
                industry_code=industry_code,
                company_size_bucket=company_size_bucket,
            )

            ratios_out[ratio_key] = {
                "status": evaluation.status.value,
                "tier": evaluation.tier,
                "reliability": evaluation.reliability,
                "warning_flag": evaluation.warning_flag,
                "underlying_ratio_status": evaluation.underlying_ratio_status,
                "resolved_scope": evaluation.resolved_scope,
                "provisional": evaluation.provisional,
                "inflation_adjusted": evaluation.inflation_adjusted,
                "warnings": list(evaluation.warnings),
            }

        categories_out[category] = {"ratios": ratios_out}

    return {
        "engine": "benchmarks",
        "engine_version": ENGINE_VERSION,
        "benchmark_registry_version": BENCHMARK_REGISTRY_VERSION,
        # Hangi ratio_registry_version'a karşı değerlendirildiği --
        # reprodüktibilite için (tasarım dokümanı Bölüm 17).
        "ratio_registry_version": ratio_result_json.get("ratio_registry_version"),
        "industry_code": industry_code,
        "company_size_bucket": company_size_bucket,
        "categories": categories_out,
    }
