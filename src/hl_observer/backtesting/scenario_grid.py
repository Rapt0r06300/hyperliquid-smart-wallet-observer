"""Espace de scenarios pour la recherche MASSIVE du replay (preparation avant les 48h).

Objectif Flo : essayer le MAXIMUM de reglages differents pour trouver le plus robuste.
On balaye un espace a 8 dimensions de sortie/entree que le moteur replay respecte
REELLEMENT (via simulate_exit_on_path + SLTPConfig, sans lookahead) : sl_bps, tp_bps,
trailing_stop_bps (0=off), trailing_activation_bps, breakeven_bps, horizon_min, cost_bps
(fees+spread ; la degradation de copie reelle enregistree est ajoutee a l'eval), et un
filtre d'entree min_edge_bps.

Les 4 flags de vetos V26 ne sont PAS cross-multiplies ici (explosion combinatoire =
sur-apprentissage) : leur effet se mesure separement via ab_flag_replay sur le gagnant.

Sources : GRID coarse + ARCHETYPES + SAMPLER aleatoire seede -> dizaines de milliers.
Pur / deterministe / read-only.
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass

SL_BPS_GRID = [15.0, 25.0, 40.0, 60.0, 90.0]
TP_BPS_GRID = [30.0, 50.0, 80.0, 120.0, 180.0, 260.0]
TRAILING_GRID = [0.0, 30.0, 60.0, 120.0]
HORIZON_MIN_GRID = [30.0, 60.0, 120.0, 240.0, 480.0]
MIN_EDGE_GRID = [0.0, 10.0, 20.0, 30.0, 45.0]
COST_BPS_FIXED = 12.0

SL_RANGE = (8.0, 130.0)
TP_RANGE = (20.0, 420.0)
TRAILING_RANGE = (15.0, 220.0)
ACTIVATION_RANGE = (15.0, 220.0)
BREAKEVEN_RANGE = (0.0, 40.0)
MIN_EDGE_RANGE = (0.0, 60.0)

# --- Dimensions ADDITIONNELLES (V2) : filtres d'entree mappes aux champs REELS des
# candidats enregistres (signal_age_ms, liquidity_score, consensus_wallets,
# copy_degradation_bps, leader_score, direction) + cout variable + stop catastrophe.
# Defauts = permissif => 100% retro-compatible avec eval_trades (qui lit les 8 dims de base).
COST_BPS_GRID = [6.0, 8.0, 10.0, 12.0, 16.0]
MAX_SIGNAL_AGE_MS_GRID = [3000.0, 5000.0, 10000.0, 30000.0, 60000.0]
MIN_LIQUIDITY_GRID = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9]  # liquidity_score reel = 0..1 (pas 0..100)
MIN_CONSENSUS_GRID = [1, 2, 3, 4]
MAX_COPY_DEGRADATION_GRID = [8.0, 12.0, 20.0, 40.0, 1e9]  # 1e9 = pas de plafond
MIN_LEADER_SCORE_GRID = [0.0, 20.0, 40.0, 60.0, 70.0, 80.0]
SIDE_MODE_GRID = ["both", "long_only", "short_only"]
CATASTROPHIC_STOP_GRID = [0.0, 120.0, 180.0, 250.0, 400.0]  # 0 = off


@dataclass(frozen=True)
class Scenario:
    name: str
    sl_bps: float
    tp_bps: float
    trailing_stop_bps: float
    trailing_activation_bps: float
    breakeven_bps: float
    horizon_min: float
    cost_bps: float
    min_edge_bps: float
    source: str
    # --- dimensions additionnelles (defauts permissifs => retro-compat eval_trades) ---
    max_signal_age_ms: float = 0.0          # 0 = pas de filtre de fraicheur
    min_liquidity_score: float = 0.0
    min_consensus_wallets: int = 1
    max_copy_degradation_bps: float = 1e9   # tres grand = pas de plafond
    min_leader_score: float = 0.0
    side_mode: str = "both"                 # both | long_only | short_only
    catastrophic_stop_bps: float = 0.0      # 0 = off

    def key(self) -> tuple:
        return (
            round(self.sl_bps, 2), round(self.tp_bps, 2), round(self.trailing_stop_bps, 2),
            round(self.trailing_activation_bps, 2), round(self.breakeven_bps, 2),
            round(self.horizon_min, 2), round(self.cost_bps, 2), round(self.min_edge_bps, 2),
            round(self.max_signal_age_ms, 2), round(self.min_liquidity_score, 2),
            int(self.min_consensus_wallets), round(self.max_copy_degradation_bps, 2),
            round(self.min_leader_score, 2), self.side_mode, round(self.catastrophic_stop_bps, 2),
        )


def _mk(name, sl, tp, trail, act, be, hz, cost, min_edge, source, *,
        max_signal_age_ms=0.0, min_liquidity_score=0.0, min_consensus_wallets=1,
        max_copy_degradation_bps=1e9, min_leader_score=0.0, side_mode="both",
        catastrophic_stop_bps=0.0) -> Scenario:
    trail = float(trail)
    return Scenario(
        name=name, sl_bps=float(sl), tp_bps=float(tp), trailing_stop_bps=trail,
        trailing_activation_bps=float(act if trail > 0 else 0.0),
        breakeven_bps=float(be if trail > 0 else 0.0),
        horizon_min=float(hz), cost_bps=float(cost), min_edge_bps=float(min_edge), source=source,
        max_signal_age_ms=float(max_signal_age_ms), min_liquidity_score=float(min_liquidity_score),
        min_consensus_wallets=int(min_consensus_wallets),
        max_copy_degradation_bps=float(max_copy_degradation_bps),
        min_leader_score=float(min_leader_score), side_mode=str(side_mode),
        catastrophic_stop_bps=float(catastrophic_stop_bps),
    )


def grid_scenarios() -> list[Scenario]:
    out: list[Scenario] = []
    i = 0
    for sl, tp, trail, hz, me in itertools.product(
        SL_BPS_GRID, TP_BPS_GRID, TRAILING_GRID, HORIZON_MIN_GRID, MIN_EDGE_GRID
    ):
        act = trail * 1.5 if trail > 0 else 0.0
        out.append(_mk(f"grid_{i}", sl, tp, trail, act, 0.0, hz, COST_BPS_FIXED, me, "grid"))
        i += 1
    return out


_ARCHETYPES = [
    ("trend_follow_tight_sl_wide_tp", 22.0, 180.0, 0.0, 0.0, 0.0, 240.0, 20.0),
    ("trend_follow_trailing", 30.0, 300.0, 80.0, 120.0, 5.0, 480.0, 20.0),
    ("triple_barrier_balanced", 40.0, 80.0, 0.0, 0.0, 0.0, 240.0, 10.0),
    ("scalp_fast_small", 18.0, 40.0, 0.0, 0.0, 0.0, 60.0, 0.0),
    ("scalp_trailing_breakeven", 20.0, 60.0, 25.0, 35.0, 2.0, 60.0, 10.0),
    ("mean_revert_wide_sl_tight_tp", 70.0, 45.0, 0.0, 0.0, 0.0, 120.0, 0.0),
    ("selective_high_edge", 45.0, 120.0, 60.0, 90.0, 5.0, 240.0, 40.0),
    ("runner_let_it_ride", 35.0, 400.0, 120.0, 180.0, 8.0, 480.0, 15.0),
    ("cost_aware_scalp", 25.0, 70.0, 0.0, 0.0, 0.0, 120.0, 28.0),
    ("baseline_default", 40.0, 70.0, 0.0, 0.0, 0.0, 240.0, 0.0),
]


def archetype_scenarios() -> list[Scenario]:
    return [_mk(f"arch_{n}", sl, tp, tr, ac, be, hz, COST_BPS_FIXED, me, "archetype")
            for (n, sl, tp, tr, ac, be, hz, me) in _ARCHETYPES]


def sampled_scenarios(n: int, *, seed: int = 1) -> list[Scenario]:
    rng = random.Random(seed)
    out: list[Scenario] = []
    for i in range(max(0, int(n))):
        sl = round(rng.uniform(*SL_RANGE), 1)
        tp = round(rng.uniform(*TP_RANGE), 1)
        use_trail = rng.random() < 0.5
        trail = round(rng.uniform(*TRAILING_RANGE), 1) if use_trail else 0.0
        act = round(rng.uniform(*ACTIVATION_RANGE), 1) if use_trail else 0.0
        be = round(rng.uniform(*BREAKEVEN_RANGE), 1) if use_trail else 0.0
        hz = rng.choice(HORIZON_MIN_GRID)
        me = round(rng.uniform(*MIN_EDGE_RANGE), 1)
        out.append(_mk(f"samp_{i}", sl, tp, trail, act, be, hz, COST_BPS_FIXED, me, "sampled"))
    return out


def generate(max_scenarios: int = 20000, *, seed: int = 1) -> list[Scenario]:
    seen: set = set()
    out: list[Scenario] = []

    def _add(scenarios) -> bool:
        for s in scenarios:
            k = s.key()
            if k in seen:
                continue
            seen.add(k)
            out.append(s)
            if len(out) >= max_scenarios:
                return True
        return False

    if _add(archetype_scenarios()):
        return out
    if _add(grid_scenarios()):
        return out
    batch = 0
    while len(out) < max_scenarios and batch < 40:
        need = (max_scenarios - len(out)) * 2 + 100
        if _add(sampled_scenarios(need, seed=seed + batch)):
            break
        batch += 1
    return out[:max_scenarios]


# Ordre canonique des champs pour la materialisation (DB de scenarios).
SCENARIO_FIELDS = [
    "name", "source", "sl_bps", "tp_bps", "trailing_stop_bps", "trailing_activation_bps",
    "breakeven_bps", "horizon_min", "cost_bps", "min_edge_bps", "max_signal_age_ms",
    "min_liquidity_score", "min_consensus_wallets", "max_copy_degradation_bps",
    "min_leader_score", "side_mode", "catastrophic_stop_bps",
]


# Ordre canonique des 15 dimensions (sans name/source). Partage par _draw, la DB scale et le reader.
DIM_ORDER = [
    "sl_bps", "tp_bps", "trailing_stop_bps", "trailing_activation_bps", "breakeven_bps",
    "horizon_min", "cost_bps", "min_edge_bps", "max_signal_age_ms", "min_liquidity_score",
    "min_consensus_wallets", "max_copy_degradation_bps", "min_leader_score", "side_mode",
    "catastrophic_stop_bps",
]


def _draw(rng: random.Random) -> tuple:
    """Tirage brut des 15 dimensions (ordre rng STABLE => deterministe), dans l'ordre DIM_ORDER.
    Source UNIQUE partagee par _sample_one (Scenario) et sample_row (ligne DB brute)."""
    use_trail = rng.random() < 0.55
    trail = round(rng.uniform(*TRAILING_RANGE), 1) if use_trail else 0.0
    act = round(rng.uniform(*ACTIVATION_RANGE), 1) if use_trail else 0.0
    be = round(rng.uniform(*BREAKEVEN_RANGE), 1) if use_trail else 0.0
    sl = round(rng.uniform(*SL_RANGE), 1)
    tp = round(rng.uniform(*TP_RANGE), 1)
    hz = rng.choice(HORIZON_MIN_GRID)
    cost = rng.choice(COST_BPS_GRID)
    me = round(rng.uniform(*MIN_EDGE_RANGE), 1)
    msa = rng.choice(MAX_SIGNAL_AGE_MS_GRID)
    mliq = rng.choice(MIN_LIQUIDITY_GRID)
    mcons = rng.choice(MIN_CONSENSUS_GRID)
    mcd = rng.choice(MAX_COPY_DEGRADATION_GRID)
    mls = rng.choice(MIN_LEADER_SCORE_GRID)
    side = rng.choice(SIDE_MODE_GRID)
    cat = rng.choice(CATASTROPHIC_STOP_GRID)
    return (sl, tp, trail, act, be, hz, cost, me, msa, mliq, mcons, mcd, mls, side, cat)


def _sample_one(rng: random.Random, idx: int) -> Scenario:
    """Un scenario aleatoire sur les 15 dimensions (deterministe via _draw)."""
    (sl, tp, trail, act, be, hz, cost, me, msa, mliq, mcons, mcd, mls, side, cat) = _draw(rng)
    return Scenario(
        name=f"full_{idx}", sl_bps=float(sl), tp_bps=float(tp), trailing_stop_bps=float(trail),
        trailing_activation_bps=float(act), breakeven_bps=float(be), horizon_min=float(hz),
        cost_bps=float(cost), min_edge_bps=float(me), source="sampled_full",
        max_signal_age_ms=float(msa), min_liquidity_score=float(mliq),
        min_consensus_wallets=int(mcons), max_copy_degradation_bps=float(mcd),
        min_leader_score=float(mls), side_mode=str(side), catastrophic_stop_bps=float(cat),
    )


def sample_row(rng: random.Random) -> tuple:
    """Ligne DB brute (15 valeurs, ordre DIM_ORDER) SANS construire de Scenario => build grande echelle."""
    return _draw(rng)


def sampled_full(n: int, *, seed: int = 1) -> list[Scenario]:
    """Echantillonne les 15 dimensions (large couverture pour la DB de scenarios)."""
    rng = random.Random(seed)
    return [_sample_one(rng, i) for i in range(max(0, int(n)))]


def generate_many(target: int = 300000, *, seed: int = 7) -> list[Scenario]:
    """Espace ETENDU pour la DB de scenarios : archetypes + grid + gros sampler 15-dim, DISTINCT.

    Deterministe (seed). Pur / read-only. Ne touche ni logs ni runtime.
    """
    seen: set = set()
    out: list[Scenario] = []

    def _add(scenarios) -> bool:
        for s in scenarios:
            k = s.key()
            if k in seen:
                continue
            seen.add(k)
            out.append(s)
            if len(out) >= target:
                return True
        return False

    if _add(archetype_scenarios()):
        return out
    if _add(grid_scenarios()):
        return out
    batch = 0
    while len(out) < target and batch < 6000:
        need = (target - len(out)) * 2 + 500
        if _add(sampled_full(need, seed=seed * 1000 + batch)):
            break
        batch += 1
    return out[:target]


__all__ = [
    "Scenario", "SL_BPS_GRID", "TP_BPS_GRID", "TRAILING_GRID", "HORIZON_MIN_GRID",
    "MIN_EDGE_GRID", "COST_BPS_GRID", "MAX_SIGNAL_AGE_MS_GRID", "MIN_LIQUIDITY_GRID",
    "MIN_CONSENSUS_GRID", "MAX_COPY_DEGRADATION_GRID", "MIN_LEADER_SCORE_GRID",
    "SIDE_MODE_GRID", "CATASTROPHIC_STOP_GRID", "SCENARIO_FIELDS", "DIM_ORDER",
    "grid_scenarios", "archetype_scenarios", "sampled_scenarios", "sampled_full", "sample_row",
    "generate", "generate_many",
]
