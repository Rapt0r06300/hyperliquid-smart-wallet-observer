from __future__ import annotations

import random
import time
from typing import Any

try:
    import hyper_smart_observer.dydx_v4.fast_scan_whale_patch  # noqa: F401
except Exception:
    pass

try:
    import hyper_smart_observer.dydx_v4.leaderboard_import_patch  # noqa: F401
except Exception:
    pass

try:
    import hyper_smart_observer.dydx_v4.cluster_whale_weight_patch  # noqa: F401
except Exception:
    pass


def correlated_count_reason(observer: Any, market: str, side: str) -> str | None:
    if not getattr(observer.config, "correlation_gate_enabled", True):
        return None
    from hyper_smart_observer.dydx_v4.market_regime import correlation_group

    group = correlation_group(market)
    count = 0
    notional = 0.0
    for pos in observer._open_positions.values():
        if str(pos.side).upper() != str(side).upper():
            continue
        if correlation_group(pos.market_id) != group:
            continue
        count += 1
        notional += abs(float(pos.size or 0.0))
    max_count = int(getattr(observer.config, "max_correlated_same_side", 5) or 5)
    if count >= max_count:
        return f"CORRELATED_COUNT group={group} side={side} count={count}>={max_count} notional={notional:.2f}"
    max_notional = float(getattr(observer.config, "max_correlated_exposure_usdc", 0.0) or 0.0)
    if max_notional > 0 and notional >= max_notional:
        return f"CORRELATED_NOTIONAL group={group} side={side} notional={notional:.2f}>={max_notional:.2f} count={count}"
    return None


def neutral_demo_price(existing: float, base: float, seed_seconds: int | None = None) -> float:
    """DÉMO RETIRÉE (2026-06-21, demande utilisateur): plus aucun prix fabriqué.

    Cette fonction générait auparavant un prix factice (bruit aléatoire) pour le
    mode démo. Conformément à la règle "aucune donnée fabriquée / aucun faux PnL",
    elle ne synthétise plus rien et renvoie simplement le prix RÉEL fourni
    (`existing`, sinon `base`). Signature conservée pour ne casser aucun appelant.
    """
    return round(float(existing or base or 0.0), 4)


def next_pyramid_index(open_positions: dict, market: str, side: str) -> int:
    prefix = f"{market}:{side}:add"
    used: set[int] = set()
    for key in open_positions:
        text = str(key)
        if text.startswith(prefix):
            try:
                used.add(int(text[len(prefix):]))
            except ValueError:
                continue
    idx = 1
    while idx in used:
        idx += 1
    return idx


def _decision_v2(observer: Any, cluster: Any):
    from hyper_smart_observer.dydx_v4.decision_intelligence_v2 import (
        BudgetState,
        DecisionIntelligenceConfig,
        SessionHealth,
        decision_intelligence_v2,
    )
    from hyper_smart_observer.dydx_v4.tremor_engine import TremorObservation
    from hyper_smart_observer.dydx_v4.tuned_decision import TunedDecisionContext

    market = str(getattr(cluster, "market_id", "") or "")
    side = str(getattr(cluster, "side", "LONG") or "LONG").upper()
    wallet_count = int(getattr(cluster, "wallet_count", 0) or 0)
    strength = float(getattr(cluster, "signal_strength", 0.0) or 0.0)
    same_market = [p for p in observer._open_positions.values() if getattr(p, "market_id", "") == market]
    try:
        market_ctx = observer._market_context(market)
        regime = str(getattr(market_ctx, "regime", "UNKNOWN") or "UNKNOWN")
        confidence = float(getattr(market_ctx, "confidence", 0.0) or 0.0)
        volume_z = float(getattr(market_ctx, "volume_zscore", 0.0) or 0.0)
    except Exception:
        regime = "UNKNOWN"
        confidence = 0.0
        volume_z = 0.0
    obs = TremorObservation(
        market_id=market,
        direction=side,
        volume_zscore=volume_z,
        flow_imbalance=strength,
        flow_volume_usdc=float(getattr(cluster, "total_notional_usdc", 0.0) or 0.0),
        flow_trade_count=int(getattr(cluster, "flow_trade_count", 0) or 0),
        large_trade_usdc=float(getattr(cluster, "flow_large_trade_usdc", 0.0) or 0.0),
        leading_wallets=wallet_count,
        consensus_wallets=wallet_count,
        signal_age_ms=int(getattr(cluster, "signal_age_ms", 0) or 0),
        edge_remaining_bps=float(getattr(observer.config, "min_edge_bps", 3.0) or 3.0) + strength * 10.0,
        market_regime=regime,
        market_confidence=confidence,
        flow_direction=side,
        source=str(getattr(cluster, "origin", "rest") or "rest"),
    )
    ctx = TunedDecisionContext(
        spread_bps=float(getattr(observer.config, "estimated_spread_bps", 3.0) or 3.0),
        slippage_bps=float(getattr(observer.config, "estimated_slippage_bps", 1.5) or 1.5),
        open_positions=len(observer._open_positions),
        market_exposure_usdc=sum(abs(float(getattr(p, "size", 0.0) or 0.0)) for p in same_market),
        base_notional_usdc=float(getattr(observer.config, "paper_notional_base_usdc", 75.0) or 75.0),
        max_notional_usdc=float(getattr(observer.config, "paper_notional_max_usdc", 100.0) or 100.0),
    )
    return decision_intelligence_v2(
        obs,
        health=SessionHealth(
            closed_trades=int(getattr(observer.stats, "positions_closed", 0) or 0),
            winrate=float(getattr(observer.stats, "winrate", 0.0) or 0.0),
            open_positions=len(observer._open_positions),
        ),
        budget_state=BudgetState(same_market_open_positions=len(same_market)),
        ctx=ctx,
        config=DecisionIntelligenceConfig(),
    )


