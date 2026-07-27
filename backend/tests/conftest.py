"""
SQLite in-memory fixture'ları. Kapsam: API sözleşmesi testleri.
PostgreSQL'e özgü davranışlar için bkz. test_postgres_integration.py ve
tests/README.md.

Ayrıca (Milestone 4.3D final doğrulama): `RATIO_REGISTRY` / `BENCHMARK_
REGISTRY` / `RATIO_SCORE_WEIGHTS` gibi process-genelinde PAYLAŞILAN global
mutable registry yapıları için autouse bir "snapshot + kesin geri yükleme"
fixture'ı -- bkz. aşağıdaki `_snapshot_shared_engine_registries`.

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
"""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  -- Base.metadata'yı doldurmak için gerekli
from app.db.base import Base
from app.db.session import get_db
from app.main import app


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

    ratio_registry_snapshot = dict(ratio_formulas_module.RATIO_REGISTRY)
    benchmark_registry_snapshot = dict(benchmark_types_module.BENCHMARK_REGISTRY)
    ratio_score_weights_snapshot = dict(health_score_registry_module.RATIO_SCORE_WEIGHTS)
    try:
        yield
    finally:
        ratio_formulas_module.RATIO_REGISTRY.clear()
        ratio_formulas_module.RATIO_REGISTRY.update(ratio_registry_snapshot)
        benchmark_types_module.BENCHMARK_REGISTRY.clear()
        benchmark_types_module.BENCHMARK_REGISTRY.update(benchmark_registry_snapshot)
        health_score_registry_module.RATIO_SCORE_WEIGHTS.clear()
        health_score_registry_module.RATIO_SCORE_WEIGHTS.update(ratio_score_weights_snapshot)


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

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
