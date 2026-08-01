"""Closed, non-dispatch result ownership registry from design section 5.2."""

from __future__ import annotations

import enum
from dataclasses import dataclass

from app.engines.analysis_orchestrator.types import EngineCode
from app.models.enums import AnalysisType


class ResultOwner(str, enum.Enum):
    FINANCIAL_ANALYSIS_RESULT = "financial_analysis_result"
    ORCHESTRATION_ARTIFACT = "orchestration_artifact"


@dataclass(frozen=True)
class ResultOwnership:
    owner: ResultOwner
    analysis_type: AnalysisType | None = None


RESULT_OWNERSHIP_REGISTRY = {
    EngineCode.FS_BALANCE_SHEET: ResultOwnership(ResultOwner.FINANCIAL_ANALYSIS_RESULT, AnalysisType.BALANCE_SHEET),
    EngineCode.FS_INCOME_STATEMENT: ResultOwnership(ResultOwner.FINANCIAL_ANALYSIS_RESULT, AnalysisType.INCOME_STATEMENT),
    EngineCode.RATIO: ResultOwnership(ResultOwner.FINANCIAL_ANALYSIS_RESULT, AnalysisType.FINANCIAL_RATIOS),
    EngineCode.BENCHMARK: ResultOwnership(ResultOwner.ORCHESTRATION_ARTIFACT),
    EngineCode.HEALTH_SCORE: ResultOwnership(ResultOwner.ORCHESTRATION_ARTIFACT),
    EngineCode.CREDIT_SCORE: ResultOwnership(ResultOwner.ORCHESTRATION_ARTIFACT),
    EngineCode.RECOMMENDATION: ResultOwnership(ResultOwner.ORCHESTRATION_ARTIFACT),
    EngineCode.EXECUTIVE_REPORT: ResultOwnership(ResultOwner.ORCHESTRATION_ARTIFACT),
    EngineCode.DASHBOARD: ResultOwnership(ResultOwner.ORCHESTRATION_ARTIFACT),
    EngineCode.RENDER_CONTRACT: ResultOwnership(ResultOwner.ORCHESTRATION_ARTIFACT),
}
