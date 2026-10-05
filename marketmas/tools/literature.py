"""Инструмент: поиск научной литературы через OpenAlex API (внешний источник) с офлайн-кэшем."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

from .base import ToolError


def openalex_search(query: str, n: int, url: str, timeout_s: float, mailto: str | None = None,
                    simulate_down: bool = False) -> list[dict]:
    if simulate_down:
        raise ToolError("OpenAlex недоступен (внедрённый отказ openalex_down)")
    params = {"search": query, "per-page": max(1, min(n, 10)), "sort": "cited_by_count:desc",
              "select": "title,publication_year,doi,cited_by_count,primary_location"}
    if mailto:
        params["mailto"] = mailto
    full = url + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(full, timeout=timeout_s) as r:
            data = json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001 — любая сетевая ошибка → retryable
        raise ToolError(f"OpenAlex: {type(e).__name__}: {e}") from e
    out = []
    for w in data.get("results", []):
        venue = None
        loc = w.get("primary_location") or {}
        if loc.get("source"):
            venue = loc["source"].get("display_name")
        doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
        out.append({"title": w.get("title"), "year": w.get("publication_year"), "venue": venue,
                    "doi": doi, "cited_by": w.get("cited_by_count"), "source": "openalex"})
    if not out:
        raise ToolError("OpenAlex вернул пустой результат", retryable=False)
    return out


def cached_literature(cache_path: Path, query: str, n: int) -> list[dict]:
    """Фолбэк: ранжирование кэша по пересечению слов запроса с тегами/названием."""
    works = json.loads(cache_path.read_text(encoding="utf-8"))["works"]
    words = {w.strip(".,").lower() for w in query.split() if len(w) > 2}

    def score(w: dict) -> int:
        text = " ".join(w.get("tags", [])) + " " + w["title"].lower()
        return sum(1 for x in words if x in text)

    ranked = sorted(works, key=score, reverse=True)[:n]
    return [{"title": w["title"], "year": w["year"], "venue": w["venue"], "doi": w["doi"],
             "cited_by": None, "source": "cache"} for w in ranked]
