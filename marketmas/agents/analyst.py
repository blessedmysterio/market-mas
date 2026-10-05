"""Агент «Аналитик»: статистика (парные t-тесты, поправка Холма), график, интерпретация и рекомендация."""
from __future__ import annotations

from ..messages import Analysis, Claim, Comparison
from ..tools.base import Tool
from ..tools.stats_tools import holm, paired_test, plot_trajectories
from .base import Agent

NAMES_RU = {"baseline": "без вмешательства", "hub_seeding": "посев через хабов", "random_seeding": "случайный посев",
            "mass_media": "массовая реклама", "price_cut": "снижение цены"}


def compare_strategies(results: list[dict]) -> list[dict]:
    by = {r["strategy"]: r["final_shares"] for r in results}
    names = list(by)
    pairs = [(s, "baseline") for s in names if s != "baseline"] if "baseline" in by else []
    act = [s for s in names if s != "baseline"]
    pairs += [(a, b) for i, a in enumerate(act) for b in act[i + 1:]]
    comps = [{"a": a, "b": b, **paired_test(by[a], by[b])} for a, b in pairs]
    for c, p in zip(comps, holm([c["p_value"] for c in comps])):
        c["p_holm"] = p
    return comps


class Analyst(Agent):
    name = "analyst"
    role = "Проводит статистический анализ результатов симуляции и формулирует выводы и рекомендацию"
    inputs = "analyze_task {spec, simulation_results, [review]}"
    outputs = "Analysis (сравнения, утверждения, лучшая стратегия, рекомендация, ограничения, график)"
    done_when = "Все пары стратегий сравнены с поправкой на множественность, построен график, сформулированы выводы"

    def build_tools(self):
        out_dir = self.s.outputs_dir / self.rt.run_id
        return [
            Tool("compare_strategies", "Парные t-тесты всех пар + поправка Холма", lambda results: compare_strategies(results)),
            Tool("plot_chart", "График средних траекторий доли бренда",
                 lambda results, title, intervention_step, shock_step=None: plot_trajectories(
                     results, out_dir / "trajectories.png", title, intervention_step, shock_step)),
        ]

    def handle(self, payload_type, payload):
        spec, sim = payload["spec"], payload["simulation_results"]
        review = payload.get("review")
        prev = payload.get("previous_analysis")
        if review and prev:  # ревизия: числа уже посчитаны, исправляем только утверждения
            comps = [c for c in prev["comparisons"]]
            chart = prev.get("chart_file")
        else:
            comps = self.call_tool("compare_strategies", results=sim["results"])
            chart = self.call_tool("plot_chart", results=sim["results"], title=spec["title"],
                                   intervention_step=spec["intervention_step"],
                                   shock_step=(spec.get("shock") or {}).get("at_step"))
        means = {r["strategy"]: sum(r["final_shares"]) / len(r["final_shares"]) * 100 for r in sim["results"]}
        hallucinate = "analyst_hallucinate" in self.s.faults and not review

        def heuristic():
            best = max(means, key=means.get)
            claims = [Claim(a=c["a"], b=c["b"], delta_pp=c["delta_pp"], significant=c["p_holm"] < 0.05) for c in comps]
            if hallucinate and claims:  # внедрённая «галлюцинация» — критик должен поймать
                claims[0].delta_pp += 2.5
            sig_vs_base = [c for c in comps if c["b"] == "baseline" and c["p_holm"] < 0.05 and c["delta_pp"] > 0]
            lines = [f"«{NAMES_RU[c['a']]}» vs «{NAMES_RU[c['b']]}»: Δ = {c['delta_pp']:+.2f} п.п. "
                     f"(95% ДИ {c['ci95_pp'][0]:+.2f}…{c['ci95_pp'][1]:+.2f}; p_Holm = {c['p_holm']:.3g}; d_z = {c['cohen_dz']:.2f})"
                     for c in comps]
            interp = (f"Лучшая стратегия по итоговой доле фокального бренда — «{NAMES_RU[best]}» "
                      f"({means[best]:.2f}%). Парные сравнения: " + "; ".join(lines) + ".")
            if best == "baseline":
                rec = "Ни одна стратегия не превзошла отсутствие вмешательства — бюджет стоит перераспределить или пересмотреть гипотезу."
            else:
                second = sorted((s for s in means if s != best), key=means.get, reverse=True)
                rec = f"Рекомендуется «{NAMES_RU[best]}»"
                runner = next((c for c in comps if {c['a'], c['b']} == {best, second[0]}), None) if second else None
                if runner and runner["p_holm"] >= 0.05:
                    rec += f"; однако отличие от «{NAMES_RU[second[0]]}» статистически незначимо — выбор между ними определяется стоимостью исполнения"
                rec += "."
            caveats = ["Параметры рынка иллюстративные и требуют калибровки по реальным данным",
                       "Модель упрощает поведение: логит-выбор, статичная сеть Barabási–Albert",
                       f"Число прогонов {sim['n_runs']}; p-значения отражают вариативность модели, а не рынка"]
            if not sig_vs_base and best != "baseline":
                caveats.append("Ни одно улучшение относительно baseline не значимо после поправки Холма")
            return Analysis(best_strategy=best, comparisons=[Comparison(**c) for c in comps], claims=claims,
                            interpretation=interp, recommendation=rec, caveats=caveats, chart_file=chart)

        task = {"spec": spec, "comparisons": comps, "means_pp": means, "review": review}
        analysis = self.think(task, Analysis, heuristic, label="revise_analysis" if review else "interpret")
        analysis.comparisons = [Comparison(**c) for c in comps]  # числа — только из инструмента
        analysis.chart_file = chart
        return "Analysis", analysis
