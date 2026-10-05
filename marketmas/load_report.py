"""Анализ распределения нагрузки по логу прогона: доля вызовов LLM+инструментов на агента (порог 40%)."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .logging_utils import read_log

THRESHOLD = 0.40


def load_stats(log_path: Path) -> dict:
    recs = read_log(log_path)
    calls = [r for r in recs if r["kind"] in ("llm", "tool")]
    total = len(calls)
    by_agent = Counter(r["agent"] for r in calls)
    llm = Counter(r["agent"] for r in calls if r["kind"] == "llm")
    tool = Counter(r["agent"] for r in calls if r["kind"] == "tool")
    errors = Counter(r["agent"] for r in calls if r["status"] in ("error", "retry"))
    rows = []
    for agent, n in by_agent.most_common():
        rows.append({"agent": agent, "llm": llm[agent], "tool": tool[agent], "total": n,
                     "share": n / total if total else 0.0, "errors_or_retries": errors[agent]})
    max_share = max((r["share"] for r in rows), default=0.0)
    return {"total_calls": total, "rows": rows, "max_share": max_share, "balanced": max_share <= THRESHOLD,
            "status": next((r["status"] for r in reversed(recs) if r["name"] == "finish"), "unknown")}


def format_table(st: dict) -> str:
    out = ["| Агент | LLM | Инструменты | Всего | Доля | Ошибки/повторы |", "|---|---|---|---|---|---|"]
    for r in st["rows"]:
        out.append(f"| {r['agent']} | {r['llm']} | {r['tool']} | {r['total']} | {r['share'] * 100:.1f}% | {r['errors_or_retries']} |")
    out.append(f"| **Итого** | | | **{st['total_calls']}** | max = {st['max_share'] * 100:.1f}% "
               f"({'≤' if st['balanced'] else '>'} 40%) | |")
    return "\n".join(out)


def plot_load(st: dict, path: Path) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = sorted(st["rows"], key=lambda r: r["share"])
    fig, ax = plt.subplots(figsize=(7, 3.6), dpi=120)
    ax.barh([r["agent"] for r in rows], [r["share"] * 100 for r in rows], color="#4C78A8")
    ax.axvline(40, color="#b23", linestyle="--", linewidth=1)
    ax.text(40.5, -0.4, "порог 40%", color="#b23", fontsize=8)
    for i, r in enumerate(rows):
        ax.text(r["share"] * 100 + 0.5, i, f"{r['share'] * 100:.1f}% ({r['total']})", va="center", fontsize=8)
    ax.set_xlabel("Доля вызовов LLM + инструментов, %")
    ax.set_xlim(0, 50)
    ax.set_title(f"Распределение нагрузки (всего вызовов: {st['total_calls']})", fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return str(path)
