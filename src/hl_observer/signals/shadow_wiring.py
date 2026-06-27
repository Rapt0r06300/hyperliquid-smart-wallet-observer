"""V13 — Shadow wiring of dormant quant modules into the live decision path.

The live copy-decision (routes.opportunity_metrics) historically used only the base
realtime score. A treasure of quant modules (whale-fill, vol-regime, multi-TF bias,
opportunity-ranker, streak sizing) was BUILT and TESTED but never reached the hot path.

This module computes their verdicts in **SHADOW**: it returns a flat dict of context-only
fields that the dashboard/ledger can expose. It NEVER changes the real decision by itself
(``context_only=True``); promotion to authoritative is a separate, explicit, env-gated step
(like the V12 gate). Pure / read-only: no order, no fabrication; each module call is guarded
so a single failure degrades gracefully (field = None) and never breaks the engine.
"""

from __future__ import annotations

from hl_observer.signals.whale_fill_signal import WhaleFillConfig, build_whale_fill_signal
from hl_observer.signals.opportunity_ranker import OpportunityInput, RankerConfig, power_score
from hl_observer.risk.regime_guard import regime_allows_paper
from hl_observer.risk.adaptive_sizing import compute_size_pct
from hl_observer.edge.bias_model import bias_from_closes


def classify_vol_regime(*, adverse_move_bps: float = 0.0, price_deviation_bps: float = 0.0,
                        high_bps: float = 30.0, panic_bps: float = 60.0) -> str:
    """Honest, conservative regime label from a volatility/adverse-move proxy.

    LOW/NORMAL = calm, HIGH = elevated, PANIC = extreme (regime_allows_paper -> False).
    """
    vol = max(abs(float(adverse_move_bps or 0.0)), abs(float(price_deviation_bps or 0.0)))
    if vol >= panic_bps:
        return "panic"
    if vol >= high_bps:
        return "high"
    if vol <= high_bps / 3.0:
        return "low"
    return "normal"


def compute_shadow_signals(
    *,
    action_type: str,
    coin: str,
    side: str,
    age_ms: int,
    consensus_wallets: int,
    leader_score: float,
    leader_notional_usdc: float,
    net_edge_bps: float,
    liquidity_score: float,
    directional_bias_bps: float = 0.0,
    leader_winrate: float | None = None,
    consecutive_losses: int = 0,
    consecutive_wins: int = 0,
    confidence: float = 1.0,
    adverse_move_bps: float = 0.0,
    price_deviation_bps: float = 0.0,
    closes_fast_tf: list[float] | None = None,
    closes_slow_tf: list[float] | None = None,
) -> dict:
    """Return SHADOW verdicts of the dormant modules. context_only — never decides alone."""
    out: dict = {"shadow_context_only": True, "shadow_changes_decision": False}

    # --- whale-fill freshness signal (Harrier A1) ---
    try:
        wf = build_whale_fill_signal(
            action_type=action_type, coin=coin, side=side,
            leader_notional_usdc=leader_notional_usdc, fill_age_ms=int(age_ms),
            leader_score=leader_score, consensus_wallets=int(consensus_wallets),
            config=WhaleFillConfig(),
        )
        out["shadow_whale_primary"] = None if wf is None else bool(wf.is_primary)
        out["shadow_whale_strength"] = None if wf is None else float(wf.strength)
        out["shadow_whale_reasons"] = "" if wf is None else "|".join(wf.reasons)
    except Exception:
        out["shadow_whale_primary"] = None
        out["shadow_whale_strength"] = None
        out["shadow_whale_reasons"] = ""

    # --- vol regime guard (CloddsBot A2) ---
    try:
        regime = classify_vol_regime(adverse_move_bps=adverse_move_bps,
                                     price_deviation_bps=price_deviation_bps)
        out["shadow_regime"] = regime
        out["shadow_regime_allows"] = bool(regime_allows_paper(regime))
    except Exception:
        out["shadow_regime"] = "unknown"
        out["shadow_regime_allows"] = True

    # --- multi-TF directional bias (mlmodelpoly A3 / bias_model) ---
    bias_bps = float(directional_bias_bps)
    try:
        if closes_fast_tf and closes_slow_tf:
            br = bias_from_closes(direction_side=side, closes_fast_tf=list(closes_fast_tf),
                                  closes_slow_tf=list(closes_slow_tf))
            bias_bps = float(br.bias_bps)
            out["shadow_bias_bps"] = bias_bps
            out["shadow_bias_aligned"] = bool(br.aligned)
            out["shadow_bias_combined"] = str(br.combined)
        else:
            out["shadow_bias_bps"] = None      # candles unavailable in this scope -> degraded
            out["shadow_bias_aligned"] = None
            out["shadow_bias_combined"] = None
    except Exception:
        out["shadow_bias_bps"] = None
        out["shadow_bias_aligned"] = None
        out["shadow_bias_combined"] = None

    # --- opportunity ranker power score (mlmodelpoly/Harrier) ---
    try:
        ps = power_score(OpportunityInput(
            coin=coin, side=side, net_edge_bps=float(net_edge_bps), signal_age_ms=int(age_ms),
            consensus_wallets=int(consensus_wallets), liquidity_score=float(liquidity_score),
            directional_bias_bps=float(bias_bps), leader_winrate=leader_winrate,
        ), RankerConfig())
        out["shadow_power_score"] = float(ps)          # 0 => failed a hard floor (drop)
    except Exception:
        out["shadow_power_score"] = None

    # --- streak-adaptive sizing (MrFadiAi A3) ---
    try:
        sd = compute_size_pct(consecutive_losses=int(consecutive_losses),
                              consecutive_wins=int(consecutive_wins),
                              confidence=float(confidence))
        out["shadow_size_pct"] = float(sd.size_pct)
        out["shadow_size_multiplier"] = float(sd.multiplier)
    except Exception:
        out["shadow_size_pct"] = None
        out["shadow_size_multiplier"] = None

    # --- local model P(profit) (V13 #147/#148) — SHADOW, never decides alone ---
    try:
        from hl_observer.ml.features import canonical_features
        from hl_observer.ml.inference import model_accepts, predict_p_profit
        _feats = canonical_features(
            net_edge_bps=net_edge_bps, signal_age_ms=age_ms, consensus_wallets=consensus_wallets,
            liquidity_score=liquidity_score, bias_bps=bias_bps,
            whale_strength=float(out.get("shadow_whale_strength") or 0.0),
            leader_score=leader_score, adverse_move_bps=adverse_move_bps,
            price_deviation_bps=price_deviation_bps,
        )
        _p = predict_p_profit(_feats)
        out["shadow_model_p_profit"] = None if _p is None else round(_p, 6)
        out["shadow_model_accept"] = model_accepts(_p)
    except Exception:
        out["shadow_model_p_profit"] = None
        out["shadow_model_accept"] = None

    return out


__all__ = ["classify_vol_regime", "compute_shadow_signals"]
