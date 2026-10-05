"""Базовый агент: одна роль, ≤5 инструментов, вызовы LLM с валидацией схемы, вызовы инструментов с повторами."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..limits import Budget
from ..llm import BaseLLM, LLMError
from ..logging_utils import CallLogger
from ..state import StateStore
from ..tools.base import Tool, ToolError

T = TypeVar("T", bound=BaseModel)
MAX_TOOLS = 5
PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


@dataclass
class Runtime:
    """Общие сервисы прогона, которые передаются всем агентам."""
    settings: Settings
    llm: BaseLLM
    logger: CallLogger
    state: StateStore
    budget: Budget
    run_id: str


class Agent:
    name: str = "agent"
    role: str = ""
    inputs: str = ""
    outputs: str = ""
    done_when: str = ""

    def __init__(self, rt: Runtime):
        self.rt = rt
        self.tools: dict[str, Tool] = {t.name: t for t in self.build_tools()}
        if len(self.tools) > MAX_TOOLS:
            raise ValueError(f"У агента {self.name} {len(self.tools)} инструментов > {MAX_TOOLS}")
        self.system_prompt = self._load_prompt()

    # --- переопределяется в наследниках
    def build_tools(self) -> list[Tool]:
        return []

    def handle(self, payload_type: str, payload: dict) -> tuple[str, BaseModel]:
        raise NotImplementedError

    # --- служебное
    def _load_prompt(self) -> str:
        p = PROMPTS_DIR / f"{self.name}.md"
        return p.read_text(encoding="utf-8") if p.exists() else f"Ты агент {self.name}. Роль: {self.role}"

    @property
    def s(self) -> Settings:
        return self.rt.settings

    def call_tool(self, tool_name: str, /, **kwargs: Any) -> Any:
        name = tool_name
        if name not in self.tools:
            raise ToolError(f"Агент {self.name} не имеет инструмента {name}", retryable=False)
        tool = self.tools[name]
        last: Exception | None = None
        attempts = 1 + self.s.tool_retries
        for attempt in range(1, attempts + 1):
            self.rt.budget.tick(f"{self.name}.{name}")
            self.rt.logger.step = self.rt.budget.steps
            try:
                with self.rt.logger.timed(agent=self.name, kind="tool", name=name, attempt=attempt,
                                          input=_summarize(kwargs)) as box:
                    result = tool(**kwargs)
                    box["output"] = _summarize(result)
                return result
            except ToolError as e:
                last = e
                if not e.retryable:
                    break
            except (TimeoutError, OSError, ValueError, RuntimeError) as e:
                last = e
            if attempt < attempts:
                time.sleep(min(0.2 * 2 ** (attempt - 1), 1.0))
        raise ToolError(f"{self.name}.{name}: не удалось после {attempt} попыток: {last}", retryable=False)

    def think(self, task: dict, schema: type[T], heuristic: Callable[[], T], label: str = "llm") -> T:
        """Вызов LLM → JSON → pydantic. При невалидном ответе — повтор с сообщением об ошибке.
        Если все попытки неудачны — детерминированный фолбэк (heuristic) и запись status=fallback."""
        system = (self.system_prompt + "\n\nОтвечай ТОЛЬКО JSON-объектом по схеме:\n"
                  + json.dumps(schema.model_json_schema(), ensure_ascii=False))
        user = json.dumps(task, ensure_ascii=False, default=str)
        mock = lambda: heuristic().model_dump_json()  # noqa: E731
        attempts = 1 + self.s.llm_retries
        feedback = ""
        for attempt in range(1, attempts + 1):
            self.rt.budget.tick(f"{self.name}.{label}")
            self.rt.logger.step = self.rt.budget.steps
            t0 = time.perf_counter()
            try:
                text, usage = self.rt.llm.chat(system, user + feedback, mock=mock, attempt=attempt)
                obj = schema.model_validate_json(_extract_json(text))
                self.rt.logger.write(agent=self.name, kind="llm", name=label, attempt=attempt,
                                     duration_ms=(time.perf_counter() - t0) * 1000, input=task, output=obj.model_dump(),
                                     provider=self.rt.llm.name, usage=usage)
                return obj
            except (ValidationError, ValueError, LLMError) as e:
                err = f"{type(e).__name__}: {str(e)[:200]}"
                self.rt.logger.write(agent=self.name, kind="llm", name=label, status="retry", attempt=attempt,
                                     duration_ms=(time.perf_counter() - t0) * 1000, error=err, provider=self.rt.llm.name)
                feedback = f"\n\nПредыдущий ответ отклонён: {err}. Верни корректный JSON по схеме."
        obj = heuristic()
        self.rt.logger.write(agent=self.name, kind="event", name=f"{label}_fallback", status="fallback",
                             output=obj.model_dump(), error="LLM не дал валидный ответ — использована детерминированная эвристика")
        return obj


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("В ответе нет JSON-объекта")
    return text[start: end + 1]


def _summarize(obj: Any) -> Any:
    """Сокращает большие массивы для логов."""
    if isinstance(obj, dict):
        return {k: _summarize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) > 6 and all(isinstance(x, (int, float)) for x in obj):
            return f"<{len(obj)} чисел, mean={sum(obj) / len(obj):.4f}>"
        return [_summarize(x) for x in obj[:6]] + ([f"...(+{len(obj) - 6})"] if len(obj) > 6 else [])
    if isinstance(obj, BaseModel):
        return _summarize(obj.model_dump())
    return obj
