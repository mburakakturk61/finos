"""
Milestone 4.3D final doğrulama (madde 8): tam test paketinin SONUNDA
çalışacak şekilde konumlandırılmış (bkz. `run_tests.py`'nin `TEST_FILES`
listesindeki SIRA -- bu dosya EN SONDA), paylaşılan global registry'lerin
"temiz" bırakıldığını doğrulayan regresyon testi.

Gerçek Docker/pytest koşusunda `test_ratio_formulas_unit.py::test_list_
ratio_formulas_by_category` testinin `_test_hs_incomplete_thresholds_
ratio` sızıntısı yüzünden başarısız olduğu tespit edilmişti (kök neden:
`tests/test_health_score_tier_interpolation_unit.py`'nin geçici bir
RATIO_REGISTRY kaydını GERİ ALMAMASI). Kök neden düzeltildi (try/finally +
`del RATIO_REGISTRY[...]`/`del BENCHMARK_REGISTRY[...]`) ve `tests/
conftest.py`'ye autouse bir snapshot/restore fixture'ı eklendi (yalnızca
GERÇEK pytest ortamında devreye girer). Bu dosya, sandbox-only stub test
runner'da (fixture mekanizması OLMADAN) dahi, tüm health score test
dosyaları çalıştıktan SONRA registry'lerin gerçekten temiz kaldığını
doğrudan doğrular.

NOT: `RATIO_REGISTRY`'nin `_test_*` kalıntısından TAMAMEN arınmış olması
beklenir (bu milestone'un düzelttiği sızıntının kaynağı). `BENCHMARK_
REGISTRY` için ise `tests/test_benchmark_types_unit.py`'nin MODÜL
SEVİYESİNDE (Milestone 4.3C'den kalma, bu milestone'un kapsamı DIŞINDA,
bilinen/kabul edilmiş) kalıcı "_test_*" kayıtları vardır -- bu, `tests/
test_benchmark_registry_unit.py::test_total_benchmark_registry_count_is_
48`'in ZATEN kullandığı filtreleme konvansiyonuyla TUTARLI şekilde burada
da filtrelenerek doğrulanır.

**Milestone 4.3E Adım 15 eklentisi:** aynı disiplinle, Credit Score'un
5 registry'sinin (`CREDIT_RATIO_SCORE_WEIGHTS`/`CREDIT_CATEGORY_WEIGHT_
PROFILES`/`CREDIT_HARD_FAIL_RULES`/`CREDIT_CRITICAL_OVERRIDE_RULES`/
`CREDIT_BANKING_LENS_SIGNAL_RULES`) TÜM Credit Score test dosyaları
çalıştıktan SONRA da temiz/tam boyutlu kaldığı doğrulanır.
"""

from app.engines.common.benchmark_types import BENCHMARK_REGISTRY
from app.engines.common.credit_score_registry import (
    CREDIT_BANKING_LENS_SIGNAL_RULES,
    CREDIT_CATEGORY_WEIGHT_PROFILES,
    CREDIT_CRITICAL_OVERRIDE_RULES,
    CREDIT_HARD_FAIL_RULES,
    CREDIT_RATIO_SCORE_WEIGHTS,
)
from app.engines.common.health_score_registry import RATIO_SCORE_WEIGHTS
from app.engines.common.ratio_formulas import RATIO_REGISTRY


def test_ratio_registry_has_zero_test_pollution_and_exact_size_57():
    leaked_keys = {code for code in RATIO_REGISTRY if code.startswith("_test") or code.startswith("_t_")}
    assert leaked_keys == set(), f"RATIO_REGISTRY'de kalıntı test kaydı bulundu: {leaked_keys}"
    assert len(RATIO_REGISTRY) == 57, f"beklenen 57 gerçek ratio formülü, bulunan: {len(RATIO_REGISTRY)}"


def test_benchmark_registry_real_entry_count_is_48_after_full_suite():
    # Milestone 4.3C'den kalma, kasıtlı/bilinen modül-seviyesi "_test_*"
    # kalıcı kayıtları (test_benchmark_types_unit.py) FİLTRELENEREK
    # doğrulanır -- bu, mevcut test_total_benchmark_registry_count_is_48
    # ile AYNI konvansiyon.
    real_entries = [code for code in BENCHMARK_REGISTRY if not code.startswith("_test")]
    assert len(real_entries) == 48, f"beklenen 48 gerçek benchmark girdisi, bulunan: {len(real_entries)}"


def test_ratio_score_weights_has_zero_test_pollution_after_full_suite():
    leaked_keys = {code for code in RATIO_SCORE_WEIGHTS if code.startswith("_test") or code.startswith("_t_")}
    assert leaked_keys == set(), f"RATIO_SCORE_WEIGHTS'te kalıntı test kaydı bulundu: {leaked_keys}"
    # Bölüm 8.1: 42 scoreable + 6 excluded (duplicate) = 48 (BENCHMARK_
    # REGISTRY'nin gerçek 48 girdisiyle birebir örtüşür).
    assert len(RATIO_SCORE_WEIGHTS) == 48


# --- Milestone 4.3E: Credit Score registry'leri de TEMİZ kalmalı -----------


def test_credit_ratio_score_weights_has_zero_test_pollution_and_exact_size_48():
    leaked_keys = {
        code for code in CREDIT_RATIO_SCORE_WEIGHTS if code.startswith("_test") or code.startswith("_t_")
    }
    assert leaked_keys == set(), f"CREDIT_RATIO_SCORE_WEIGHTS'te kalıntı test kaydı bulundu: {leaked_keys}"
    # Bölüm 5.3: 41 scored + 7 explainability-only = 48.
    assert len(CREDIT_RATIO_SCORE_WEIGHTS) == 48


def test_credit_category_weight_profiles_has_exact_size_one_global_only():
    leaked_keys = {
        scope_key for scope_key in CREDIT_CATEGORY_WEIGHT_PROFILES if str(scope_key[1]).startswith("_test")
    }
    assert leaked_keys == set()
    assert len(CREDIT_CATEGORY_WEIGHT_PROFILES) == 1
    assert ("global", None) in CREDIT_CATEGORY_WEIGHT_PROFILES


def test_credit_hard_fail_rules_has_exact_size_two_after_full_suite():
    assert len(CREDIT_HARD_FAIL_RULES) == 2
    assert {r.rule_code for r in CREDIT_HARD_FAIL_RULES} == {
        "NEGATIVE_EQUITY", "SEVERE_DEBT_SERVICE_SHORTFALL",
    }


def test_credit_critical_override_rules_has_exact_size_five_after_full_suite():
    assert len(CREDIT_CRITICAL_OVERRIDE_RULES) == 5
    assert all(rule.ratio_code != "debt_to_equity" for rule in CREDIT_CRITICAL_OVERRIDE_RULES)


def test_credit_banking_lens_signal_rules_has_exact_size_six_after_full_suite():
    assert len(CREDIT_BANKING_LENS_SIGNAL_RULES) == 6
    assert {r.flag_code for r in CREDIT_BANKING_LENS_SIGNAL_RULES} == {
        "SHORT_TERM_LIQUIDITY_STRAIN", "HIGH_LEVERAGE", "DEBT_SERVICE_STRESS",
        "WEAK_PROFIT_BUFFER", "WORKING_CAPITAL_STRAIN", "DEBT_FUNDED_GROWTH",
    }
