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
"""

from app.engines.common.benchmark_types import BENCHMARK_REGISTRY
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
