"""Агент «Дизайнер сценариев»: переводит маркетинговый вопрос в формальную спецификацию эксперимента."""
from __future__ import annotations

from .. import heuristics as H
from ..messages import ScenarioSpec, Shock
from ..tools.base import Tool
from ..tools.design_tools import budget_to_intensity, strategy_catalog
from ..tools.validation import BOUNDS
from .base import Agent

DEFAULTS = {"budget_kzt": 30_000_000, "n_agents": 1000, "n_runs": 30, "n_steps": 60}


class ScenarioDesigner(Agent):
    name = "scenario_designer"
    role = "Формализует бриф в ScenarioSpec: стратегии, бюджет, размер сети, горизонт, число прогонов, кризис"
    inputs = "design_task {brief, market_context, [review], [previous_spec]}"
    outputs = "ScenarioSpec"
    done_when = "Спецификация собрана, интенсивности рассчитаны инструментом budget_to_intensity"

    def build_tools(self):
        return [
            Tool("strategy_catalog", "Каталог доступных стратегий и правил сравнения", lambda: strategy_catalog()),
            Tool("budget_to_intensity", "Перевод бюджета (KZT) в интенсивность вмешательства", budget_to_intensity),
        ]

    def handle(self, payload_type, payload):
        brief = payload["brief"]
        ctx = payload["market_context"]
        review = payload.get("review")
        prev = payload.get("previous_spec")
        catalog = None if review else self.call_tool("strategy_catalog")

        def heuristic():
            if review and prev:  # ревизия: применяем исправления критика
                spec = dict(prev)
                for iss in review["issues"]:
                    if iss["severity"] != "error" or iss.get("suggested") is None:
                        continue
                    field = iss["field"]
                    if field == "shock.at_step" and spec.get("shock"):
                        spec["shock"] = {**spec["shock"], "at_step": iss["suggested"]}
                    elif field in spec:
                        spec[field] = iss["suggested"]
                spec["assumptions"] = list(spec.get("assumptions", [])) + [
                    f"Ревизия по замечаниям критика: {', '.join(sorted({i['field'] for i in review['issues'] if i['severity'] == 'error'}))}"]
                return ScenarioSpec.model_validate(spec)
            nums = {**DEFAULTS, **H.parse_numbers(brief)}
            strategies = H.detect_strategies(brief)
            crisis = H.detect_crisis(brief)
            assumptions = [f"Отрасль: {ctx['industry']}; фокальный бренд — {ctx['focus_brand']}",
                           "Все активные стратегии сравниваются при одинаковом бюджете"]
            for k, v in DEFAULTS.items():
                if k not in H.parse_numbers(brief):
                    assumptions.append(f"{k} не указан в брифе — принято {v:,}".replace(",", " "))
            active = [s for s in strategies if s != "baseline"]
            title = ("Кризис: " if crisis else "") + " vs ".join(active or ["baseline"]) + f" ({ctx['industry']})"
            return ScenarioSpec(
                title=title, research_question=brief.strip()[:300], strategies=strategies,
                budget_kzt=float(nums["budget_kzt"]), n_agents=int(nums["n_agents"]), n_runs=int(nums["n_runs"]),
                n_steps=int(nums["n_steps"]), intervention_step=5,
                shock=Shock(at_step=3, quality_drop=0.15) if crisis else None, assumptions=assumptions,
            )

        task = {"brief": brief, "market_context": ctx, "catalog": catalog, "bounds": BOUNDS,
                "review": review, "previous_spec": prev}
        spec = self.think(task, ScenarioSpec, heuristic, label="revise_spec" if review else "design_spec")
        extra = self.rt.state.get(self.rt.run_id, "market_extra") or {"segment_size": 100000, "arpu_kzt": 4000}
        n_for_intensity = min(max(spec.n_agents, BOUNDS["n_agents"][0]), BOUNDS["n_agents"][1])
        spec.intensities = self.call_tool(
            "budget_to_intensity", budget_kzt=spec.budget_kzt, n_agents=n_for_intensity,
            seed_cost_kzt=ctx["seed_cost_kzt"], segment_size=extra["segment_size"], cpm_kzt=ctx["cpm_kzt"],
            arpu_kzt=extra["arpu_kzt"])
        return "ScenarioSpec", spec
