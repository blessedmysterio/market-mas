"""Инструменты аналитика: парные t-тесты, поправка Холма, график траекторий."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import stats


def paired_test(a: list[float], b: list[float]) -> dict:
    a_arr, b_arr = np.asarray(a) * 100, np.asarray(b) * 100  # в п.п.
    d = a_arr - b_arr
    n = len(d)
    mean_d = float(d.mean())
    sd = float(d.std(ddof=1)) if n > 1 else 0.0
    if sd == 0:
        t, p = (0.0, 1.0) if mean_d == 0 else (float("inf") * np.sign(mean_d), 0.0)
    else:
        t, p = stats.ttest_rel(a_arr, b_arr)
    se = sd / np.sqrt(n) if n > 1 else 0.0
    tcrit = stats.t.ppf(0.975, n - 1) if n > 1 else 0.0
    return {"mean_a_pp": round(float(a_arr.mean()), 3), "mean_b_pp": round(float(b_arr.mean()), 3),
            "delta_pp": round(mean_d, 3), "t_stat": round(float(t), 3), "p_value": float(p),
            "ci95_pp": (round(mean_d - tcrit * se, 3), round(mean_d + tcrit * se, 3)),
            "cohen_dz": round(mean_d / sd, 3) if sd else 0.0}


def holm(pvals: list[float]) -> list[float]:
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * pvals[idx])
        adj[idx] = min(1.0, running)
    return [float(x) for x in adj]


def plot_trajectories(results: list[dict], path: Path, title: str, intervention_step: int,
                      shock_step: int | None = None) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=120)
    for r in results:
        ax.plot(np.asarray(r["mean_trajectory"]) * 100, label=r["strategy"], linewidth=1.8)
    ax.axvline(intervention_step, color="grey", linestyle="--", linewidth=1)
    ax.text(intervention_step + 0.5, ax.get_ylim()[1], "вмешательство", va="top", fontsize=8, color="grey")
    if shock_step is not None:
        ax.axvline(shock_step, color="#b23", linestyle=":", linewidth=1)
    ax.set_xlabel("Шаг модели")
    ax.set_ylabel("Доля фокального бренда, %")
    ax.set_title(title[:90], fontsize=10)
    ax.grid(alpha=0.25)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return str(path)
