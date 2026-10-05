"""Настройки системы. Все секреты читаются из переменных окружения / .env, в коде их нет."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv необязателен
    pass

ROOT = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # --- LLM ---
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock"))  # mock | openai
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"))
    llm_api_key: str | None = field(default_factory=lambda: os.getenv("LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini"))
    llm_temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.2))
    llm_timeout_s: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT_S", 60))
    llm_retries: int = field(default_factory=lambda: _env_int("LLM_RETRIES", 2))

    # --- Лимиты и надёжность ---
    max_steps: int = field(default_factory=lambda: _env_int("MAX_STEPS", 60))
    run_timeout_s: float = field(default_factory=lambda: _env_float("RUN_TIMEOUT_S", 300))
    max_revisions: int = field(default_factory=lambda: _env_int("MAX_REVISIONS", 2))
    tool_retries: int = field(default_factory=lambda: _env_int("TOOL_RETRIES", 2))
    loop_repeat_limit: int = field(default_factory=lambda: _env_int("LOOP_REPEAT_LIMIT", 3))

    # --- Внешние источники ---
    openalex_url: str = field(default_factory=lambda: os.getenv("OPENALEX_URL", "https://api.openalex.org/works"))
    openalex_mailto: str | None = field(default_factory=lambda: os.getenv("OPENALEX_MAILTO"))
    http_timeout_s: float = field(default_factory=lambda: _env_float("HTTP_TIMEOUT_S", 8))

    # --- Пути ---
    data_dir: Path = ROOT / "data"
    logs_dir: Path = field(default_factory=lambda: Path(os.getenv("LOGS_DIR", ROOT / "logs")))
    outputs_dir: Path = field(default_factory=lambda: Path(os.getenv("OUTPUTS_DIR", ROOT / "outputs")))
    state_db: Path = field(default_factory=lambda: Path(os.getenv("STATE_DB", ROOT / "outputs" / "state.db")))

    # --- Внедрение отказов (для тестовых сценариев надёжности) ---
    # Через запятую: openalex_down, sim_flaky, llm_garbage, critic_reject, analyst_hallucinate, slow_sim
    faults: frozenset[str] = field(
        default_factory=lambda: frozenset(f.strip() for f in os.getenv("FAULTS", "").split(",") if f.strip())
    )

    def with_overrides(self, **kw) -> "Settings":
        if "faults" in kw and not isinstance(kw["faults"], frozenset):
            kw["faults"] = frozenset(kw["faults"])
        for k in ("logs_dir", "outputs_dir", "state_db"):
            if k in kw and kw[k] is not None:
                kw[k] = Path(kw[k])
        return replace(self, **kw)
