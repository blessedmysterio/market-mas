"""Агент «Маркет-исследователь»: собирает параметры рынка (БД) и релевантную литературу (OpenAlex/кэш)."""
from __future__ import annotations

from functools import partial

from .. import heuristics as H
from ..messages import MarketContext, Reference, ResearchQuery
from ..tools.base import Tool, ToolError
from ..tools.literature import cached_literature, openalex_search
from ..tools.market_db import market_lookup
from .base import Agent


class MarketResearcher(Agent):
    name = "market_researcher"
    role = "Определяет отрасль и собирает параметры рынка и научные источники для калибровки модели"
    inputs = "research_task {brief}"
    outputs = "MarketContext (бренды, доли, качество, цены, чувствительности, стоимости, ссылки)"
    done_when = "Параметры рынка получены из БД и найдено ≥1 источника (OpenAlex или кэш)"

    def build_tools(self):
        s = self.s
        return [
            Tool("market_lookup", "Параметры рынка по отрасли из SQLite-справочника",
                 partial(market_lookup, s.outputs_dir / "market.db", s.data_dir / "market_benchmarks.csv"), external=True),
            Tool("openalex_search", "Поиск научных работ в OpenAlex API",
                 lambda query, n=5: openalex_search(query, n, s.openalex_url, s.http_timeout_s, s.openalex_mailto,
                                                    simulate_down="openalex_down" in s.faults), external=True),
            Tool("literature_cache", "Офлайн-кэш ключевых работ (фолбэк)",
                 lambda query, n=5: cached_literature(s.data_dir / "openalex_cache.json", query, n), external=True),
        ]

    def handle(self, payload_type, payload):
        brief = payload["brief"]

        def heuristic():
            strategies = H.detect_strategies(brief)
            return ResearchQuery(industry=H.detect_industry(brief),
                                 literature_query=H.literature_query(strategies, H.detect_crisis(brief)))

        q = self.think({"brief": brief, "known_industries": list(H.INDUSTRY_WORDS)}, ResearchQuery, heuristic,
                       label="plan_research")
        mkt = self.call_tool("market_lookup", industry=q.industry)
        notes = [mkt["note"]]
        if not mkt["found"]:
            notes.append(f"Отрасль '{q.industry}' не найдена в справочнике — использованы параметры по умолчанию")
        try:
            refs = self.call_tool("openalex_search", query=q.literature_query, n=5)
        except ToolError as e:
            notes.append(f"OpenAlex недоступен ({str(e)[:80]}…) — источники взяты из офлайн-кэша")
            refs = self.call_tool("literature_cache", query=q.literature_query, n=5)
        ctx = MarketContext(
            industry=mkt["industry"], focus_brand=mkt["brands"][0], brands=mkt["brands"],
            base_shares=mkt["base_shares"], quality=mkt["quality"], price=mkt["price"],
            social_weight=mkt["social_weight"], price_sensitivity=mkt["price_sensitivity"],
            churn_rate=mkt["churn_rate"], cpm_kzt=mkt["cpm_kzt"], seed_cost_kzt=mkt["seed_cost_kzt"],
            references=[Reference(**r) for r in refs], data_notes=notes,
        )
        # segment_size/arpu нужны дизайнеру — кладём в blackboard рядом
        self.rt.state.put(self.rt.run_id, "market_extra", {"segment_size": mkt["segment_size"], "arpu_kzt": mkt["arpu_kzt"]})
        return "MarketContext", ctx
