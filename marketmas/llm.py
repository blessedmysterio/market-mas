"""LLM-клиенты.

* OpenAICompatibleLLM — любой OpenAI-совместимый endpoint (OpenAI, Groq, OpenRouter, Ollama, LM Studio, vLLM).
  Ключ берётся только из окружения (LLM_API_KEY).
* MockLLM — детерминированный офлайн-режим: вместо модели вызывает эвристику агента и возвращает JSON
  той же схемы. Нужен для воспроизводимых тестов и демонстрации без ключа/интернета.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Callable

from .config import Settings


class LLMError(RuntimeError):
    pass


class BaseLLM:
    name = "base"

    def chat(self, system: str, user: str, *, mock: Callable[[], str] | None = None, attempt: int = 1) -> tuple[str, dict]:
        """Возвращает (text, usage)."""
        raise NotImplementedError


class MockLLM(BaseLLM):
    name = "mock"

    def __init__(self, settings: Settings):
        self.settings = settings

    def chat(self, system, user, *, mock=None, attempt=1):
        if mock is None:
            raise LLMError("MockLLM требует эвристику агента")
        # Внедрённый отказ: первая попытка возвращает невалидный JSON
        if "llm_garbage" in self.settings.faults and attempt == 1:
            return "Sure! Here is the JSON you asked for: {oops", {"prompt_tokens": 0, "completion_tokens": 0}
        text = mock()
        return text, {"prompt_tokens": len(system + user) // 4, "completion_tokens": len(text) // 4}


class OpenAICompatibleLLM(BaseLLM):
    name = "openai"

    def __init__(self, settings: Settings):
        if not settings.llm_api_key and "localhost" not in settings.llm_base_url and "127.0.0.1" not in settings.llm_base_url:
            raise LLMError("LLM_API_KEY не задан. Укажите его в .env или используйте LLM_PROVIDER=mock")
        self.settings = settings

    def chat(self, system, user, *, mock=None, attempt=1):
        body = {
            "model": self.settings.llm_model,
            "temperature": self.settings.llm_temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        req = urllib.request.Request(
            self.settings.llm_base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.settings.llm_api_key or 'none'}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.settings.llm_timeout_s) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:300]
            if e.code == 429:
                time.sleep(2 * attempt)
            raise LLMError(f"HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise LLMError(f"Сеть/таймаут: {e}") from e
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Неожиданный ответ API: {str(data)[:200]}") from e
        return text, data.get("usage", {})


def make_llm(settings: Settings) -> BaseLLM:
    if settings.llm_provider == "mock":
        return MockLLM(settings)
    if settings.llm_provider in ("openai", "openai_compatible", "groq", "ollama", "openrouter"):
        return OpenAICompatibleLLM(settings)
    raise LLMError(f"Неизвестный LLM_PROVIDER: {settings.llm_provider}")
