"""Агент «Критик» (проверяющий): валидирует спецификацию до запуска и выводы аналитика после."""
from __future__ import annotations

from ..messages import Issue, ReviewVerdict
from ..tools.base import Tool
from ..tools.stats_tools import holm, paired_test
from ..tools.validation import check_claims, validate_spec
from .base import Agent


def _recompute(results: list[dict]) -> tuple[list[dict], dict]:
    """Независимый пересчёт статистики критиком (не доверяем числам аналитика)."""
    by = {r["strategy"]: r["final_shares"] for r in results}
    names = list(by)
    pairs = []
    if "baseline" in by:
        pairs += [(s, "baseline") for s in names if s != "baseline"]
    act = [s for s in names if s != "baseline"]
    pairs += [(a, b) for i, a in enumerate(act) for b in act[i + 1:]]
    comps = [{"a": a, "b": b, **paired_test(by[a], by[b])} for a, b in pairs]
    for c, p in zip(comps, holm([c["p_value"] for c in comps])):
        c["p_holm"] = p
    means = {s: sum(v) / len(v) * 100 for s, v in by.items()}
    return comps, means


class Critic(Agent):
    name = "critic"
    role = "Проверяет корректность: спецификацию до симуляции и соответствие выводов числам после анализа"
    inputs = "review_spec {spec} | review_analysis {analysis, simulation_results}"
    outputs = "ReviewVerdict {approved, issues[]}"
    done_when = "Вынесен вердикт; при ошибках каждая снабжена полем и предлагаемым исправлением"

    def build_tools(self):
        return [
            Tool("validate_spec", "Проверка границ, вычислительного объёма и логики сценария", lambda spec: validate_spec(spec)),
            Tool("recompute_stats", "Независимый пересчёт парных тестов", lambda results: _recompute(results)),
            Tool("check_claims", "Сверка утверждений аналитика с пересчитанными числами", check_claims),
        ]

    def handle(self, payload_type, payload):
        if payload_type == "review_spec":
            target = "scenario_spec"
            issues = self.call_tool("validate_spec", spec=payload["spec"])
        else:
            target = "analysis"
            comps, means = self.call_tool("recompute_stats", results=payload["simulation_results"]["results"])
            issues = self.call_tool("check_claims", analysis=payload["analysis"], comparisons_truth=comps, means_pp=means)

        forced = "critic_reject" in self.s.faults
        errors = [i for i in issues if i["severity"] == "error"]

        def heuristic():
            iss = [Issue(**i) for i in issues]
            if forced:
                iss.append(Issue(severity="error", field="forced", message="Внедрённый отказ: критик отклоняет всегда"))
            ok = not errors and not forced
            comment = "Замечаний, блокирующих продолжение, нет." if ok else f"Найдено ошибок: {len(iss) - len([i for i in iss if i.severity == 'warning'])}"
            return ReviewVerdict(target=target, approved=ok, issues=iss, comment=comment)

        verdict = self.think({"target": target, "tool_findings": issues, "payload": payload}, ReviewVerdict, heuristic,
                             label=f"review_{target}")
        # Жёсткое правило: LLM не может одобрить то, что провалило детерминированную проверку
        if errors and verdict.approved:
            verdict.approved = False
            verdict.issues = [Issue(**i) for i in issues]
            verdict.comment += " [одобрение отменено: валидатор нашёл ошибки]"
        if forced:
            verdict.approved = False
        return "ReviewVerdict", verdict
