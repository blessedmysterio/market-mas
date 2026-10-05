"""Инструменты дизайнера сценариев: каталог стратегий и перевод бюджета в интенсивность вмешательства."""
from __future__ import annotations

import math

STRATEGY_CATALOG = {
    "baseline": "Без вмешательства (контрольная группа).",
    "hub_seeding": "Посев среди хабов: конверсия узлов с максимальной степенью в адвокатов бренда (дороже за контакт).",
    "random_seeding": "Посев среди случайных потребителей (дешевле за контакт).",
    "mass_media": "Массовая реклама: временный бонус полезности для всех потребителей.",
    "price_cut": "Временное снижение цены фокального бренда (ценовая война).",
}

HUB_COST_MULT = 3.0   # контакт с хабом (инфлюенсером) дороже обычного посева
AD_MAX, AD_F50 = 0.8, 120.0


def strategy_catalog() -> dict:
    return {"strategies": STRATEGY_CATALOG, "notes": [
        "Для корректного сравнения всегда включайте baseline или минимум две активные стратегии.",
        "Бюджет у всех активных стратегий одинаковый — сравнение при равных затратах.",
    ]}


def budget_to_intensity(*, budget_kzt: float, n_agents: int, seed_cost_kzt: float, segment_size: float,
                        cpm_kzt: float, arpu_kzt: float) -> dict:
    """Масштабирование: n_agents моделирует сегмент segment_size потребителей."""
    if budget_kzt <= 0:
        return {"random_seeds": 0, "hub_seeds": 0, "ad_boost": 0.0, "price_cut": 0.0}
    frac_random = budget_kzt / seed_cost_kzt / segment_size
    frac_hub = frac_random / HUB_COST_MULT
    random_seeds = int(min(round(frac_random * n_agents), 0.15 * n_agents))
    hub_seeds = int(min(round(frac_hub * n_agents), 0.05 * n_agents))
    impressions = budget_kzt / cpm_kzt * 1000
    freq = impressions / segment_size
    ad_boost = AD_MAX * (1 - math.exp(-freq / AD_F50))
    price_cut = min(budget_kzt / (segment_size * arpu_kzt), 0.30)
    return {"random_seeds": max(random_seeds, 1), "hub_seeds": max(hub_seeds, 1),
            "ad_boost": round(ad_boost, 4), "price_cut": round(price_cut, 4)}
