"""Оркестратор: строит план и распределяет задачи. Предметной работы не выполняет —
не считает статистику, не трогает модель, не пишет текст отчёта. Только маршрутизация,
циклы ревизии по вердикту критика, лимиты и итоговый статус."""
from __future__ import annotations

from pydantic import BaseModel

from .. import heuristics as H
from ..limits import RunAborted
from ..messages import (AgentMessage, Analysis, MarketContext, Plan, PlanStep, Report, ReviewVerdict, RunOutcome,
                        ScenarioSpec, SimulationResults)
from ..tools.base import ToolError
from .analyst import Analyst
from .base import Agent
from .critic import Critic
from .market_researcher import MarketResearcher
from .report_writer import ReportWriter
from .scenario_designer import ScenarioDesigner
from .simulation_engineer import SimulationEngineer

CANONICAL = [
    PlanStep(agent="market_researcher", task="Собрать параметры рынка и литературу"),
    PlanStep(agent="scenario_designer", task="Формализовать сценарий эксперимента"),
    PlanStep(agent="critic", task="Проверить спецификацию до запуска"),
    PlanStep(agent="simulation_engineer", task="Прогнать агентную модель"),
    PlanStep(agent="analyst", task="Статистический анализ и рекомендация"),
    PlanStep(agent="critic", task="Сверить выводы с числами"),
    PlanStep(agent="report_writer", task="Подготовить отчёт"),
]


