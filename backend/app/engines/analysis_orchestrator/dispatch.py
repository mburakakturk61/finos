"""
Milestone 5.0A -- ORCHESTRATOR_ENGINE_DISPATCH (Bolum 36).

Denetim bulgusu H1'in tam cozumu: gercek, cagirilabilir motor fonksiyonlari
BURADA, import-zamaninda DOGRUDAN Python `import` ifadeleriyle baglanir.
`importlib`/`getattr` (dinamik/string-tabanli)/`eval`/`exec` KULLANILMAZ --
Architecture Book Sec.18 ile TAM uyum.

`ENGINE_DEPENDENCY_REGISTRY` (registry.py) ile bu modul KESIN OLARAK AYRIDIR:
biri "hangi motor hangi motora bagimli" (metadata), digeri "bu motoru
GERCEKTEN nasil cagiririm" (executable) sorusuna cevap verir. Bu ayrim,
testlerin TEK bir callable'i (`unittest.mock.patch` ile)
`ENGINE_DEPENDENCY_REGISTRY`'nin bagimlilik metadata'sina HIC DOKUNMADAN
sahtelemesini mumkun kilar (Bolum 65).

ORCHESTRATOR_ENGINE_DISPATCH process-local production wiring'dir --
`OrchestrationRunRequest`/`OrchestrationRunResult` gibi serilestirilebilir
sozlesmelerin PARCASI DEGILDIR (Bolum 19/36).
"""

from __future__ import annotations

from typing import Any, Callable

# --- Import-sirasi duzeltmesi (tests/conftest.py::_snapshot_shared_engine_
# registries ile AYNI kok neden) -----------------------------------------
#
# `app.engines.common.health_score_registry`/`credit_score_registry`/
# `recommendation_registry`, modul seviyesinde kayit-ani doguelanmalari
# calistirir -- bunlar `BENCHMARK_REGISTRY`'nin (48 gercek kayitla)
# ZATEN dolu olmasini gerektirir. `BENCHMARK_REGISTRY` yalnizca
# `app.engines.common.benchmark_registry` modulu import edildiginde
# (register_benchmark(...) cagrilarinin YAN ETKISIYLE) dolar --
# `app.engines.common.benchmark_types` tek basina BOS bir sozluk tanimlar.
#
# Bu dosya, health_score/credit_score/recommendation servislerini
# dogrudan import eden ILK production kod yoludur (bu motorlar bugune
# kadar app.engines.registry.py'nin gercek dispatch akisina hic
# BAGLANMAMISTI) -- bu yuzden DOGRU import sirasini burada, ACIKCA
# saglamak bu dosyanin sorumlulugudur. Sira: ratio_formulas ->
# benchmark_registry -> benchmark_types -> health_score_registry ->
# credit_score_registry -> recommendation_registry -> report_registry ->
# dashboard_registry (tests/conftest.py'deki DISIPLINLE BIREBIR AYNI).
import app.engines.common.ratio_formulas  # noqa: F401
import app.engines.common.benchmark_registry  # noqa: F401 -- BENCHMARK_REGISTRY'yi 48 kayitla doldurur (yan etki)
import app.engines.common.benchmark_types  # noqa: F401
import app.engines.common.health_score_registry  # noqa: F401
import app.engines.common.credit_score_registry  # noqa: F401
import app.engines.common.recommendation_registry  # noqa: F401
import app.engines.common.report_registry  # noqa: F401
import app.engines.common.dashboard_registry  # noqa: F401

from app.engines.analysis_orchestrator.registry import ENGINE_DEPENDENCY_REGISTRY
from app.engines.analysis_orchestrator.types import EngineCode
from app.engines.balance_sheet.service import analyze_balance_sheet
from app.engines.benchmarks.service import evaluate_benchmarks
from app.engines.credit_score.service import compute_credit_score
from app.engines.dashboards.service import generate_dashboard_snapshot
from app.engines.executive_reports.service import generate_executive_report
from app.engines.financial_ratios.service import analyze_financial_ratios
from app.engines.health_score.service import compute_financial_health_score
from app.engines.income_statement.service import analyze_income_statement
from app.engines.recommendation.service import generate_recommendations
from app.engines.render_contract.service import preview_render_contract


class DispatchIncompleteError(ValueError):
    """ENGINE_DEPENDENCY_REGISTRY ile ORCHESTRATOR_ENGINE_DISPATCH'in
    anahtar kumeleri eslesmedigi zaman firlatilir (import ani, uygulama
    hic baslamaz)."""


ORCHESTRATOR_ENGINE_DISPATCH: "dict[EngineCode, Callable[..., Any]]" = {
    EngineCode.FS_BALANCE_SHEET: analyze_balance_sheet,
    EngineCode.FS_INCOME_STATEMENT: analyze_income_statement,
    EngineCode.RATIO: analyze_financial_ratios,
    EngineCode.BENCHMARK: evaluate_benchmarks,
    EngineCode.HEALTH_SCORE: compute_financial_health_score,
    EngineCode.CREDIT_SCORE: compute_credit_score,
    EngineCode.RECOMMENDATION: generate_recommendations,
    EngineCode.EXECUTIVE_REPORT: generate_executive_report,
    EngineCode.DASHBOARD: generate_dashboard_snapshot,
    EngineCode.RENDER_CONTRACT: preview_render_contract,
}


def validate_dispatch_completeness(
    dispatch: "dict[EngineCode, Callable[..., Any]]",
    registry: "dict[EngineCode, Any]",
) -> None:
    registry_codes = set(registry)
    dispatch_codes = set(dispatch)
    if registry_codes != dispatch_codes:
        missing = registry_codes - dispatch_codes
        extra = dispatch_codes - registry_codes
        raise DispatchIncompleteError(
            f"ENGINE_DEPENDENCY_REGISTRY ile ORCHESTRATOR_ENGINE_DISPATCH "
            f"eslesmiyor. Eksik: {sorted(c.value for c in missing)}, "
            f"Fazla: {sorted(c.value for c in extra)}."
        )


validate_dispatch_completeness(ORCHESTRATOR_ENGINE_DISPATCH, ENGINE_DEPENDENCY_REGISTRY)
