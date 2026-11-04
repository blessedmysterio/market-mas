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
    sub.add_parser("llm-check", help="Проверить подключение к LLM из .env")

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

    if a.cmd == "llm-check":
        return _llm_check()

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


def _llm_check() -> int:
    import time
    from .llm import LLMError, make_llm
    s = Settings()
    print(f"Провайдер: {s.llm_provider}")
    if s.llm_provider == "mock":
        print("Сейчас включён офлайн-режим (mock). Чтобы подключить модель, задайте в .env:\n"
              "  LLM_PROVIDER=openai\n  LLM_BASE_URL=...\n  LLM_API_KEY=...\n  LLM_MODEL=...")
        return 1
    print(f"URL:       {s.llm_base_url}\nМодель:    {s.llm_model}\nКлюч:      {'задан' if s.llm_api_key else 'НЕ задан'}")
    try:
        llm = make_llm(s)
        t0 = time.perf_counter()
        text, usage = llm.chat("Ответь JSON-объектом.",
                               'Верни {"status": "ok", "model": "<как тебя зовут>"}')
        dt = time.perf_counter() - t0
    except LLMError as e:
        print(f"\nОШИБКА: {e}")
        msg = str(e)
        if "401" in msg or "403" in msg:
            print("Подсказка: неверный или просроченный LLM_API_KEY.")
        elif "404" in msg or "model" in msg.lower():
            print("Подсказка: проверьте LLM_MODEL — такой модели у провайдера нет (список моделей — в консоли провайдера).")
        elif "Сеть" in msg:
            print("Подсказка: нет соединения с LLM_BASE_URL (интернет, VPN, адрес; для Ollama — запущен ли `ollama serve`).")
        return 2
    print(f"\nОтвет за {dt:.1f} с: {text.strip()[:200]}\nТокены: {usage}")
    print("\nПодключение работает. Запустите любой бриф: python -m marketmas run \"...\"")
    return 0


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
