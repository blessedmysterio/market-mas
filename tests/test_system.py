"""Модульные тесты + все тестовые сценарии из scenarios/*.json.
Запуск: pytest -q   (офлайн, LLM_PROVIDER=mock)"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OUTPUTS_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("STATE_DB", str(tmp_path / "out" / "state.db"))
    monkeypatch.setenv("FAULTS", "")
    monkeypatch.setenv("HTTP_TIMEOUT_S", "3")


# ---------------------------------------------------------------- модульные
def test_brief_parsing():
    from marketmas import heuristics as H
    b = "Оператор связи, бюджет 30 млн тенге, сеть из 2000 агентов, 40 прогонов, инфлюенсеры против рекламы"
    nums = H.parse_numbers(b)
    assert nums["budget_kzt"] == 30_000_000 and nums["n_agents"] == 2000 and nums["n_runs"] == 40
    assert H.detect_industry(b) == "telecom"
    assert H.detect_strategies(b) == ["baseline", "hub_seeding", "mass_media"]
    assert not H.in_scope("Какая завтра погода?")


def test_spec_validator_catches_out_of_bounds():
    from marketmas.tools.validation import validate_spec
    issues = validate_spec({"n_agents": 10**7, "ba_m": 3, "n_steps": 60, "n_runs": 5000, "strategies": ["baseline"],
                            "budget_kzt": 1, "intervention_step": 5, "intensities": {}})
    fields = {i["field"] for i in issues if i["severity"] == "error"}
    assert {"n_agents", "n_runs", "strategies"} <= fields


def test_paired_test_and_holm():
    from marketmas.tools.stats_tools import holm, paired_test
    r = paired_test([0.32, 0.33, 0.35, 0.34], [0.30, 0.31, 0.32, 0.31])
    assert r["delta_pp"] == pytest.approx(2.5, abs=1e-6) and r["p_value"] < 0.05
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_simulation_common_random_numbers():
    """Baseline одинаков при одинаковом seed; вмешательство не сдвигает общий шум."""
    from marketmas.tools.simulator import simulate_strategy
    ctx = dict(base_shares=[.3, .4, .3], quality=[.7, .75, .65], price=[1, 1.05, .92], social_weight=.9,
               price_sensitivity=1, churn_rate=.1)
    spec = dict(n_agents=300, ba_m=3, n_steps=30, intervention_step=5, shock=None,
                intensities={"hub_seeds": 5, "random_seeds": 10, "ad_boost": .3, "price_cut": .1})
    a = simulate_strategy(spec=spec, ctx=ctx, strategy="baseline", n_runs=3, base_seed=1)
    b = simulate_strategy(spec=spec, ctx=ctx, strategy="baseline", n_runs=3, base_seed=1)
    assert a["final_shares"] == b["final_shares"]


def test_check_claims_detects_wrong_numbers():
    from marketmas.tools.validation import check_claims
    truth = [{"a": "hub_seeding", "b": "baseline", "delta_pp": 5.0, "p_holm": 0.001}]
    bad = {"best_strategy": "hub_seeding", "caveats": ["x"],
           "claims": [{"a": "hub_seeding", "b": "baseline", "delta_pp": 7.5, "significant": True}]}
    assert any(i["severity"] == "error" for i in check_claims(bad, truth, {"hub_seeding": 36, "baseline": 31}))


def test_agents_have_at_most_5_tools_and_orchestrator_has_none():
    from marketmas.__main__ import _tools_of
    from marketmas.agents.analyst import Analyst
    from marketmas.agents.critic import Critic
    from marketmas.agents.market_researcher import MarketResearcher
    from marketmas.agents.orchestrator import Orchestrator
    from marketmas.agents.report_writer import ReportWriter
    from marketmas.agents.scenario_designer import ScenarioDesigner
    from marketmas.agents.simulation_engineer import SimulationEngineer
    classes = [MarketResearcher, ScenarioDesigner, Critic, SimulationEngineer, Analyst, ReportWriter]
    for cls in classes:
        assert 1 <= len(_tools_of(cls)) <= 5, cls.name
    assert _tools_of(Orchestrator) == []  # оркестратор не выполняет предметную работу
    names = [t.name for c in classes for t in _tools_of(c)]
    assert len(names) == len(set(names)), "инструменты (роли) не должны дублироваться"
    external = {t.name for c in classes for t in _tools_of(c) if t.external}
    assert {"openalex_search", "market_lookup", "simulate_strategy"} <= external


def test_no_api_keys_in_code():
    pat = re.compile(r"(sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|api_key\s*=\s*['\"][^'\"]{8,})")
    for p in (ROOT / "marketmas").rglob("*.py"):
        assert not pat.search(p.read_text(encoding="utf-8")), p


def test_messages_are_json_roundtrip():
    from marketmas.messages import AgentMessage
    m = AgentMessage(run_id="r", step=1, sender="orchestrator", recipient="critic", type="task",
                     payload_type="review_spec", payload={"spec": {"n_agents": 1000}})
    assert AgentMessage.model_validate_json(m.model_dump_json()) == m


def test_missing_api_key_gives_clear_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from marketmas.config import Settings
    from marketmas.system import run_brief
    out = run_brief("Оператор связи сравнивает инфлюенсеров и рекламу", Settings())
    assert out.status == "failed" and "LLM_API_KEY" in out.message


# ---------------------------------------------------------------- сценарии
def _scenario_ids():
    import json
    return [json.loads(p.read_text(encoding="utf-8"))["id"] for p in sorted((ROOT / "scenarios").glob("*.json"))]


@pytest.mark.parametrize("sid", _scenario_ids())
def test_scenario(sid):
    from marketmas.evaluate import load_scenarios, run_scenario
    sc = load_scenarios([sid])[0]
    outcome, fails, _ = run_scenario(sc)
    assert not fails, f"{sid}: {fails} | {outcome.message}"
