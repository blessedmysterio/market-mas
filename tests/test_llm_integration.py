"""Путь через реальный OpenAI-совместимый API (без ключа и интернета: локальный фейковый сервер)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fake_llm_server import start, state


@pytest.fixture
def fake_api(tmp_path, monkeypatch):
    srv, url = start()
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_BASE_URL", url)
    monkeypatch.setenv("LLM_MODEL", "fake")
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OUTPUTS_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("STATE_DB", str(tmp_path / "out" / "state.db"))
    monkeypatch.setenv("FAULTS", "openalex_down")
    yield url
    srv.shutdown()


def test_full_run_through_llm_api(fake_api):
    from marketmas.config import Settings
    from marketmas.load_report import load_stats
    from marketmas.system import run_brief
    out = run_brief("Оператор связи: инфлюенсеры или реклама? Бюджет 30 млн тенге", Settings())
    assert out.status == "completed", out.message
    recs = [json.loads(l) for l in open(out.log_file, encoding="utf-8")]
    llm_ok = [r for r in recs if r["kind"] == "llm" and r["status"] == "ok"]
    assert len(llm_ok) == 8 and all(r["provider"] == "openai" for r in llm_ok)   # все 7 агентов думали через API
    assert not any(r["status"] == "fallback" for r in recs)                       # эвристика не понадобилась
    assert state["rf_seen"] >= 1                                                  # откат без response_format
    assert state["max_user_chars"] < 8000                                         # промпты сжаты
    assert load_stats(Path(out.log_file))["balanced"]
    report = Path(out.report_path).read_text(encoding="utf-8")
    assert "отклонение LLM без подтверждённой ошибки" in report                   # критик-LLM не блокирует без причины


def test_llm_check_command(fake_api, capsys):
    from marketmas.__main__ import main
    assert main(["llm-check"]) == 0
    assert "Подключение работает" in capsys.readouterr().out


def test_unreachable_api_gives_clear_status(fake_api, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLM_RETRIES", "0")
    from marketmas.config import Settings
    from marketmas.system import run_brief
    out = run_brief("Оператор связи: инфлюенсеры или реклама? Бюджет 30 млн тенге", Settings())
    # сеть недоступна → каждый агент уходит в детерминированный фолбэк, прогон не падает
    assert out.status == "completed"
    recs = [json.loads(l) for l in open(out.log_file, encoding="utf-8")]
    assert any(r["status"] == "fallback" for r in recs)
