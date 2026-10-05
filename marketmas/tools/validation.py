"""Инструменты критика: проверка спецификации сценария и сверка выводов аналитика с числами."""
from __future__ import annotations

BOUNDS = {
    "n_agents": (100, 5000),
    "ba_m": (1, 10),
    "n_steps": (20, 300),
    "n_runs": (10, 100),
}
MAX_COMPUTE = 2.5e7  # n_agents * n_steps * n_runs * n_strategies
TOL_PP = 0.05


def validate_spec(spec: dict) -> list[dict]:
    issues: list[dict] = []

    def add(sev, field, msg, suggested=None):
        issues.append({"severity": sev, "field": field, "message": msg, "suggested": suggested})

    for f, (lo, hi) in BOUNDS.items():
        v = spec.get(f)
        if v is None or v < lo or v > hi:
            add("error", f, f"{f}={v} вне допустимого диапазона [{lo}, {hi}]", min(max(v or lo, lo), hi))

    strategies = spec.get("strategies", [])
    if len(set(strategies)) != len(strategies):
        add("error", "strategies", "Стратегии повторяются", list(dict.fromkeys(strategies)))
    active = [s for s in strategies if s != "baseline"]
    if len(strategies) < 2:
        add("error", "strategies", "Нужно минимум 2 стратегии для сравнения", list(dict.fromkeys(["baseline", *strategies])))
    elif not active:
        add("error", "strategies", "Нет ни одной активной стратегии", ["baseline", "hub_seeding"])
    if len(strategies) > 5:
        add("error", "strategies", "Слишком много стратегий (>5)", strategies[:5])

    if active and spec.get("budget_kzt", 0) <= 0:
        add("error", "budget_kzt", "Активные стратегии требуют положительного бюджета", 10_000_000)

    iv, steps = spec.get("intervention_step", 0), spec.get("n_steps", 60)
    if iv >= steps * 0.8:
        add("error", "intervention_step", "Вмешательство слишком поздно — эффект не успеет проявиться", max(1, steps // 10))
    shock = spec.get("shock")
    if shock and shock.get("at_step", 0) >= steps:
        add("error", "shock.at_step", "Кризис позже горизонта моделирования", max(0, iv - 1))

    n_ok = all(spec.get(f) is not None for f in ("n_agents", "n_steps", "n_runs"))
    if n_ok:
        compute = spec["n_agents"] * spec["n_steps"] * spec["n_runs"] * max(1, len(strategies))
        if compute > MAX_COMPUTE:
            add("error", "n_runs", f"Вычислительный объём {compute:.2e} > {MAX_COMPUTE:.1e}",
                max(BOUNDS["n_runs"][0], int(MAX_COMPUTE / (spec["n_agents"] * spec["n_steps"] * max(1, len(strategies))))))
        if spec["n_runs"] < 30:
            add("warning", "n_runs", "Меньше 30 прогонов — снижена статистическая мощность", 30)

    intens = spec.get("intensities", {})
    if "hub_seeding" in strategies and intens.get("hub_seeds", 0) < 1:
        add("error", "intensities", "Не рассчитано число хабов для посева (вызовите budget_to_intensity)")
    return issues


def check_claims(analysis: dict, comparisons_truth: list[dict], means_pp: dict[str, float], alpha: float = 0.05) -> list[dict]:
    """Сверяет утверждения аналитика с пересчитанной статистикой."""
    issues: list[dict] = []
    truth = {(c["a"], c["b"]): c for c in comparisons_truth}
    for cl in analysis.get("claims", []):
        key = (cl["a"], cl["b"])
        t = truth.get(key)
        if t is None and (cl["b"], cl["a"]) in truth:
            t0 = truth[(cl["b"], cl["a"])]
            t = {**t0, "delta_pp": -t0["delta_pp"]}
        if t is None:
            issues.append({"severity": "error", "field": "claims", "message": f"Сравнение {key} не проводилось", "suggested": None})
            continue
        if abs(cl["delta_pp"] - t["delta_pp"]) > TOL_PP:
            issues.append({"severity": "error", "field": "claims",
                           "message": f"Δ({cl['a']} vs {cl['b']}) заявлено {cl['delta_pp']:+.2f} п.п., фактически {t['delta_pp']:+.2f}",
                           "suggested": t["delta_pp"]})
        sig = t["p_holm"] < alpha
        if bool(cl["significant"]) != sig:
            issues.append({"severity": "error", "field": "claims",
                           "message": f"Значимость {key} указана неверно (p_holm={t['p_holm']:.4g})", "suggested": sig})
    best_true = max(means_pp, key=means_pp.get)
    if analysis.get("best_strategy") != best_true:
        issues.append({"severity": "error", "field": "best_strategy",
                       "message": f"Лучшая стратегия по средней доле — {best_true}, а не {analysis.get('best_strategy')}",
                       "suggested": best_true})
    if not analysis.get("caveats"):
        issues.append({"severity": "warning", "field": "caveats", "message": "Не указаны ограничения модели", "suggested": None})
    return issues
