"""Инструмент: агентная модель конкуренции брендов на безмасштабной сети (Barabási–Albert).

Модель (дискретное время):
* N потребителей — узлы BA-графа (параметр m). У каждого текущий бренд из K.
* На шаге t потребитель с вероятностью churn пересматривает выбор (агенты-адвокаты — реже).
* Полезность бренда k:  U_ik = b_q·q_k − b_p·ps·p_k/mean(p) + b_s·sw·s_ik + inertia·[k = текущий] + ad_k + Gumbel
  где s_ik — взвешенная доля соседей с брендом k (адвокаты весят больше).
* Выбор — argmax U (эквивалент логит-модели).
* Вмешательства фокального бренда (индекс 0) на шаге intervention_step:
  hub_seeding / random_seeding — конверсия k узлов (топ по степени / случайных) в адвокатов;
  mass_media — рекламный бонус всем на ad_steps шагов; price_cut — снижение цены на promo_steps шагов.
* Shock — репутационный кризис: падение качества фокального бренда.
* Common random numbers: при одинаковом seed все стратегии видят одну и ту же сеть и шум,
  поэтому сравнения парные.
"""
from __future__ import annotations

import time
from functools import lru_cache

import networkx as nx
import numpy as np

# Поведенческие коэффициенты модели
B_Q, B_P, B_S, INERTIA = 2.0, 1.5, 1.2, 1.5
ADVOCATE_WEIGHT = 2.0
ADVOCATE_CHURN_MULT = 0.3
AD_STEPS = 15
PROMO_STEPS = 20


@lru_cache(maxsize=64)
def generate_network(n: int, m: int, seed: int):
    g = nx.barabasi_albert_graph(n, m, seed=seed)
    adj = nx.to_scipy_sparse_array(g, format="csr", dtype=np.float32)
    deg = np.asarray(adj.sum(axis=1)).ravel()
    return adj, deg


def simulate_run(*, n: int, m: int, n_steps: int, strategy: str, intensities: dict, intervention_step: int,
                 base_shares, quality, price, social_weight: float, price_sensitivity: float, churn: float,
                 shock: dict | None, seed: int) -> tuple[np.ndarray, int]:
    adj, deg = generate_network(n, m, seed)
    k_brands = len(base_shares)
    rng = np.random.default_rng(seed)           # общий шум (CRN)
    rng_iv = np.random.default_rng(seed + 99991)  # отдельный поток для вмешательств — не сдвигает общий шум

    shares = np.asarray(base_shares, dtype=float)
    shares = shares / shares.sum()
    choice = rng.choice(k_brands, size=n, p=shares)
    q = np.asarray(quality, dtype=float).copy()
    p = np.asarray(price, dtype=float).copy()
    p0_orig = p[0]
    w = np.ones(n)
    churn_vec = np.full(n, churn)
    ad = np.zeros(k_brands)
    ad_until = -1
    promo_until = -1
    eye = np.eye(k_brands)
    traj = np.empty(n_steps)
    seeds_used = 0

    for t in range(n_steps):
        if shock and t == shock["at_step"]:
            q[0] = max(0.0, q[0] - shock["quality_drop"])
        if t == intervention_step:
            if strategy == "hub_seeding":
                k = int(intensities.get("hub_seeds", 0))
                idx = np.argsort(-deg, kind="stable")[:k]
            elif strategy == "random_seeding":
                k = int(intensities.get("random_seeds", 0))
                idx = rng_iv.choice(n, size=min(k, n), replace=False)
            else:
                idx = np.array([], dtype=int)
            if idx.size:
                choice[idx] = 0
                w[idx] = ADVOCATE_WEIGHT
                churn_vec[idx] = churn * ADVOCATE_CHURN_MULT
                seeds_used = int(idx.size)
            if strategy == "mass_media":
                ad[0] = intensities.get("ad_boost", 0.0)
                ad_until = t + AD_STEPS
            if strategy == "price_cut":
                p[0] = p0_orig * (1 - intensities.get("price_cut", 0.0))
                promo_until = t + PROMO_STEPS
        if t == ad_until:
            ad[0] = 0.0
        if t == promo_until:
            p[0] = p0_orig

        onehot = eye[choice]
        neigh = adj @ (onehot * w[:, None])
        tot = neigh.sum(axis=1, keepdims=True)
        s = np.divide(neigh, tot, out=np.full_like(neigh, 1.0 / k_brands), where=tot > 0)
        util = (B_Q * q - B_P * price_sensitivity * p / p.mean())[None, :] + B_S * social_weight * s \
            + INERTIA * onehot + ad[None, :]
        noise = rng.gumbel(size=(n, k_brands))
        reconsider = rng.random(n) < churn_vec
        new_choice = np.argmax(util + noise, axis=1)
        choice = np.where(reconsider, new_choice, choice)
        traj[t] = np.mean(choice == 0)
    return traj, seeds_used


def simulate_strategy(*, spec: dict, ctx: dict, strategy: str, n_runs: int, base_seed: int,
                      deadline_s: float | None = None, slow: bool = False) -> dict:
    """Прогоняет стратегию n_runs раз (seed = base_seed + i). Возвращает доли и среднюю траекторию."""
    t0 = time.monotonic()
    finals, trajs, seeds_used = [], [], 0
    for i in range(n_runs):
        if slow:
            time.sleep(0.2)
        if deadline_s is not None and time.monotonic() - t0 > deadline_s:
            raise TimeoutError(f"simulate_strategy({strategy}) превысил отведённые {deadline_s:.1f} с")
        traj, seeds_used = simulate_run(
            n=spec["n_agents"], m=spec["ba_m"], n_steps=spec["n_steps"], strategy=strategy,
            intensities=spec["intensities"], intervention_step=spec["intervention_step"],
            base_shares=ctx["base_shares"], quality=ctx["quality"], price=ctx["price"],
            social_weight=ctx["social_weight"], price_sensitivity=ctx["price_sensitivity"],
            churn=ctx["churn_rate"], shock=spec.get("shock"), seed=base_seed + i,
        )
        finals.append(float(traj[-1]))
        trajs.append(traj)
    mean_traj = np.mean(trajs, axis=0)
    return {"strategy": strategy, "final_shares": finals,
            "mean_trajectory": [round(float(x), 5) for x in mean_traj], "seeds_used": seeds_used}
