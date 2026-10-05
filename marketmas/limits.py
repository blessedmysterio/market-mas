"""Лимиты на шаги и время, защита от зацикливания."""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter


class RunAborted(Exception):
    status = "failed"


class StepLimitExceeded(RunAborted):
    status = "step_limit"


class RunTimeout(RunAborted):
    status = "timeout"


class LoopDetected(RunAborted):
    status = "step_limit"


class Budget:
    """Общий бюджет прогона. Каждый вызов LLM/инструмента и каждое сообщение тратят шаг."""

    def __init__(self, max_steps: int, timeout_s: float, loop_repeat_limit: int = 3):
        self.max_steps = max_steps
        self.timeout_s = timeout_s
        self.loop_repeat_limit = loop_repeat_limit
        self.started = time.monotonic()
        self.steps = 0
        self._seen: Counter[str] = Counter()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def remaining_s(self) -> float:
        return max(0.0, self.timeout_s - self.elapsed)

    def check_time(self) -> None:
        if self.elapsed > self.timeout_s:
            raise RunTimeout(f"Превышен лимит времени {self.timeout_s:.0f} с (прошло {self.elapsed:.1f} с)")

    def tick(self, what: str = "") -> int:
        self.check_time()
        self.steps += 1
        if self.steps > self.max_steps:
            raise StepLimitExceeded(f"Превышен лимит шагов {self.max_steps} (на действии '{what}')")
        return self.steps

    def guard_repeat(self, agent: str, payload: object) -> None:
        """Одинаковая задача одному агенту больше N раз подряд = зацикливание."""
        key = agent + ":" + hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        self._seen[key] += 1
        if self._seen[key] > self.loop_repeat_limit:
            raise LoopDetected(f"Зацикливание: агент '{agent}' получил одинаковую задачу {self._seen[key]} раз")
