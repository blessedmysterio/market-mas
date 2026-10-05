"""Агент «Инженер симуляции»: планирует эксперимент и прогоняет агентную модель (выполнение кода)."""
from __future__ import annotations

import json
import time

from ..messages import ExperimentPlan, SimulationResults, StrategyResult
from ..tools.base import Tool
from ..tools.simulator import simulate_strategy
from .base import Agent

SEC_PER_UNIT = 1.6e-7  # оценка: секунд на (агент × шаг) одного прогона


class SimulationEngineer(Agent):
    name = "simulation_engineer"
    role = "Планирует вычислительный эксперимент (прогоны, сиды, CRN) и выполняет агентную модель"
    inputs = "simulate_task {spec, market_context}"
    outputs = "SimulationResults (доли по прогонам, средние траектории, путь к файлу)"
    done_when = "Все стратегии прогнаны на одинаковых сидах, результаты сохранены в JSON"

    def build_tools(self):
        out_dir = self.s.outputs_dir / self.rt.run_id
        self._flaky_left = 1 if "sim_flaky" in self.s.faults else 0

        def sim(**kw):
            if self._flaky_left > 0:
                self._flaky_left -= 1
                raise RuntimeError("Внедрённый временный сбой симулятора (sim_flaky)")
            return simulate_strategy(slow="slow_sim" in self.s.faults, **kw)

        def save(results: dict) -> str:
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / "simulation_results.json"
            p.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
            return str(p)

        return [
            Tool("simulate_strategy", "Прогон агентной модели BA-сети для одной стратегии", sim, external=True),
            Tool("save_results", "Сохранение результатов в JSON-файл", save, external=True),
        ]

    def handle(self, payload_type, payload):
        spec, ctx = payload["spec"], payload["market_context"]
        k = len(spec["strategies"])
        remaining = self.rt.budget.remaining_s

        def heuristic():
            per_run = spec["n_agents"] * spec["n_steps"] * k * SEC_PER_UNIT
            affordable = int(0.6 * remaining / max(per_run, 1e-6))
            n_runs = max(10, min(spec["n_runs"], affordable))
            why = f"Оценка {per_run:.2f} с на прогон всех стратегий; осталось {remaining:.0f} с"
            if n_runs < spec["n_runs"]:
                why += f" — число прогонов сокращено с {spec['n_runs']} до {n_runs}"
            return ExperimentPlan(n_runs=n_runs, base_seed=42, common_random_numbers=True, rationale=why)

        plan = self.think({"spec": spec, "remaining_s": round(remaining, 1)}, ExperimentPlan, heuristic, label="plan_experiment")
        plan.n_runs = max(10, min(plan.n_runs, 100))
        t0 = time.monotonic()
        results = []
        for strat in spec["strategies"]:
            r = self.call_tool("simulate_strategy", spec=spec, ctx=ctx, strategy=strat, n_runs=plan.n_runs,
                               base_seed=plan.base_seed, deadline_s=self.rt.budget.remaining_s)
            results.append(StrategyResult(**r))
        sim = SimulationResults(spec_title=spec["title"], n_runs=plan.n_runs, n_agents=spec["n_agents"],
                                results=results, elapsed_s=round(time.monotonic() - t0, 2))
        sim.results_file = self.call_tool("save_results", results={"plan": plan.model_dump(), **sim.model_dump()})
        return "SimulationResults", sim
