"""
SQLite in-memory fixture'ları. Kapsam: API sözleşmesi testleri.
PostgreSQL'e özgü davranışlar için bkz. test_postgres_integration.py ve
tests/README.md.

Ayrıca (Milestone 4.3D final doğrulama + Milestone 4.3E Adım 12): `RATIO_
REGISTRY` / `BENCHMARK_REGISTRY` / `RATIO_SCORE_WEIGHTS` / `CREDIT_RATIO_
SCORE_WEIGHTS` / `CREDIT_CATEGORY_WEIGHT_PROFILES` / `CREDIT_HARD_FAIL_
RULES` / `CREDIT_CRITICAL_OVERRIDE_RULES` / `CREDIT_BANKING_LENS_SIGNAL_
RULES` gibi process-genelinde PAYLAŞILAN global registry yapıları için
autouse bir "snapshot + kesin geri yükleme" fixture'ı -- bkz. aşağıdaki
`_snapshot_shared_engine_registries`.

**ÖNEMLİ (import sırası düzeltmesi):** `app.engines.common.health_score_
registry`, modül seviyesinde `_build_ratio_score_weights()` çalıştırır --
bu fonksiyon her `ratio_code`'un `BENCHMARK_REGISTRY`'de KAYITLI olduğunu
doğrular (production validasyonu, GEVŞETİLMEDİ). `BENCHMARK_REGISTRY`
yalnızca `app.engines.common.benchmark_registry` modülü import edildiğinde
(o modüldeki `register_benchmark(...)` çağrılarının YAN ETKİSİYLE) gerçek
48 kayıtla dolar -- `app.engines.common.benchmark_types` tek başına yalnızca
BOŞ bir `BENCHMARK_REGISTRY = {}` sözlüğü tanımlar. Bu dosya (conftest.py)
pytest'in TOPLAMA (collection) aşamasında EN İLK yüklenen dosyadır; önceki
sürümde bu dosyanın MODÜL SEVİYESİNDE `from app.engines.common.health_
score_registry import RATIO_SCORE_WEIGHTS` yapması, `benchmark_registry`
modülü HENÜZ hiçbir yerde import edilmemişken `health_score_registry`'yi
tetikliyordu -- `BENCHMARK_REGISTRY` boşken `_build_ratio_score_weights()`
çalışıp "'current_ratio', BENCHMARK_REGISTRY'de kayıtlı değil" ile
patlıyordu. Bu, production hesaplama hatası DEĞİL, yalnızca bu dosyanın
kendi import sırası hatasıydı. Çözüm: üç modülü de burada, DOĞRU sırayla
(ratio_formulas -> benchmark_registry -> health_score_registry) ve
LAZY olarak (fixture GÖVDESİNDE, modül seviyesinde DEĞİL) import etmek.

**Milestone 4.3E Adım 12 eklentisi:** `app.engines.common.credit_score_
registry`, modül seviyesinde `_build_credit_ratio_score_weights()` +
`CREDIT_HARD_FAIL_RULES`/`CREDIT_CRITICAL_OVERRIDE_RULES`/`CREDIT_
BANKING_LENS_SIGNAL_RULES` kayıt-anı doğrulamalarını çalıştırır -- bu da
`BENCHMARK_REGISTRY`'nin (Health Score ile AYNI kök neden) ZATEN dolu
olmasını gerektirir. Bu yüzden `credit_score_registry` importu da AYNI
disiplinle -- LAZY (fixture gövdesinde) ve `benchmark_registry`'den
SONRA -- eklenir. `credit_score_registry`, `health_score_registry`'ye
BAĞIMLI DEĞİLDİR (yalnızca `benchmark_types`/`credit_score_types`'a
bağımlıdır) -- ama tutarlılık için import sırası, bu dosyadaki mevcut
sırayı KORUYARAK genişletilir (ratio_formulas -> benchmark_registry ->
benchmark_types -> health_score_registry -> credit_score_registry).

**Milestone 4.3F eklentisi (Recommendation Engine, Adım 13):**
`app.engines.common.recommendation_registry`, modül seviyesinde
`register_recommendation_rule()` (39 kural) + `_validate_cross_rule_
references()` kayıt-anı doğrulamalarını çalıştırır -- bu da `RATIO_
REGISTRY`'nin (related_ratio_codes çapraz doğrulaması için) ZATEN dolu
olmasını gerektirir. Bölüm 1.6'nın ZORUNLU import sırası gereği bu modül
`credit_score_registry`'den SONRA, HER ZAMAN EN SON import edilir:
`ratio_formulas -> benchmark_registry -> benchmark_types ->
health_score_registry -> credit_score_registry ->
recommendation_registry`. `RECOMMENDATION_RULES`/`RECOMMENDATION_
CONFLICT_PAIRS` `tuple` (immutable, referans yeniden atamayla restore
edilir); `RECOMMENDATION_CATEGORY_WEIGHT_PROFILES`/`BANKING_FLAG_TO_
RATIO_OVERLAP` `dict` (mutable, `clear()+update()` ile restore edilir).
Restore AŞAMASI (finally bloğu), snapshot sırasının TERSİ (LIFO) --
Recommendation Engine EN SON import edildiği için EN ÖNCE restore edilir.

**Milestone 4.4 eklentisi (Executive Report Engine, Adım 6):** `app.engines.
common.report_registry` (18 section + 7 report type + legal/confidentiality
matrisi) ve `app.engines.common.dashboard_registry` (10 widget) de modül
seviyesinde kayıt-anı doğrulaması çalıştırır. Bu ikisi `recommendation_
registry`'ye BAĞIMLI DEĞİLDİR (yalnızca `report_types`/`dashboard_types`'a
bağımlıdır) ama tutarlılık için EN SON import edilir, LIFO restore'da EN
ÖNCE geri yüklenir.

**Milestone 5.0A eklentisi (Analysis Orchestrator, Bölüm 65):**
`app.engines.analysis_orchestrator.registry.ENGINE_DEPENDENCY_REGISTRY`
(10 motor kodu + 24 kenar) de modül seviyesinde kayıt-anı doğrulaması
(`validate_dependency_registry`) çalıştırır. Bu registry diğerlerine
BAĞIMLI DEĞİLDİR (yalnızca `analysis_orchestrator.types`'a bağımlıdır) --
ama tutarlılık için EN SON eklenir, LIFO restore'da EN ÖNCE geri yüklenir.
`app.engines.analysis_orchestrator.dispatch.ORCHESTRATOR_ENGINE_DISPATCH`
bir "registry" DEĞİLDİR (kayıt-doğrulama mantığı taşımaz, yalnızca sabit
import-zamanı bağlamalardır) -- testler tek tek callable'ları
`unittest.mock.patch.dict` ile geçici olarak değiştirir, bu fixture'a
GEREK DUYMAZ (Bölüm 65).
"""