class Orchestrator(Agent):
    name = "orchestrator"
    role = "Планирует конвейер, распределяет задачи агентам, управляет циклами ревизии и лимитами"
    inputs = "Бриф пользователя (текст)"
    outputs = "RunOutcome {status, message, report_path}"
    done_when = "Отчёт готов или прогон остановлен с понятным статусом (out_of_scope/лимит/ошибка)"

    def __init__(self, rt):
        super().__init__(rt)
        self.agents: dict[str, Agent] = {a.name: a for a in (
            MarketResearcher(rt), ScenarioDesigner(rt), Critic(rt), SimulationEngineer(rt), Analyst(rt), ReportWriter(rt))}
        self.revisions = {"scenario_spec": 0, "analysis": 0}

    # ------------------------------------------------------------------ messaging
    def dispatch(self, recipient: str, payload_type: str, payload: dict) -> BaseModel:
        rt = self.rt
        rt.budget.guard_repeat(recipient, {"t": payload_type, "p": payload})
        rt.budget.check_time()
        task = AgentMessage(run_id=rt.run_id, step=rt.budget.steps, sender="orchestrator", recipient=recipient,
                            type="task", payload_type=payload_type, payload=payload)
        rt.state.add_message(task)
        rt.logger.write(agent="orchestrator", kind="message", name=f"→ {recipient}", input={"type": payload_type})
        rt.state.update_run(rt.run_id, step=rt.budget.steps)
        out_type, result = self.agents[recipient].handle(payload_type, payload)
        reply = AgentMessage(run_id=rt.run_id, step=rt.budget.steps, sender=recipient, recipient="orchestrator",
                             type="review" if out_type == "ReviewVerdict" else "result", payload_type=out_type,
                             payload=result.model_dump(mode="json"))
        rt.state.add_message(reply)
        rt.logger.write(agent=recipient, kind="message", name="→ orchestrator", output={"type": out_type})
        return result

    # ------------------------------------------------------------------ planning
    def make_plan(self, brief: str) -> Plan:
        def heuristic():
            if not H.in_scope(brief):
                return Plan(in_scope=False, reason="Запрос не относится к моделированию маркетинговых ситуаций")
            return Plan(in_scope=True, reason="Маркетинговый вопрос о сравнении стратегий", steps=CANONICAL)

        plan = self.think({"brief": brief, "available_agents": {n: a.role for n, a in self.agents.items()}},
                          Plan, heuristic, label="plan")
        if plan.in_scope and [s.agent for s in plan.steps] != [s.agent for s in CANONICAL]:
            self.rt.logger.write(agent="orchestrator", kind="event", name="plan_normalized", status="warning",
                                 input=[s.agent for s in plan.steps], error="План LLM не совпал с допустимым графом — применён канонический")
            plan.steps = CANONICAL
        return plan

    # ------------------------------------------------------------------ main loop
    def run(self, brief: str) -> RunOutcome:
        rt, st = self.rt, self.rt.state
        try:
            plan = self.make_plan(brief)
            st.put(rt.run_id, "plan", plan)
            if not plan.in_scope:
                return self._finish("out_of_scope", f"Запрос отклонён: {plan.reason}. Пример корректного запроса: "
                                    "«Что эффективнее для оператора связи с бюджетом 30 млн тенге — инфлюенсеры или реклама?»")

            ctx: MarketContext = self.dispatch("market_researcher", "research_task", {"brief": brief})
            st.put(rt.run_id, "market_context", ctx)

            # --- спецификация + цикл ревизии критиком
            spec: ScenarioSpec = self.dispatch("scenario_designer", "design_task",
                                               {"brief": brief, "market_context": ctx.model_dump()})
            spec_verdict = self._review_loop(
                "scenario_spec", lambda s: {"spec": s.model_dump()}, spec,
                lambda verdict, prev: self.dispatch("scenario_designer", "design_task", {
                    "brief": brief, "market_context": ctx.model_dump(), "review": verdict.model_dump(),
                    "previous_spec": prev.model_dump()}))
            if spec_verdict is None:
                return self._finish("revision_limit", "Спецификация не прошла проверку критика за "
                                    f"{self.s.max_revisions} ревизий. Уточните бриф (размер сети, число прогонов, стратегии).")
            spec = spec_verdict[1]
            st.put(rt.run_id, "scenario_spec", spec)

            sim: SimulationResults = self.dispatch("simulation_engineer", "simulate_task",
                                                   {"spec": spec.model_dump(), "market_context": ctx.model_dump()})
            st.put(rt.run_id, "simulation_results", sim)

            # --- анализ + цикл ревизии
            sim_d = sim.model_dump(mode="json")
            analysis: Analysis = self.dispatch("analyst", "analyze_task", {"spec": spec.model_dump(), "simulation_results": sim_d})
            an_verdict = self._review_loop(
                "analysis", lambda a: {"analysis": a.model_dump(mode="json"), "simulation_results": sim_d}, analysis,
                lambda verdict, prev: self.dispatch("analyst", "analyze_task", {
                    "spec": spec.model_dump(), "simulation_results": sim_d, "review": verdict.model_dump(),
                    "previous_analysis": prev.model_dump(mode="json")}))
            if an_verdict is None:
                return self._finish("revision_limit", "Выводы аналитика не прошли сверку с числами за "
                                    f"{self.s.max_revisions} ревизий. Результаты симуляции сохранены: {sim.results_file}")
            verdicts, analysis = an_verdict[0], an_verdict[1]
            st.put(rt.run_id, "analysis", analysis)

            reviews = {
                "Спецификация": {**spec_verdict[0].model_dump(), "revisions": self.revisions["scenario_spec"]},
                "Анализ": {**verdicts.model_dump(), "revisions": self.revisions["analysis"]},
            }
            report: Report = self.dispatch("report_writer", "report_task", {
                "spec": spec.model_dump(), "market_context": ctx.model_dump(), "simulation_results": sim_d,
                "analysis": analysis.model_dump(mode="json"), "reviews": reviews})
            st.put(rt.run_id, "report", report)
            return self._finish("completed", report.headline, report_path=report.path, best=analysis.best_strategy)

        except RunAborted as e:
            return self._finish(e.status, f"Прогон остановлен: {e}")
        except ToolError as e:
            return self._finish("failed", f"Сбой инструмента после повторных попыток: {e}")
        except Exception as e:  # noqa: BLE001 — последний рубеж: понятное сообщение вместо трейсбэка
            rt.logger.write(agent="orchestrator", kind="event", name="unhandled", status="error", error=repr(e))
            return self._finish("failed", f"Непредвиденная ошибка: {type(e).__name__}: {e}")

    def _review_loop(self, target, to_payload, obj, revise):
        """Отправляет объект критику; при отказе — на доработку автору, не более max_revisions раз."""
        while True:
            verdict: ReviewVerdict = self.dispatch("critic", "review_spec" if target == "scenario_spec" else "review_analysis",
                                                   to_payload(obj))
            self.rt.state.put(self.rt.run_id, f"review_{target}_{self.revisions[target]}", verdict)
            if verdict.approved:
                return verdict, obj
            if self.revisions[target] >= self.s.max_revisions:
                self.rt.logger.write(agent="orchestrator", kind="event", name="revision_limit", status="error",
                                     error=f"{target}: исчерпан лимит ревизий {self.s.max_revisions}")
                return None
            self.revisions[target] += 1
            obj = revise(verdict, obj)

    def _finish(self, status: str, message: str, report_path: str | None = None, best: str | None = None) -> RunOutcome:
        rt = self.rt
        rt.state.update_run(rt.run_id, status=status, message=message, step=rt.budget.steps, finished=True)
        rt.logger.write(agent="orchestrator", kind="event", name="finish", status=status, output=message)
        return RunOutcome(run_id=rt.run_id, status=status, message=message, report_path=report_path,
                          best_strategy=best, revisions=dict(self.revisions), log_file=str(rt.logger.path))
