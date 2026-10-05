"""Типизированные сообщения и полезные нагрузки, которыми обмениваются агенты (pydantic → JSON)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal[
    "orchestrator",
    "market_researcher",
    "scenario_designer",
    "critic",
    "simulation_engineer",
    "analyst",
    "report_writer",
    "user",
]

StrategyName = Literal[
    "baseline",
    "hub_seeding",
    "random_seeding",
    "mass_media",
    "price_cut",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AgentMessage(BaseModel):
    """Конверт сообщения. payload — сериализованная модель из этого модуля."""

    msg_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    run_id: str
    step: int
    sender: AgentName
    recipient: AgentName
    type: Literal["task", "result", "error", "review"]
    payload_type: str
    payload: dict[str, Any]
    ts: str = Field(default_factory=_now)


# ---------------------------------------------------------------- Orchestrator
class PlanStep(BaseModel):
    agent: AgentName
    task: str = Field(description="Короткое описание подзадачи")


class Plan(BaseModel):
    in_scope: bool = Field(description="Относится ли запрос к маркетинговому моделированию")
    reason: str = ""
    steps: list[PlanStep] = Field(default_factory=list)


# ---------------------------------------------------------- Market researcher
class ResearchQuery(BaseModel):
    industry: str = Field(description="Отрасль из справочника: telecom, fmcg, fintech, ecommerce, auto, fashion, foodtech")
    literature_query: str = Field(description="Поисковый запрос на английском для OpenAlex")
    focus_brand: str = "Brand A"


class Reference(BaseModel):
    title: str
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    cited_by: int | None = None
    source: Literal["openalex", "cache"] = "openalex"


class MarketContext(BaseModel):
    industry: str
    focus_brand: str
    brands: list[str]
    base_shares: list[float]
    quality: list[float]
    price: list[float]
    social_weight: float
    price_sensitivity: float
    churn_rate: float
    cpm_kzt: float
    seed_cost_kzt: float
    references: list[Reference] = Field(default_factory=list)
    data_notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------- Scenario designer
class Shock(BaseModel):
    at_step: int = Field(ge=0)
    quality_drop: float = Field(ge=0, le=1, description="Падение качества фокального бренда (репутационный кризис)")


class ScenarioSpec(BaseModel):
    title: str
    research_question: str
    strategies: list[StrategyName]
    budget_kzt: float
    n_agents: int
    ba_m: int = 3
    n_steps: int = 60
    n_runs: int = 30
    intervention_step: int = 5
    shock: Shock | None = None
    intensities: dict[str, float] = Field(default_factory=dict, description="Параметры интенсивности стратегий, считаются инструментом")
    assumptions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------- Critic
class Issue(BaseModel):
    severity: Literal["error", "warning"]
    field: str
    message: str
    suggested: Any | None = None


class ReviewVerdict(BaseModel):
    target: Literal["scenario_spec", "analysis"]
    approved: bool
    issues: list[Issue] = Field(default_factory=list)
    comment: str = ""


# ---------------------------------------------------------- Simulation engineer
class ExperimentPlan(BaseModel):
    n_runs: int
    base_seed: int = 42
    common_random_numbers: bool = True
    rationale: str = ""


class StrategyResult(BaseModel):
    strategy: StrategyName
    final_shares: list[float] = Field(description="Доля фокального бренда в конце, по прогонам (0..1)")
    mean_trajectory: list[float]
    seeds_used: int = 0


class SimulationResults(BaseModel):
    spec_title: str
    n_runs: int
    n_agents: int
    results: list[StrategyResult]
    results_file: str | None = None
    elapsed_s: float = 0.0


# ---------------------------------------------------------------------- Analyst
class Comparison(BaseModel):
    a: StrategyName
    b: StrategyName
    mean_a_pp: float
    mean_b_pp: float
    delta_pp: float
    t_stat: float
    p_value: float
    p_holm: float
    ci95_pp: tuple[float, float]
    cohen_dz: float


class Claim(BaseModel):
    a: StrategyName
    b: StrategyName
    delta_pp: float
    significant: bool


class Analysis(BaseModel):
    best_strategy: StrategyName
    comparisons: list[Comparison] = Field(default_factory=list, description="Заполняется инструментом compare_strategies")
    claims: list[Claim]
    interpretation: str
    recommendation: str
    caveats: list[str] = Field(default_factory=list)
    chart_file: str | None = None


# ---------------------------------------------------------------- Report writer
class ExecutiveSummary(BaseModel):
    headline: str
    summary: str
    next_steps: list[str] = Field(default_factory=list)


class Report(BaseModel):
    path: str
    headline: str


class RunOutcome(BaseModel):
    run_id: str
    status: Literal["completed", "out_of_scope", "failed", "timeout", "step_limit", "revision_limit"]
    message: str
    report_path: str | None = None
    best_strategy: str | None = None
    revisions: dict[str, int] = Field(default_factory=dict)
    log_file: str | None = None