from collections.abc import Generator
import uuid

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  -- Base.metadata'yı doldurmak için gerekli
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.integrations.analysis_http.legacy_security import (
    require_legacy_route_security,
    resolve_legacy_tenant_id,
)
from app.models.analysis_run_scope_claim import AnalysisRunScopeClaim
from app.models.bulk_upload_batch import BulkUploadBatch
from app.models.company import Company


_E2_TEST_TENANT_ID = uuid.UUID("00000000-0000-5000-8000-000000005e20")
_E2_TEST_TENANT_KEY = "test-default-tenant"


def _insert_test_tenant(connection, tenant_id: uuid.UUID, tenant_key: str) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(text("""
            INSERT INTO security_tenants
                (id,tenant_key,status,policy_version,version)
            VALUES (:id,:key,'ACTIVE',1,1)
            ON CONFLICT (tenant_key) DO NOTHING
        """), {"id": tenant_id, "key": tenant_key})
    elif connection.dialect.name == "sqlite":
        connection.execute(text("""
            INSERT OR IGNORE INTO security_tenants
                (id,tenant_key,status,policy_version,version)
            VALUES (:id,:key,'ACTIVE',1,1)
        """), {"id": tenant_id.hex, "key": tenant_key})


def pytest_sessionstart(session) -> None:
    """Explicitly bind accumulated shared test data before E2 is applied.

    This is test-only trusted fixture provisioning. Production migrations never
    infer a tenant and retain the fail-closed E2 behavior.
    """
    from app.core.config import get_settings

    test_engine = create_engine(get_settings().database_url)
    try:
        with test_engine.begin() as connection:
            if connection.scalar(text("SELECT to_regclass('security_tenants')")) is None:
                return
            _insert_test_tenant(connection, _E2_TEST_TENANT_ID, _E2_TEST_TENANT_KEY)
            keys = connection.execute(text("""
                SELECT DISTINCT tenant_id FROM analysis_run_scope_claims
                WHERE tenant_id ~ '^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$'
                  AND octet_length(tenant_id) BETWEEN 3 AND 63
            """)).scalars()
            for tenant_key in keys:
                tenant_id = uuid.uuid5(uuid.NAMESPACE_URL, "finos-test:" + tenant_key)
                _insert_test_tenant(connection, tenant_id, tenant_key)
            connection.execute(text(
                "UPDATE companies SET tenant_id=:tenant WHERE tenant_id IS NULL"
            ), {"tenant": _E2_TEST_TENANT_ID})
            connection.execute(text(
                "UPDATE bulk_upload_batches SET tenant_id=:tenant WHERE tenant_id IS NULL"
            ), {"tenant": _E2_TEST_TENANT_ID})
    finally:
        test_engine.dispose()


