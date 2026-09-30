"""V13 #162 — 2 stratégies paper : contrarian-favorite-dip-hedge + panic-dip-hedge.

Recettes qui, sur données réelles, proposent un PaperIntent (simulation_only forcé). Elles ne
placent JAMAIS d'ordre : un PaperIntent doit passer par le RiskEngine (approve_with_risk).
Pur / read-only.
"""

from __future__ import annotations

from hl_observer.strategies.models import IntentAction, IntentSide, PaperIntent


def propose_panic_dip_hedge(
    *, coin: str, recent_return_pct: float, window_ms: int,
    drop_threshold_pct: float = -15.0, max_window_ms: int = 3000,
    target_notional_usdt: float = 20.0, now_ms: int = 0,
) -> PaperIntent | None:
    """MrFadiAi DipArb : chute panique (> X% en Y s) -> achète le creux (couvert)."""
    if window_ms > max_window_ms:
        return None
    if recent_return_pct > drop_threshold_pct:
        return None                       # pas de panique
    confidence = min(1.0, abs(recent_return_pct) / abs(drop_threshold_pct))
    return PaperIntent(
        strategy_id="panic_dip_hedge@v1", coin=str(coin).upper(), side=IntentSide.LONG,
        action=IntentAction.OPEN, target_notional_usdt=float(target_notional_usdt),
        confidence=round(confidence, 4), reasons=("PANIC_DIP", "HEDGED"), created_at_ms=int(now_ms),
    )


def propose_contrarian_favorite_dip_hedge(
    *, coin: str, favorite_prob: float, short_term_return_pct: float,
    min_favorite_prob: float = 0.65, dip_threshold_pct: float = -1.0,
    target_notional_usdt: float = 20.0, now_ms: int = 0,
) -> PaperIntent | None:
    """mlmodelpoly z_contra : un FAVORI (proba haute) qui dippe -> on ajoute à contre-courant (couvert)."""
    if favorite_prob < min_favorite_prob:
        return None                       # pas un favori
    if short_term_return_pct > dip_threshold_pct:
        return None                       # pas de dip
    confidence = min(1.0, float(favorite_prob))
    return PaperIntent(
        strategy_id="contrarian_favorite_dip_hedge@v1", coin=str(coin).upper(), side=IntentSide.LONG,
        action=IntentAction.ADD, target_notional_usdt=float(target_notional_usdt),
        confidence=round(confidence, 4), reasons=("FAVORITE_DIP", "CONTRARIAN", "HEDGED"),
        created_at_ms=int(now_ms),
    )


__all__ = ["propose_panic_dip_hedge", "propose_contrarian_favorite_dip_hedge"]
