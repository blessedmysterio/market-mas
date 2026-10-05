"""Точка входа: собирает runtime и запускает оркестратор."""
from __future__ import annotations

import uuid
from datetime import datetime

from .agents.base import Runtime
from .agents.orchestrator import Orchestrator
from .config import Settings
from .limits import Budget
from .llm import LLMError, make_llm
from .logging_utils import CallLogger
from .messages import RunOutcome
from .state import StateStore


def run_brief(brief: str, settings: Settings | None = None, echo: bool = False, run_id: str | None = None) -> RunOutcome:
    s = settings or Settings()
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    logger = CallLogger(s.logs_dir / f"run_{run_id}.jsonl", run_id, echo=echo)
    state = StateStore(s.state_db)
    state.create_run(run_id, brief)
    try:
        llm = make_llm(s)
    except LLMError as e:
        state.update_run(run_id, status="failed", message=str(e), finished=True)
        logger.write(agent="orchestrator", kind="event", name="finish", status="failed", error=str(e))
        state.close()
        return RunOutcome(run_id=run_id, status="failed", message=f"Ошибка конфигурации LLM: {e}", log_file=str(logger.path))
    rt = Runtime(settings=s, llm=llm, logger=logger, state=state,
                 budget=Budget(s.max_steps, s.run_timeout_s, s.loop_repeat_limit), run_id=run_id)
    logger.write(agent="orchestrator", kind="event", name="start", input=brief,
                 provider=llm.name, faults=sorted(s.faults))
    try:
        return Orchestrator(rt).run(brief)
    finally:
        state.close()
