"""Логирование всех вызовов агентов (LLM) и инструментов в JSONL — один файл на прогон."""
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _short(obj: Any, limit: int = 300) -> str:
    try:
        s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = repr(obj)
    return s if len(s) <= limit else s[: limit - 3] + "..."


class CallLogger:
    """Пишет события: kind ∈ {llm, tool, message, event}. Нагрузку считаем по llm+tool."""

    def __init__(self, path: Path, run_id: str, echo: bool = False):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.run_id = run_id
        self.echo = echo
        self._lock = threading.Lock()
        self.step = 0

    def write(self, *, agent: str, kind: str, name: str, status: str = "ok", duration_ms: float | None = None,
              attempt: int | None = None, input: Any = None, output: Any = None, error: str | None = None,
              **extra: Any) -> None:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "step": self.step,
            "agent": agent,
            "kind": kind,
            "name": name,
            "status": status,
        }
        if duration_ms is not None:
            rec["duration_ms"] = round(duration_ms, 1)
        if attempt is not None:
            rec["attempt"] = attempt
        if input is not None:
            rec["input"] = _short(input)
        if output is not None:
            rec["output"] = _short(output)
        if error:
            rec["error"] = error
        rec.update(extra)
        line = json.dumps(rec, ensure_ascii=False)
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if self.echo:
            tag = f"[{rec['step']:02d}] {agent:<19} {kind:<7} {name:<22} {status}"
            if duration_ms is not None:
                tag += f"  {duration_ms:7.0f} ms"
            if error:
                tag += f"  ! {error[:90]}"
            print(tag, flush=True)

    @contextmanager
    def timed(self, *, agent: str, kind: str, name: str, attempt: int | None = None, input: Any = None):
        """Контекст: логирует ok/error и длительность. В yield отдаёт dict, куда можно положить output."""
        box: dict[str, Any] = {}
        t0 = time.perf_counter()
        try:
            yield box
        except Exception as e:  # noqa: BLE001
            self.write(agent=agent, kind=kind, name=name, status="error", attempt=attempt,
                       duration_ms=(time.perf_counter() - t0) * 1000, input=input, error=f"{type(e).__name__}: {e}")
            raise
        else:
            self.write(agent=agent, kind=kind, name=name, status=box.get("status", "ok"), attempt=attempt,
                       duration_ms=(time.perf_counter() - t0) * 1000, input=input, output=box.get("output"),
                       **box.get("extra", {}))


def read_log(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
