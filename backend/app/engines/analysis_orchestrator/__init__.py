"""
Milestone 5.0A -- Analysis Orchestrator.

Bu paket, docs/FINOS_MILESTONE_5_0A_ANALYSIS_ORCHESTRATOR_DESIGN.md (v2,
denetim sonrasi FINAL tasarim) dokumaninin implementasyonudur. Paket
SIFIR sqlalchemy/fastapi/pydantic bagimliligi tasir -- diger app.engines.**
paketleriyle ayni disiplin (bkz. app/engines/protocol.py).

Alt moduller:
  - types.py            : enum'lar + frozen dataclass sozlesmeleri
  - registry.py          : ENGINE_DEPENDENCY_REGISTRY (yalnizca metadata)
  - dispatch.py           : ORCHESTRATOR_ENGINE_DISPATCH (dogrudan callable baglama)
  - execution_plan.py     : DAG'dan turetilmis deterministik siralama
  - fingerprint.py         : SHA-256 canonical-JSON girdi parmak izi
  - service.py             : run_orchestration() -- tek genel API
"""
