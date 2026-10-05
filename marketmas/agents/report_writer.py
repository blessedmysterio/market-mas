"""Агент «Автор отчёта»: собирает итоговый Markdown-отчёт для маркетолога."""
from __future__ import annotations

from pathlib import Path

from ..messages import ExecutiveSummary, Report
from ..tools.base import Tool
from .analyst import NAMES_RU
from .base import Agent


def render_markdown(*, summary: dict, spec: dict, ctx: dict, sim: dict, analysis: dict, reviews: dict) -> str:
    L = [f"# {summary['headline']}", "", summary["summary"], ""]
    L += ["## Вопрос и постановка эксперимента", "", f"**Вопрос:** {spec['research_question']}", "",
          "| Параметр | Значение |", "|---|---|",
          f"| Отрасль / фокальный бренд | {ctx['industry']} / {ctx['focus_brand']} |",
          f"| Стратегии | {', '.join(NAMES_RU[s] for s in spec['strategies'])} |",
          f"| Бюджет | {spec['budget_kzt']:,.0f} ₸ |".replace(",", " "),
          f"| Сеть | Barabási–Albert, N = {spec['n_agents']}, m = {spec['ba_m']} |",
          f"| Горизонт / шаг вмешательства | {spec['n_steps']} / {spec['intervention_step']} |",
          f"| Прогонов (парные, общие сиды) | {sim['n_runs']} |"]
    if spec.get("shock"):
        L.append(f"| Репутационный кризис | шаг {spec['shock']['at_step']}, падение качества {spec['shock']['quality_drop']:.2f} |")
    it = spec.get("intensities", {})
    L.append(f"| Интенсивности | хабов {it.get('hub_seeds')}, случайных {it.get('random_seeds')}, "
             f"реклама +{it.get('ad_boost')}, скидка {it.get('price_cut', 0) * 100:.1f}% |")
    L += ["", "## Результаты", "", "| Стратегия | Средняя итоговая доля, % |", "|---|---|"]
    for r in sim["results"]:
        m = sum(r["final_shares"]) / len(r["final_shares"]) * 100
        mark = " **(лучшая)**" if r["strategy"] == analysis["best_strategy"] else ""
        L.append(f"| {NAMES_RU[r['strategy']]}{mark} | {m:.2f} |")
    L += ["", "| Сравнение | Δ, п.п. | 95% ДИ | t | p (Холм) | d_z |", "|---|---|---|---|---|---|"]
    for c in analysis["comparisons"]:
        L.append(f"| {NAMES_RU[c['a']]} vs {NAMES_RU[c['b']]} | {c['delta_pp']:+.2f} | "
                 f"[{c['ci95_pp'][0]:+.2f}; {c['ci95_pp'][1]:+.2f}] | {c['t_stat']:.2f} | {c['p_holm']:.3g} | {c['cohen_dz']:.2f} |")
    if analysis.get("chart_file"):
        L += ["", f"![Траектории доли]({Path(analysis['chart_file']).name})"]
    L += ["", "## Интерпретация", "", analysis["interpretation"], "", "## Рекомендация", "", analysis["recommendation"], ""]
    if summary.get("next_steps"):
        L += ["## Следующие шаги", ""] + [f"- {s}" for s in summary["next_steps"]] + [""]
    L += ["## Ограничения", ""] + [f"- {c}" for c in analysis.get("caveats", [])]
    L += [f"- {n}" for n in ctx.get("data_notes", [])] + [f"- Допущение: {a}" for a in spec.get("assumptions", [])]
    L += ["", "## Проверка критиком", ""]
    for k, v in reviews.items():
        L.append(f"- {k}: {'одобрено' if v['approved'] else 'отклонено'} (ревизий: {v.get('revisions', 0)}). {v.get('comment', '')}")
    L += ["", "## Источники", ""]
    for r in ctx.get("references", []):
        doi = f" https://doi.org/{r['doi']}" if r.get("doi") else ""
        L.append(f"- {r['title']} ({r.get('year') or 'н.д.'}). *{r.get('venue') or ''}*.{doi} [{r['source']}]")
    return "\n".join(L) + "\n"


class ReportWriter(Agent):
    name = "report_writer"
    role = "Пишет итоговый отчёт: резюме для руководителя, таблицы, график, ограничения, источники"
    inputs = "report_task {spec, market_context, simulation_results, analysis, reviews}"
    outputs = "Report {path, headline}"
    done_when = "Файл report.md записан в outputs/<run_id>/"

    def build_tools(self):
        out_dir = self.s.outputs_dir / self.rt.run_id

        def write_file(name: str, content: str) -> str:
            out_dir.mkdir(parents=True, exist_ok=True)
            p = out_dir / name
            p.write_text(content, encoding="utf-8")
            return str(p)

        return [
            Tool("render_markdown", "Сборка Markdown-отчёта по шаблону", render_markdown),
            Tool("write_file", "Запись файла в каталог прогона", write_file, external=True),
        ]

    def handle(self, payload_type, payload):
        a, spec = payload["analysis"], payload["spec"]
        best = a["best_strategy"]
        delta = next((c["delta_pp"] for c in a["comparisons"] if c["a"] == best and c["b"] == "baseline"), None)

        def heuristic():
            head = f"{NAMES_RU[best].capitalize()} — лучшая стратегия в сценарии «{spec['title']}»"
            summ = (f"Агентная модель ({payload['simulation_results']['n_runs']} парных прогонов) показывает, что "
                    f"«{NAMES_RU[best]}» даёт наибольшую итоговую долю фокального бренда"
                    + (f" (+{delta:.2f} п.п. к варианту без вмешательства)." if delta is not None else ".")
                    + " " + a["recommendation"])
            steps = ["Откалибровать параметры рынка по реальным данным (доли, отток, CPM)",
                     "Проверить устойчивость вывода при другой топологии сети и бюджете ±50%",
                     "Спланировать пилот с контрольной группой для эмпирической проверки"]
            return ExecutiveSummary(headline=head, summary=summ, next_steps=steps)

        summary = self.think({"analysis": a, "spec": spec}, ExecutiveSummary, heuristic, label="write_summary")
        md = self.call_tool("render_markdown", summary=summary.model_dump(), spec=spec, ctx=payload["market_context"],
                            sim=payload["simulation_results"], analysis=a, reviews=payload["reviews"])
        path = self.call_tool("write_file", name="report.md", content=md)
        return "Report", Report(path=path, headline=summary.headline)
