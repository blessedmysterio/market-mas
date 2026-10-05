"""CLI:
  python -m marketmas run "бриф..." [--provider mock|openai] [--faults openalex_down,...] [--quiet]
  python -m marketmas eval [S01 S02 ...]
  python -m marketmas load logs/run_<id>.jsonl [--png путь]
  python -m marketmas show <run_id>
  python -m marketmas agents
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="marketmas", description="Многоагентная система моделирования маркетинговых ситуаций")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="Выполнить бриф")
    r.add_argument("brief")
    r.add_argument("--provider", choices=["mock", "openai"], help="LLM-провайдер (по умолчанию из LLM_PROVIDER)")
    r.add_argument("--faults", default=None, help="Внедрение отказов через запятую")
    r.add_argument("--timeout", type=float, default=None, help="Лимит времени прогона, с")
    r.add_argument("--max-steps", type=int, default=None)
    r.add_argument("--quiet", action="store_true")

    e = sub.add_parser("eval", help="Прогнать тестовые сценарии")
    e.add_argument("ids", nargs="*")

    lo = sub.add_parser("load", help="Распределение нагрузки по логу")
    lo.add_argument("log")
    lo.add_argument("--png", default=None)

    sh = sub.add_parser("show", help="Состояние прогона из хранилища")
    sh.add_argument("run_id")

    sub.add_parser("agents", help="Таблица агентов")

    a = ap.parse_args(argv)

    if a.cmd == "run":
        from .system import run_brief
        kw = {}
        if a.provider:
            kw["llm_provider"] = a.provider
        if a.faults is not None:
            kw["faults"] = frozenset(f for f in a.faults.split(",") if f)
        if a.timeout:
            kw["run_timeout_s"] = a.timeout
        if a.max_steps:
            kw["max_steps"] = a.max_steps
        s = Settings().with_overrides(**kw)
        out = run_brief(a.brief, s, echo=not a.quiet)
        print("\n" + "=" * 70)
        print(f"Статус: {out.status}\n{out.message}")
        if out.report_path:
            print(f"Отчёт: {out.report_path}")
        print(f"Лог:   {out.log_file}")
        from .load_report import format_table, load_stats
        print("\n" + format_table(load_stats(Path(out.log_file))))
        return 0 if out.status in ("completed", "out_of_scope") else 2

    if a.cmd == "eval":
        from .evaluate import main as eval_main
        return eval_main(a.ids or None)

    if a.cmd == "load":
        from .load_report import format_table, load_stats, plot_load
        st = load_stats(Path(a.log))
        print(format_table(st))
        if a.png:
            print("График:", plot_load(st, Path(a.png)))
        return 0

    if a.cmd == "show":
        from .state import StateStore
        st = StateStore(Settings().state_db)
        print(json.dumps(st.get_run(a.run_id), ensure_ascii=False, indent=2))
        for m in st.messages(a.run_id):
            print(f"  [{m['step']:02d}] {m['sender']:>19} → {m['recipient']:<19} {m['type']:<7} {m['payload_type']}")
        return 0

    if a.cmd == "agents":
        from .agents.analyst import Analyst
        from .agents.critic import Critic
        from .agents.market_researcher import MarketResearcher
        from .agents.orchestrator import Orchestrator
        from .agents.report_writer import ReportWriter
        from .agents.scenario_designer import ScenarioDesigner
        from .agents.simulation_engineer import SimulationEngineer
        print("| Агент | Роль | Входы | Выходы | Инструменты | Критерий завершения |\n|---|---|---|---|---|---|")
        for cls in (Orchestrator, MarketResearcher, ScenarioDesigner, Critic, SimulationEngineer, Analyst, ReportWriter):
            tools = ", ".join(t.name for t in _tools_of(cls)) or "— (только LLM-планирование)"
            print(f"| {cls.name} | {cls.role} | {cls.inputs} | {cls.outputs} | {tools} | {cls.done_when} |")
        return 0
    return 1


def _tools_of(cls):
    """Список инструментов без полноценного runtime (для документации)."""
    from types import SimpleNamespace
    s = Settings()
    fake = SimpleNamespace(settings=s, run_id="doc", state=None)
    obj = cls.__new__(cls)
    obj.rt = fake
    return obj.build_tools()


if __name__ == "__main__":
    sys.exit(main())