@event.listens_for(Company, "before_insert")
def _bind_test_company_tenant(_mapper, connection, target) -> None:
    if target.tenant_id is None:
        _insert_test_tenant(connection, _E2_TEST_TENANT_ID, _E2_TEST_TENANT_KEY)
        target.tenant_id = _E2_TEST_TENANT_ID


@event.listens_for(BulkUploadBatch, "before_insert")
def _bind_test_batch_tenant(_mapper, connection, target) -> None:
    if target.tenant_id is None:
        _insert_test_tenant(connection, _E2_TEST_TENANT_ID, _E2_TEST_TENANT_KEY)
        target.tenant_id = _E2_TEST_TENANT_ID


@event.listens_for(AnalysisRunScopeClaim, "before_insert")
def _provision_test_claim_tenant(_mapper, connection, target) -> None:
    if target.tenant_id:
        tenant_id = uuid.uuid5(uuid.NAMESPACE_URL, "finos-test:" + target.tenant_id)
        _insert_test_tenant(connection, tenant_id, target.tenant_id)


@pytest.fixture(autouse=True)
def _snapshot_shared_engine_registries() -> Generator[None, None, None]:
    """
    Milestone 4.3D final doğrulama (gerçek Docker/pytest koşusu) --
    kök neden: `RATIO_REGISTRY`/`BENCHMARK_REGISTRY`/`RATIO_SCORE_WEIGHTS`
    modül seviyesinde TANIMLANMIŞ, process-genelinde PAYLAŞILAN mutable
    sözlüklerdir. Bir test (ör. eski hâliyle `test_health_score_tier_
    interpolation_unit.py::test_compute_ratio_score_falls_back_to_tier_
    constant_when_thresholds_incomplete`) geçici bir "_test_*" kaydı
    ekleyip GERİ ALMAZSA, pytest'in TÜM test dosyalarını TEK process'te
    (genellikle alfabetik toplama sırasıyla) çalıştırması yüzünden, o
    kayıt SONRAKİ, TAMAMEN İLGİSİZ bir test dosyasını (`test_ratio_
    formulas_unit.py::test_list_ratio_formulas_by_category`) kirletip
    başarısız edebilir.

    Bu autouse fixture, HER testten önce üç registry'nin de sığ birer
    kopyasını (snapshot) alır ve test bittikten sonra -- test BAŞARILI
    olsa da, bir assertion/exception ile BAŞARISIZ olsa da (`finally`
    bloğu HER durumda çalışır) -- registry'leri `clear()` + `update()`
    ile snapshot'taki hâline BİREBİR geri yükler. Böylece testlerin sıra
    bağımlılığı (bir testin, başka bir testin bıraktığı kalıntıdan
    etkilenmesi) yapısal olarak ortadan kaldırılır.

    NOT 1: Bu fixture, testin KENDİ İÇİNDE try/finally ile temizlik yapma
    disiplininin (bkz. `test_ratio_formulas_unit.py`'deki `del
    RATIO_REGISTRY[...]` konvansiyonu) YERİNİ TUTMAZ -- ikinci bir güvenlik
    katmanıdır (defense-in-depth). Sandbox-only stub test runner (`tests/
    README.md`) pytest fixture mekanizmasını KULLANMADIĞI için, bu fixture
    yalnızca GERÇEK pytest ortamında (Docker) devreye girer.

    NOT 2: Registry importları BİLEREK bu fonksiyon GÖVDESİNDE (modül
    seviyesinde DEĞİL) ve DOĞRU sırayla yapılır -- yukarıdaki docstring'te
    açıklanan import-sırası hatasını önlemek için. `import X` zaten
    import edilmiş bir modül için ucuz bir sözlük bakışıdır (`sys.modules`
    cache'i) -- burada tekrar tekrar çağrılması performans sorunu
    yaratmaz.
    """

    import app.engines.common.ratio_formulas as ratio_formulas_module
    import app.engines.common.benchmark_registry  # noqa: F401 -- BENCHMARK_REGISTRY'yi 48 gerçek kayıtla YAN ETKİ olarak doldurur
    import app.engines.common.benchmark_types as benchmark_types_module
    import app.engines.common.health_score_registry as health_score_registry_module
    import app.engines.common.credit_score_registry as credit_score_registry_module
    import app.engines.common.recommendation_registry as recommendation_registry_module
    import app.engines.common.report_registry as report_registry_module
    import app.engines.common.dashboard_registry as dashboard_registry_module
    import app.engines.analysis_orchestrator.registry as orchestrator_registry_module

    ratio_registry_snapshot = dict(ratio_formulas_module.RATIO_REGISTRY)
    benchmark_registry_snapshot = dict(benchmark_types_module.BENCHMARK_REGISTRY)
    ratio_score_weights_snapshot = dict(health_score_registry_module.RATIO_SCORE_WEIGHTS)
    credit_ratio_score_weights_snapshot = dict(
        credit_score_registry_module.CREDIT_RATIO_SCORE_WEIGHTS
    )
    credit_category_weight_profiles_snapshot = dict(
        credit_score_registry_module.CREDIT_CATEGORY_WEIGHT_PROFILES
    )
    credit_hard_fail_rules_snapshot = credit_score_registry_module.CREDIT_HARD_FAIL_RULES
    credit_critical_override_rules_snapshot = (
        credit_score_registry_module.CREDIT_CRITICAL_OVERRIDE_RULES
    )
    credit_banking_lens_signal_rules_snapshot = (
        credit_score_registry_module.CREDIT_BANKING_LENS_SIGNAL_RULES
    )
    recommendation_rules_by_code_snapshot = dict(
        recommendation_registry_module.RECOMMENDATION_RULES_BY_CODE
    )
    recommendation_rules_snapshot = recommendation_registry_module.RECOMMENDATION_RULES
    recommendation_conflict_pairs_snapshot = (
        recommendation_registry_module.RECOMMENDATION_CONFLICT_PAIRS
    )
    recommendation_mutually_exclusive_groups_snapshot = (
        recommendation_registry_module.RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS
    )
    recommendation_category_weight_profiles_snapshot = dict(
        recommendation_registry_module.RECOMMENDATION_CATEGORY_WEIGHT_PROFILES
    )
    banking_flag_to_ratio_overlap_snapshot = dict(
        recommendation_registry_module.BANKING_FLAG_TO_RATIO_OVERLAP
    )

    # Milestone 4.4 eklentisi (Executive Report Engine, Adım 6): `app.engines.
    # common.report_registry`/`app.engines.common.dashboard_registry` da modül
    # seviyesinde kayıt-anı doğrulaması çalıştırır (18 section + 7 report type +
    # 10 widget). Bu iki modül `recommendation_registry`'ye BAĞIMLI DEĞİLDİR
    # (yalnızca `report_types`/`dashboard_types`'a bağımlıdır) -- ama tutarlılık
    # için EN SON eklenir, LIFO restore'da EN ÖNCE geri yüklenir.
    report_section_registry_snapshot = dict(report_registry_module.REPORT_SECTION_REGISTRY)
    report_type_registry_snapshot = dict(report_registry_module.REPORT_TYPE_REGISTRY)
    report_type_legal_profiles_snapshot = dict(report_registry_module.REPORT_TYPE_LEGAL_PROFILES)
    dashboard_widget_registry_snapshot = dict(dashboard_registry_module.DASHBOARD_WIDGET_REGISTRY)

    # Milestone 5.0A eklentisi (Bölüm 65): ENGINE_DEPENDENCY_REGISTRY en
    # son import edilir, LIFO restore'da en önce geri yüklenir.
    orchestrator_registry_snapshot = dict(orchestrator_registry_module.ENGINE_DEPENDENCY_REGISTRY)

    try:
        yield
    finally:
        orchestrator_registry_module.ENGINE_DEPENDENCY_REGISTRY.clear()
        orchestrator_registry_module.ENGINE_DEPENDENCY_REGISTRY.update(orchestrator_registry_snapshot)
        try:
            from app.engines.analysis_orchestrator.execution_plan import _reset_plan_cache_for_tests

            _reset_plan_cache_for_tests()
        except ImportError:  # pragma: no cover
            pass

        # LIFO -- Milestone 4.4 registry'leri (report_registry/dashboard_
        # registry) EN SON import edildiği için EN ÖNCE restore edilir.
        report_registry_module.REPORT_SECTION_REGISTRY.clear()
        report_registry_module.REPORT_SECTION_REGISTRY.update(report_section_registry_snapshot)
        report_registry_module.REPORT_TYPE_REGISTRY.clear()
        report_registry_module.REPORT_TYPE_REGISTRY.update(report_type_registry_snapshot)
        report_registry_module.REPORT_TYPE_LEGAL_PROFILES.clear()
        report_registry_module.REPORT_TYPE_LEGAL_PROFILES.update(report_type_legal_profiles_snapshot)
        dashboard_registry_module.DASHBOARD_WIDGET_REGISTRY.clear()
        dashboard_registry_module.DASHBOARD_WIDGET_REGISTRY.update(dashboard_widget_registry_snapshot)

        # LIFO (devam) -- Recommendation Engine (4.3F) EN SON import edildiği için
        # EN ÖNCE restore edilir.
        recommendation_registry_module.RECOMMENDATION_RULES_BY_CODE.clear()
        recommendation_registry_module.RECOMMENDATION_RULES_BY_CODE.update(
            recommendation_rules_by_code_snapshot
        )
        recommendation_registry_module.RECOMMENDATION_RULES = recommendation_rules_snapshot
        recommendation_registry_module.RECOMMENDATION_CONFLICT_PAIRS = (
            recommendation_conflict_pairs_snapshot
        )
        recommendation_registry_module.RECOMMENDATION_MUTUALLY_EXCLUSIVE_GROUPS = (
            recommendation_mutually_exclusive_groups_snapshot
        )
        recommendation_registry_module.RECOMMENDATION_CATEGORY_WEIGHT_PROFILES.clear()
        recommendation_registry_module.RECOMMENDATION_CATEGORY_WEIGHT_PROFILES.update(
            recommendation_category_weight_profiles_snapshot
        )
        recommendation_registry_module.BANKING_FLAG_TO_RATIO_OVERLAP.clear()
        recommendation_registry_module.BANKING_FLAG_TO_RATIO_OVERLAP.update(
            banking_flag_to_ratio_overlap_snapshot
        )

        ratio_formulas_module.RATIO_REGISTRY.clear()
        ratio_formulas_module.RATIO_REGISTRY.update(ratio_registry_snapshot)
        benchmark_types_module.BENCHMARK_REGISTRY.clear()
        benchmark_types_module.BENCHMARK_REGISTRY.update(benchmark_registry_snapshot)
        health_score_registry_module.RATIO_SCORE_WEIGHTS.clear()
        health_score_registry_module.RATIO_SCORE_WEIGHTS.update(ratio_score_weights_snapshot)
        credit_score_registry_module.CREDIT_RATIO_SCORE_WEIGHTS.clear()
        credit_score_registry_module.CREDIT_RATIO_SCORE_WEIGHTS.update(
            credit_ratio_score_weights_snapshot
        )
        credit_score_registry_module.CREDIT_CATEGORY_WEIGHT_PROFILES.clear()
        credit_score_registry_module.CREDIT_CATEGORY_WEIGHT_PROFILES.update(
            credit_category_weight_profiles_snapshot
        )
        # Bu üçü TUPLE (immutable) -- clear()/update() UYGULANAMAZ. Bir
        # test modül attribute'unu (ör. `credit_score_registry_module.
        # CREDIT_HARD_FAIL_RULES = ...`) yeniden ATASA bile, referansı
        # snapshot'takine GERİ ATAYARAK aynı garanti sağlanır.
        credit_score_registry_module.CREDIT_HARD_FAIL_RULES = credit_hard_fail_rules_snapshot
        credit_score_registry_module.CREDIT_CRITICAL_OVERRIDE_RULES = (
            credit_critical_override_rules_snapshot
        )
        credit_score_registry_module.CREDIT_BANKING_LENS_SIGNAL_RULES = (
            credit_banking_lens_signal_rules_snapshot
        )


@pytest.fixture()
def engine() -> Generator[Engine, None, None]:
    test_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)

    yield test_engine

    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


@pytest.fixture()
def db_session(engine: Engine) -> Generator[Session, None, None]:
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(engine: Engine) -> Generator[TestClient, None, None]:
    testing_session_local = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        session = testing_session_local()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    # Legacy API contract tests predate 5.0E. Security behavior has its own
    # explicit suite; this TEST-only override cannot enter production wiring.
    def bypass_legacy_security(request: Request):
        request.state.legacy_security_test_bypass = True

    app.dependency_overrides[require_legacy_route_security] = bypass_legacy_security
    app.dependency_overrides[resolve_legacy_tenant_id] = lambda: None

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
