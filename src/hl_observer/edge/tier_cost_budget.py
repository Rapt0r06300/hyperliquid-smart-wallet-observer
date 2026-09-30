"""V26 L7 — Budget de coûts par tier de leader (repo 17) + WE/WEL (passivbot).

* Tier depuis le score leader (S/A/B/WATCH) ; chaque tier a un budget de coûts
  (bps) : un leader S justifie de payer plus de dégradation de copie qu'un B.
  Coûts (copy_degradation_bps) > budget(tier) ⇒ ``COST_BUDGET_EXCEEDED``.
* Wallet Exposure passivbot : WE = notionnel / solde non-levier ;
  WEL par position = total_limit / n_positions ; ``check_add_allowed`` refuse
  l'ADD au-delà du WEL (complète le cap d'exposition existant, ne le remplace pas).

Pur, sans I/O. Opt-in : ``HYPERSMART_V26_TIER_COST_BUDGET=1``. Paper-only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

MASTER_FLAG = "HYPERSMART_V26_TIER_COST_BUDGET"
S_MIN_ENV = "HYPERSMART_V26_TIER_S_MIN_SCORE"
A_MIN_ENV = "HYPERSMART_V26_TIER_A_MIN_SCORE"
B_MIN_ENV = "HYPERSMART_V26_TIER_B_MIN_SCORE"
S_BUDGET_ENV = "HYPERSMART_V26_TIER_S_BUDGET_BPS"
A_BUDGET_ENV = "HYPERSMART_V26_TIER_A_BUDGET_BPS"
B_BUDGET_ENV = "HYPERSMART_V26_TIER_B_BUDGET_BPS"
WATCH_BUDGET_ENV = "HYPERSMART_V26_TIER_WATCH_BUDGET_BPS"

_DEF = {
    S_MIN_ENV: 85.0, A_MIN_ENV: 70.0, B_MIN_ENV: 50.0,
    S_BUDGET_ENV: 80.0, A_BUDGET_ENV: 50.0, B_BUDGET_ENV: 30.0, WATCH_BUDGET_ENV: 20.0,
}

REASON_BUDGET = "COST_BUDGET_EXCEEDED"


def _f(name: str, env: dict | None = None) -> float:
    e = env if env is not None else os.environ
    try:
        return float(e.get(name, _DEF[name]) or _DEF[name])
    except (TypeError, ValueError):
        return float(_DEF[name])


def flag_on(env: dict | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(MASTER_FLAG, "0")).strip().lower() in ("1", "true", "yes", "on")


def tier_of(leader_score: float, env: dict | None = None) -> str:
    s = float(leader_score or 0.0)
    if s >= _f(S_MIN_ENV, env):
        return "S"
    if s >= _f(A_MIN_ENV, env):
        return "A"
    if s >= _f(B_MIN_ENV, env):
        return "B"
    return "WATCH"


def budget_bps_for_tier(tier: str, env: dict | None = None) -> float:
    return {
        "S": _f(S_BUDGET_ENV, env),
        "A": _f(A_BUDGET_ENV, env),
        "B": _f(B_BUDGET_ENV, env),
    }.get(str(tier).upper(), _f(WATCH_BUDGET_ENV, env))


def cost_budget_veto(*, leader_score: float | None, copy_degradation_bps: float | None,
                     env: dict | None = None) -> str | None:
    """Retourne ``COST_BUDGET_EXCEEDED`` ou None. Inconnu (None) ne bloque jamais."""
    if leader_score is None or copy_degradation_bps is None:
        return None
    tier = tier_of(leader_score, env)
    if float(copy_degradation_bps) > budget_bps_for_tier(tier, env):
        return REASON_BUDGET
    return None


# ── WE / WEL (passivbot risk_management.md §1) ─────────────────────────────

@dataclass(frozen=True, slots=True)
class ExposureCheck:
    we: float                 # wallet exposure courant (après l'ajout envisagé)
    wel_per_position: float   # limite par position
    allowed: bool
    reason: str | None


def wallet_exposure(position_notional_usd: float, unleveraged_balance_usd: float) -> float:
    if unleveraged_balance_usd <= 0:
        return float("inf")
    return max(0.0, float(position_notional_usd)) / float(unleveraged_balance_usd)


def wel_per_position(total_wallet_exposure_limit: float, n_positions: int) -> float:
    return float(total_wallet_exposure_limit) / max(1, int(n_positions))


def check_add_allowed(
    *,
    current_position_notional_usd: float,
    add_notional_usd: float,
    unleveraged_balance_usd: float,
    total_wallet_exposure_limit: float,
    n_positions: int,
) -> ExposureCheck:
    """Refuse un ADD qui pousserait la position au-delà de son WEL (passivbot)."""
    wel = wel_per_position(total_wallet_exposure_limit, n_positions)
    we_after = wallet_exposure(
        current_position_notional_usd + max(0.0, add_notional_usd), unleveraged_balance_usd
    )
    if we_after > wel:
        return ExposureCheck(round(we_after, 6), round(wel, 6), False, "PORTFOLIO_EXPOSURE_TOO_HIGH")
    return ExposureCheck(round(we_after, 6), round(wel, 6), True, None)


__all__ = [
    "MASTER_FLAG", "REASON_BUDGET", "flag_on", "tier_of", "budget_bps_for_tier",
    "cost_budget_veto", "ExposureCheck", "wallet_exposure", "wel_per_position", "check_add_allowed",
]
