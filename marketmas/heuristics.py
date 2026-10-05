"""Детерминированный разбор брифа (RU/EN). Используется:
1) в офлайн-режиме (MockLLM) как «ответ модели»;
2) как фолбэк, если реальная LLM не вернула валидный JSON.
"""
from __future__ import annotations

import re

SCOPE_WORDS = ["маркет", "бренд", "реклам", "стратег", "посев", "инфлюенс", "блогер", "хаб", "цен", "скидк", "акци",
               "кризис", "скандал", "репутац", "доля", "долю", "клиент", "потребител", "покупател", "кампани", "продвиж",
               "marketing", "brand", "campaign", "seeding", "influencer", "market", "price", "promo", "advert", "customer"]

INDUSTRY_WORDS = {
    "telecom": ["оператор", "связ", "мобильн", "телеком", "telecom", "тариф", "sim"],
    "fmcg": ["напит", "снек", "fmcg", "йогурт", "шоколад", "сок", "газиров", "молоч"],
    "fintech": ["банк", "финтех", "платеж", "платёж", "кредит", "fintech", "bank", "кошел"],
    "ecommerce": ["маркетплейс", "интернет-магазин", "e-commerce", "ecommerce", "онлайн-магазин", "marketplace"],
    "auto": ["авто", "машин", "автомоб", "car ", "cars", "дилер"],
    "fashion": ["одежд", "мода", "fashion", "обув", "кроссов"],
    "foodtech": ["доставк", "foodtech", "ресторан", "еды", "food delivery"],
}

STRATEGY_WORDS = {
    "hub_seeding": ["хаб", "инфлюенс", "лидер", "блогер", "influencer", "hub", "амбассадор", "звезд"],
    "random_seeding": ["случайн", "random", "семплинг", "сэмплинг", "пробник"],
    "mass_media": ["массов", "реклам", "тв", "телевиз", "наружн", "баннер", "mass", "ads", "медийн"],
    "price_cut": ["цен", "скидк", "price", "discount", "демпинг", "дешевл"],
}
CRISIS_WORDS = ["кризис", "скандал", "репутац", "crisis", "scandal", "отравлен", "утечк", "бойкот"]

LIT_QUERIES = {
    "hub_seeding": "hub seeding influencers social network marketing",
    "random_seeding": "seeding strategies viral marketing",
    "mass_media": "mass media advertising word of mouth diffusion",
    "price_cut": "price competition agent-based market simulation",
}

_MULT = [(r"млрд|миллиард\w*|bn|billion", 1e9), (r"млн|миллион\w*|mln|million|m\b", 1e6), (r"тыс\w*|k\b|thousand", 1e3)]
_NUM = r"(\d[\d\s]*(?:[.,]\d+)?)\s*(млрд|миллиард\w*|млн|миллион\w*|тыс\w*|bn|billion|mln|million|thousand|k|m)?\b\.?\s*"


def _to_num(raw: str, mult: str | None) -> float:
    v = float(raw.replace(" ", "").replace(",", "."))
    if mult:
        for pat, k in _MULT:
            if re.fullmatch(pat, mult.lower()):
                return v * k
    return v


def _find(text: str, nouns: str) -> float | None:
    m = re.search(_NUM + r"(?:\w+\s){0,1}(" + nouns + r")", text, flags=re.I)
    return _to_num(m.group(1), m.group(2)) if m else None


def in_scope(brief: str) -> bool:
    t = brief.lower()
    return sum(w in t for w in SCOPE_WORDS) >= 1 and len(t.split()) >= 4


def detect_industry(brief: str) -> str:
    t = brief.lower() + " "
    best, score = "default", 0
    for ind, words in INDUSTRY_WORDS.items():
        sc = sum(w in t for w in words)
        if sc > score:
            best, score = ind, sc
    return best


def detect_strategies(brief: str) -> list[str]:
    t = brief.lower()
    found = [s for s, words in STRATEGY_WORDS.items() if any(w in t for w in words)]
    if not found:
        found = ["hub_seeding", "random_seeding", "mass_media"]
    return ["baseline", *found][:5]


def detect_crisis(brief: str) -> bool:
    t = brief.lower()
    return any(w in t for w in CRISIS_WORDS)


def parse_numbers(brief: str) -> dict:
    out: dict = {}
    b = _find(brief, r"тенге|тг|₸|kzt|tenge")
    if b is None:
        m = re.search(r"бюджет\w*\s*(?:в\s*)?" + _NUM, brief, flags=re.I) or re.search(r"budget\s*(?:of\s*)?" + _NUM, brief, flags=re.I)
        if m:
            b = _to_num(m.group(1), m.group(2))
    if b is not None:
        out["budget_kzt"] = b
    n = _find(brief, r"агент\w*|потребител\w*|узл\w*|узел|agents?|nodes?|клиент\w*")
    if n is not None:
        out["n_agents"] = int(n)
    r = _find(brief, r"прогон\w*|запуск\w*|повтор\w*|runs?|симуляц\w*")
    if r is not None:
        out["n_runs"] = int(r)
    s = _find(brief, r"шаг\w*|недел\w*|steps?|period\w*")
    if s is not None:
        out["n_steps"] = int(s)
    return out


def literature_query(strategies: list[str], crisis: bool) -> str:
    active = [s for s in strategies if s != "baseline"]
    q = LIT_QUERIES.get(active[0], "agent-based simulation marketing") if active else "agent-based simulation marketing"
    if crisis:
        q = "brand crisis reputation word of mouth " + q.split()[0]
    return q
