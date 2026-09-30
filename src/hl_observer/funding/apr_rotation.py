"""Distillation HL-Delta (cgaspart, 40★) + X: gate APR, rotation, drift delta.

Idées copiées (logique, pas code) des meilleurs repos d'arbitrage:
  - GATE EN RENDEMENT ANNUALISÉ: gate l'entrée sur l'APR (≥5% défaut) au lieu du
    bps/heure brut — comparable entre coins, intuitif (HL-Delta).
  - ROTATION D'OPPORTUNITÉ: si le rendement de la paire courante tombe sous le
    seuil ET qu'une meilleure paire existe, on tourne vers la meilleure (HL-Delta
    "position switching"). Toujours dans la meilleure opportunité.
  - REBALANCE SUR DRIFT DELTA: quand les 2 jambes divergent de >seuil (5% défaut),
    on rééquilibre au lieu de fermer (HL-Delta allocation.rebalance_threshold).
  - Timing: le funding HL se règle chaque heure → vérifier juste avant (min 50).

Pur, déterministe, read-only. Aucune promesse de PnL.
"""

from __future__ import annotations

from dataclasses import dataclass

HOURS_PER_YEAR = 24 * 365


def annualized_yield_pct(rate_bps_per_hour: float) -> float:
    """bps/heure → rendement annualisé %. Ex: 2.5 bps/h ≈ 21.9%/an."""
    return round(float(rate_bps_per_hour) / 10_000.0 * HOURS_PER_YEAR * 100.0, 4)


def passes_apr_gate(rate_bps_per_hour: float, *, min_apr_pct: float = 5.0) -> bool:
    return abs(annualized_yield_pct(rate_bps_per_hour)) >= float(min_apr_pct)


@dataclass(frozen=True, slots=True)
class RotationDecision:
    action: str          # HOLD | ROTATE | EXIT
    from_coin: str | None
    to_coin: str | None
    reason: str


def decide_rotation(
    *,
    current_coin: str | None,
    current_rate_bps_per_hour: float | None,
    candidates: dict[str, float],   # coin -> rate_bps_per_hour disponible
    min_apr_pct: float = 5.0,
    switch_margin_apr_pct: float = 3.0,
) -> RotationDecision:
    """Décide s'il faut tenir, tourner vers mieux, ou sortir (edge mort).

    On ne tourne que si la meilleure alternative dépasse le courant d'une MARGE
    (anti-ping-pong sur du bruit), et si le courant est sous le gate.
    """
    ranked = sorted(((abs(annualized_yield_pct(r)), c, r) for c, r in (candidates or {}).items()), reverse=True)
    best = ranked[0] if ranked else None

    if current_coin is None or current_rate_bps_per_hour is None:
        if best and best[0] >= min_apr_pct:
            return RotationDecision("ROTATE", None, best[1], "ENTER_BEST_APR")
        return RotationDecision("HOLD", None, None, "NO_QUALIFYING_OPPORTUNITY")

    cur_apr = abs(annualized_yield_pct(current_rate_bps_per_hour))
    if cur_apr < min_apr_pct:
        if best and best[1] != current_coin and best[0] >= min_apr_pct:
            return RotationDecision("ROTATE", current_coin, best[1], "CURRENT_DECAYED_ROTATE_TO_BETTER")
        return RotationDecision("EXIT", current_coin, None, "CURRENT_BELOW_APR_NO_ALTERNATIVE")
    # courant encore bon: ne tourner que si une alternative bat nettement (marge)
    if best and best[1] != current_coin and (best[0] - cur_apr) >= switch_margin_apr_pct:
        return RotationDecision("ROTATE", current_coin, best[1], "BETTER_OPPORTUNITY_BEYOND_MARGIN")
    return RotationDecision("HOLD", current_coin, current_coin, "CURRENT_STILL_BEST")


def delta_drift_action(long_leg_usdt: float, short_leg_usdt: float, *, rebalance_threshold: float = 0.05) -> dict:
    """Delta-neutre = jambes égales. Si divergence > seuil → rééquilibrer (pas fermer)."""
    a, b = abs(float(long_leg_usdt)), abs(float(short_leg_usdt))
    base = max(a, b) or 1.0
    drift = abs(a - b) / base
    if drift > float(rebalance_threshold):
        return {"action": "REBALANCE", "drift_pct": round(drift * 100, 3),
                "heavier": "LONG" if a > b else "SHORT", "reason": "DELTA_DRIFT_EXCEEDS_THRESHOLD"}
    return {"action": "HOLD", "drift_pct": round(drift * 100, 3), "reason": "DELTA_WITHIN_TOLERANCE"}


def near_funding_settlement(utc_minute: int, *, window_before: int = 10) -> bool:
    """HL règle le funding à l'heure pile → fenêtre d'action juste avant (min 50-59)."""
    return int(utc_minute) >= (60 - int(window_before))


__all__ = ["annualized_yield_pct", "passes_apr_gate", "RotationDecision",
           "decide_rotation", "delta_drift_action", "near_funding_settlement"]
