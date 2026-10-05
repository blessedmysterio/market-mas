"""Прогон набора тестовых сценариев (scenarios/*.json) и проверка ожидаемых результатов."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import ROOT, Settings
from .load_report import load_stats
from .logging_utils import read_log
from .state import StateStore
from .system import run_brief

SCEN_DIR = ROOT / "scenarios"


def load_scenarios(ids: list[str] | None = None) -> list[dict]:
    out = []
    for p in sorted(SCEN_DIR.glob("*.json")):
        sc = json.loads(p.read_text(encoding="utf-8"))
        if not ids or sc["id"] in ids:
            out.append(sc)
    return out


def check(sc: dict, outcome, settings: Settings) -> list[str]:
    """Возвращает список нарушенных ожиданий (пустой = сценарий пройден)."""
    exp = sc["expected"]
    fails: list[str] = []
    if outcome.status != exp["status"]:
        fails.append(f"status={outcome.status}, ожидался {exp['status']}")
    if "best_strategy_in" in exp and outcome.best_strategy not in exp["best_strategy_in"]:
        fails.append(f"best={outcome.best_strategy}, ожидалось одно из {exp['best_strategy_in']}")
    for k, v in exp.get("min_revisions", {}).items():
        if outcome.revisions.get(k, 0) < v:
            fails.append(f"ревизий {k}={outcome.revisions.get(k, 0)} < {v}")
    recs = read_log(Path(outcome.log_file))
    for cond in exp.get("log_contains", []):
        if not any(all(r.get(k) == v for k, v in cond.items()) for r in recs):
            fails.append(f"в логе нет записи {cond}")
    for cond in exp.get("log_absent", []):
        if any(all(r.get(k) == v for k, v in cond.items()) for r in recs):
            fails.append(f"в логе есть запрещённая запись {cond}")
    if exp.get("balanced"):
        st = load_stats(Path(outcome.log_file))
        if not st["balanced"]:
            fails.append(f"нагрузка не сбалансирована: max={st['max_share']:.1%}")
    if "max_calls" in exp:
        st = load_stats(Path(outcome.log_file))
        if st["total_calls"] > exp["max_calls"]:
            fails.append(f"вызовов {st['total_calls']} > {exp['max_calls']}")
    if exp.get("spec") or exp.get("delta_vs_baseline") or exp.get("comparison"):
        store = StateStore(settings.state_db)
        spec = store.get(outcome.run_id, "scenario_spec") or {}
        analysis = store.get(outcome.run_id, "analysis") or {}
        store.close()
        for k, v in exp.get("spec", {}).items():
            got = spec.get(k)
            if isinstance(v, dict) and "max" in v:
                if got is None or got > v["max"]:
                    fails.append(f"spec.{k}={got} > {v['max']}")
            elif isinstance(v, dict) and "not_null" in v:
                if (got is None) == v["not_null"]:
                    fails.append(f"spec.{k}={got}")
            elif got != v:
                fails.append(f"spec.{k}={got}, ожидалось {v}")
        comps = {(c["a"], c["b"]): c for c in analysis.get("comparisons", [])}
        for cmp in exp.get("comparison", []):
            c = comps.get((cmp["a"], cmp["b"]))
            if c is None:
                fails.append(f"нет сравнения {cmp['a']} vs {cmp['b']}")
                continue
            if "delta_sign" in cmp and (c["delta_pp"] > 0) != (cmp["delta_sign"] == "+"):
                fails.append(f"Δ({cmp['a']} vs {cmp['b']})={c['delta_pp']:+.2f}, ожидался знак {cmp['delta_sign']}")
            if cmp.get("significant") is not None and (c["p_holm"] < 0.05) != cmp["significant"]:
                fails.append(f"значимость {cmp['a']} vs {cmp['b']}: p_holm={c['p_holm']:.3g}")
    if exp.get("report_contains"):
        if not outcome.report_path:
            fails.append("нет отчёта")
        else:
            text = Path(outcome.report_path).read_text(encoding="utf-8")
            for frag in exp["report_contains"]:
                if frag not in text:
                    fails.append(f"в отчёте нет «{frag}»")
    if exp.get("message_contains") and exp["message_contains"] not in outcome.message:
        fails.append(f"сообщение не содержит «{exp['message_contains']}»: {outcome.message[:120]}")
    return fails


def run_scenario(sc: dict, base: Settings | None = None, echo: bool = False):
    s = (base or Settings()).with_overrides(**sc.get("settings", {}))
    t0 = time.monotonic()
    outcome = run_brief(sc["brief"], s, echo=echo, run_id=f"{sc['id']}-{int(time.time() * 1000) % 10**8}")
    elapsed = time.monotonic() - t0
    fails = check(sc, outcome, s)
    return outcome, fails, elapsed


def main(ids: list[str] | None = None, out: Path | None = None) -> int:
    scs = load_scenarios(ids)
    rows, passed = [], 0
    for sc in scs:
        outcome, fails, elapsed = run_scenario(sc)
        st = load_stats(Path(outcome.log_file))
        ok = not fails
        passed += ok
        rows.append({"id": sc["id"], "name": sc["name"], "status": outcome.status, "best": outcome.best_strategy,
                     "calls": st["total_calls"], "max_share": st["max_share"], "elapsed_s": round(elapsed, 1),
                     "passed": ok, "fails": fails, "log": Path(outcome.log_file).name,
                     "expected": sc["expected_text"]})
        print(f"{'PASS' if ok else 'FAIL'}  {sc['id']}  {sc['name'][:55]:<55} {outcome.status:<15} {elapsed:5.1f}s"
              + ("" if ok else f"  <- {'; '.join(fails)}"), flush=True)
    print(f"\nПройдено {passed}/{len(scs)} ({passed / max(1, len(scs)):.0%})")
    out = out or (ROOT / "outputs" / "eval_results.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    md = ["# Результаты тестовых сценариев", "", f"Пройдено: **{passed}/{len(scs)}** ({passed / max(1, len(scs)):.0%})", "",
          "| ID | Сценарий | Ожидаемый результат | Статус | Лучшая стратегия | Вызовов | Макс. доля агента | Время, с | Итог |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['id']} | {r['name']} | {r['expected']} | {r['status']} | {r['best'] or '—'} | {r['calls']} | "
                  f"{r['max_share'] * 100:.1f}% | {r['elapsed_s']} | {'✅' if r['passed'] else '❌ ' + '; '.join(r['fails'])} |")
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    (out.with_suffix(".json")).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if passed == len(scs) else 1