def _install_class_pyramid_guard() -> None:
    try:
        from hyper_smart_observer.dydx_v4.live_observer import DydxLiveObserver
        from hyper_smart_observer.dydx_v4.notional_bridge import install_notional_bridge, set_next_notional
    except Exception:
        return
    if getattr(DydxLiveObserver, "_pyramid_guard_installed", False):
        return
    install_notional_bridge(DydxLiveObserver)
    original = DydxLiveObserver._evaluate_cluster

    def _hard_decision_v2_reasons(result: Any) -> list[str]:
        reasons = [str(r) for r in getattr(result, "reasons", []) or []]
        hard_markers = (
            "HARD_",
            "DAILY_LOSS",
            "CONSECUTIVE_LOSS",
            "CIRCUIT",
            "KILL",
            "MAX_OPEN",
            "DRAWDOWN",
            "PRIVATE",
            "ORDER",
        )
        return [r for r in reasons if any(marker in r.upper() for marker in hard_markers)]

    def guarded(self, cluster):
        market = str(getattr(cluster, "market_id", "") or "")
        side = str(getattr(cluster, "side", "") or "")
        signal_age_ms = int(getattr(cluster, "signal_age_ms", 0) or 0)
        max_signal_age_ms = int(getattr(self, "max_signal_age_ms", 0) or 0)
        is_fresh = bool(getattr(cluster, "is_fresh", True))
        if max_signal_age_ms > 0 and (signal_age_ms > max_signal_age_ms or not is_fresh):
            stats = getattr(self, "stats", None)
            if stats is not None:
                stats.stale_signals_refused = getattr(stats, "stale_signals_refused", 0) + 1
            refuse = getattr(self, "_refuse", None)
            if callable(refuse):
                refuse(f"STALE_SIGNAL age={signal_age_ms}ms fresh={is_fresh}")
            return None
        base_key = f"{market}:{side}"
        existing = getattr(self, "_open_positions", {}).get(base_key)
        if existing is not None:
            setattr(existing, "_pyramid_count", next_pyramid_index(self._open_positions, market, side) - 1)
        try:
            result = _decision_v2(self, cluster)
            record = getattr(self, "_record_decision", None)
            if callable(record):
                record("DECISION_V2", result.to_dict())
            if not result.can_open:
                hard_reasons = _hard_decision_v2_reasons(result)
                if hard_reasons:
                    refuse = getattr(self, "_refuse", None)
                    if callable(refuse):
                        refuse(f"DECISION_V2_{result.action.value} hard={','.join(hard_reasons)}")
                    return None
                # Decision V2 is advisory when it has insufficient sample/profile
                # data. The original deterministic gates still validate freshness,
                # liquidity, spread, edge, exposure and paper-only safety.
                return original(self, cluster)
            set_next_notional(self, getattr(result, "notional_usdc", 0.0))
        except Exception:
            pass
        return original(self, cluster)

    DydxLiveObserver._evaluate_cluster = guarded
    DydxLiveObserver._pyramid_guard_installed = True


_install_class_pyramid_guard()


__all__ = ["correlated_count_reason", "neutral_demo_price", "next_pyramid_index"]
