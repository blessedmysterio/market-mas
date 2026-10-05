"""Базовый класс инструмента."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class ToolError(RuntimeError):
    """Ошибка инструмента. retryable=True — имеет смысл повторить."""

    def __init__(self, msg: str, retryable: bool = True):
        super().__init__(msg)
        self.retryable = retryable


@dataclass
class Tool:
    name: str
    description: str
    func: Callable[..., Any]
    external: bool = False  # внешний источник данных (API/БД/файлы/код)

    def __call__(self, **kwargs: Any) -> Any:
        return self.func(**kwargs)
