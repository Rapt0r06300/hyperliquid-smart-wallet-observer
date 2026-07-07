"""V10.7 paper strategies library (lots S1/S2/S3) — paper-only, deny-by-default.

Each strategy is PURE and deterministic: given already-observed real features it returns
a PaperIntent (a simulated action only) or None (no opportunity). Nothing here places an
order; intents must still pass approve_with_risk(). Meta strategies (kelly/ensemble/
shadow/rag) compose or annotate other intents. No fabricated data.
"""

from __future__ import annotations

from collections import Counter

from hl_observer.storage.run_context import RunContext
from hl_observer.strategies.models import (
    IntentAction,
    IntentSide,
    PaperIntent,
    StrategyKind,
    make_strategy,
)

SHADOW_REASON = "SHADOW_ONLY"


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _intent(strategy_id, coin, side, *, action=IntentAction.OPEN, confidence, reasons,
            context=RunContext.LIVE, now_ms=0, notional=0.0) -> PaperIntent:
    return PaperIntent(
        strategy_id=strategy_id, coin=str(coin).upper(), side=side, action=action,
        target_notional_usdt=float(notional), confidence=round(_clamp(confidence), 6),
        context=context, reasons=tuple(reasons), created_at_ms=int(now_ms),
    )


class _Base:
    kind: StrategyKind

    def __init__(self, definition):
        self.definition = definition

    @property
    def strategy_id(self) -> str:
        return self.definition.strategy_id

    def _p(self, key, default):
        return self.definition.params.get(key, default)


# ----------------------------- Lot 1 (#120) -----------------------------

class FadeImpulseStrategy(_Base):
    kind = StrategyKind.FADE_IMPULSE

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="fade_impulse", version=1, kind=cls.kind,
                                 name="Fade impulse", params={"min_impulse_bps": 40}))

    def propose(self, *, coin, impulse_bps, context=RunContext.LIVE, now_ms=0):
        thr = float(self._p("min_impulse_bps", 40))
        if abs(impulse_bps) < thr:
            return None
        side = IntentSide.SHORT if impulse_bps > 0 else IntentSide.LONG  # fade the move
        return _intent(self.strategy_id, coin, side, confidence=abs(impulse_bps) / 100.0,
                       reasons=(f"fade_impulse_bps={impulse_bps:.1f}",), context=context, now_ms=now_ms)


class FollowImpulseStrategy(_Base):
    kind = StrategyKind.FOLLOW_IMPULSE

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="follow_impulse", version=1, kind=cls.kind,
                                 name="Follow impulse", params={"min_impulse_bps": 40}))

    def propose(self, *, coin, impulse_bps, context=RunContext.LIVE, now_ms=0):
        thr = float(self._p("min_impulse_bps", 40))
        if abs(impulse_bps) < thr:
            return None
        side = IntentSide.LONG if impulse_bps > 0 else IntentSide.SHORT  # follow the move
        return _intent(self.strategy_id, coin, side, confidence=abs(impulse_bps) / 100.0,
                       reasons=(f"follow_impulse_bps={impulse_bps:.1f}",), context=context, now_ms=now_ms)


class WhaleFillEarlyStrategy(_Base):
    kind = StrategyKind.WHALE_ALERT

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="whale_fill_early", version=1, kind=cls.kind,
                                 name="Whale fill early",
                                 params={"min_whale_notional_usdc": 100000, "max_age_ms": 30000}))

    def propose(self, *, coin, leader_side, leader_notional_usdc, signal_age_ms,
                context=RunContext.LIVE, now_ms=0):
        if leader_side is IntentSide.FLAT:
            return None
        if leader_notional_usdc < float(self._p("min_whale_notional_usdc", 100000)):
            return None  # not a whale
        if signal_age_ms > int(self._p("max_age_ms", 30000)):
            return None  # stale
        return _intent(self.strategy_id, coin, leader_side,
                       confidence=_clamp(leader_notional_usdc / 1_000_000.0),
                       reasons=(f"whale_notional={leader_notional_usdc:.0f}",), context=context, now_ms=now_ms)


class DirectionMultiTfStrategy(_Base):
    kind = StrategyKind.DIRECTION_HUNT

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="direction_multi_tf", version=1, kind=cls.kind,
                                 name="Direction multi-TF"))

    def propose(self, *, coin, dir_5m, dir_15m, dir_1h, context=RunContext.LIVE, now_ms=0):
        if dir_5m is IntentSide.FLAT or not (dir_5m == dir_15m == dir_1h):
            return None  # need agreement across 5m/15m/1h
        return _intent(self.strategy_id, coin, dir_5m, confidence=0.9,
                       reasons=("multi_tf_agreement",), context=context, now_ms=now_ms)


# ----------------------------- Lot 2 (#121) -----------------------------

class MeanReversionStrategy(_Base):
    kind = StrategyKind.MEAN_REVERSION

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="mean_reversion", version=1, kind=cls.kind,
                                 name="Mean reversion", params={"min_deviation_bps": 30}))

    def propose(self, *, coin, deviation_bps, context=RunContext.LIVE, now_ms=0):
        thr = float(self._p("min_deviation_bps", 30))
        if abs(deviation_bps) < thr:
            return None
        side = IntentSide.SHORT if deviation_bps > 0 else IntentSide.LONG  # revert toward fair value
        return _intent(self.strategy_id, coin, side, confidence=abs(deviation_bps) / 100.0,
                       reasons=(f"deviation_bps={deviation_bps:.1f}",), context=context, now_ms=now_ms)


class MomentumStrategy(_Base):
    kind = StrategyKind.MOMENTUM

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="momentum", version=1, kind=cls.kind,
                                 name="Momentum", params={"min_return_bps": 20}))

    def propose(self, *, coin, return_bps, context=RunContext.LIVE, now_ms=0):
        thr = float(self._p("min_return_bps", 20))
        if abs(return_bps) < thr:
            return None
        side = IntentSide.LONG if return_bps > 0 else IntentSide.SHORT
        return _intent(self.strategy_id, coin, side, confidence=abs(return_bps) / 100.0,
                       reasons=(f"return_bps={return_bps:.1f}",), context=context, now_ms=now_ms)


class SpreadFarmStrategy(_Base):
    kind = StrategyKind.SPREAD_FARM

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="spread_farm", version=1, kind=cls.kind,
                                 name="Spread farming", params={"min_spread_bps": 8, "min_imbalance": 0.1}))

    def propose(self, *, coin, spread_bps, imbalance, context=RunContext.LIVE, now_ms=0):
        if spread_bps < float(self._p("min_spread_bps", 8)):
            return None  # not enough spread to farm
        if abs(imbalance) < float(self._p("min_imbalance", 0.1)):
            return None
        side = IntentSide.LONG if imbalance > 0 else IntentSide.SHORT
        return _intent(self.strategy_id, coin, side, confidence=abs(imbalance),
                       reasons=(f"spread_bps={spread_bps:.1f}", f"imbalance={imbalance:+.2f}"),
                       context=context, now_ms=now_ms)


class VolatilityBreakoutStrategy(_Base):
    kind = StrategyKind.VOLATILITY_BREAKOUT

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="volatility_breakout", version=1, kind=cls.kind,
                                 name="Volatility breakout", params={"min_breakout_bps": 50}))

    def propose(self, *, coin, breakout_bps, vol_expanding, context=RunContext.LIVE, now_ms=0):
        if not vol_expanding:
            return None
        if abs(breakout_bps) < float(self._p("min_breakout_bps", 50)):
            return None
        side = IntentSide.LONG if breakout_bps > 0 else IntentSide.SHORT
        return _intent(self.strategy_id, coin, side, confidence=abs(breakout_bps) / 150.0,
                       reasons=(f"breakout_bps={breakout_bps:.1f}",), context=context, now_ms=now_ms)


class LowVolScalpingStrategy(_Base):
    kind = StrategyKind.LOW_VOL_SCALPING

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="low_vol_scalping", version=1, kind=cls.kind,
                                 name="Low-vol scalping",
                                 params={"max_volatility_bps": 15, "max_spread_bps": 5, "min_imbalance": 0.12}))

    def propose(self, *, coin, volatility_bps, imbalance, spread_bps, context=RunContext.LIVE, now_ms=0):
        if volatility_bps > float(self._p("max_volatility_bps", 15)):
            return None
        if spread_bps > float(self._p("max_spread_bps", 5)):
            return None
        if abs(imbalance) < float(self._p("min_imbalance", 0.12)):
            return None
        side = IntentSide.LONG if imbalance > 0 else IntentSide.SHORT
        return _intent(self.strategy_id, coin, side, confidence=abs(imbalance),
                       reasons=(f"vol_bps={volatility_bps:.1f}", f"imbalance={imbalance:+.2f}"),
                       context=context, now_ms=now_ms)


# ----------------------------- Lot 3 (#122) -----------------------------

class CrossSourceDiscrepancyStrategy(_Base):
    kind = StrategyKind.CROSS_SOURCE_DISCREPANCY

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="cross_source_discrepancy", version=1, kind=cls.kind,
                                 name="Cross-source discrepancy",
                                 params={"min_dev_bps": 8, "max_dev_bps": 60}))

    def propose(self, *, coin, price_index, price_venue, context=RunContext.LIVE, now_ms=0):
        mid = (price_index + price_venue) / 2.0
        if mid <= 0:
            return None
        dev_bps = abs(price_index - price_venue) / mid * 10_000.0
        if dev_bps < float(self._p("min_dev_bps", 8)):
            return None  # too small
        if dev_bps > float(self._p("max_dev_bps", 60)):
            return None  # likely bad data, not an opportunity
        # venue below index -> expect venue to rise -> LONG
        side = IntentSide.LONG if price_venue < price_index else IntentSide.SHORT
        return _intent(self.strategy_id, coin, side, confidence=dev_bps / float(self._p("max_dev_bps", 60)),
                       reasons=(f"cross_source_dev_bps={dev_bps:.1f}",), context=context, now_ms=now_ms)


class DcaSimStrategy(_Base):
    kind = StrategyKind.DCA_SIM

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="dca_sim", version=1, kind=cls.kind,
                                 name="DCA simulation", params={"interval_ms": 3600000, "max_legs": 5}))

    def propose(self, *, coin, base_side, elapsed_since_last_ms, legs_done,
                context=RunContext.LIVE, now_ms=0):
        if base_side is IntentSide.FLAT:
            return None
        if legs_done >= int(self._p("max_legs", 5)):
            return None
        if elapsed_since_last_ms < int(self._p("interval_ms", 3600000)):
            return None
        return _intent(self.strategy_id, coin, base_side, action=IntentAction.ADD, confidence=0.5,
                       reasons=(f"dca_leg={legs_done + 1}",), context=context, now_ms=now_ms)


class KellySizingStrategy(_Base):
    """Meta: sizes a directional view via the Kelly criterion (capped)."""
    kind = StrategyKind.KELLY_SIZING

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="kelly_sizing", version=1, kind=cls.kind,
                                 name="Kelly sizing", params={"max_fraction": 0.1}))

    def propose(self, *, coin, side, win_prob, win_loss_ratio, equity_usdt,
                context=RunContext.LIVE, now_ms=0):
        if side is IntentSide.FLAT:
            return None
        b = max(1e-9, float(win_loss_ratio))
        p = _clamp(float(win_prob))
        f = p - (1.0 - p) / b  # Kelly fraction
        max_frac = float(self._p("max_fraction", 0.1))
        f = min(max(f, 0.0), max_frac)
        if f <= 0.0:
            return None  # no positive edge -> no size
        notional = round(float(equity_usdt) * f, 2)
        return _intent(self.strategy_id, coin, side, confidence=f / max_frac, notional=notional,
                       reasons=(f"kelly_fraction={f:.4f}",), context=context, now_ms=now_ms)


class StrategyEnsembleStrategy(_Base):
    """Meta: consensus over sub-strategy intents (majority side)."""
    kind = StrategyKind.STRATEGY_ENSEMBLE

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="strategy_ensemble", version=1, kind=cls.kind,
                                 name="Strategy ensemble", params={"min_agree": 2}))

    def propose(self, *, coin, intents, context=RunContext.LIVE, now_ms=0):
        non_flat = [i for i in (intents or []) if i is not None and i.side is not IntentSide.FLAT]
        if not non_flat:
            return None
        counts = Counter(i.side for i in non_flat)
        side, count = counts.most_common(1)[0]
        if count < int(self._p("min_agree", 2)):
            return None
        conf = sum(i.confidence for i in non_flat if i.side == side) / count
        return _intent(self.strategy_id, coin, side, confidence=conf,
                       reasons=(f"ensemble_agree={count}",), context=context, now_ms=now_ms)


class ShadowModelStrategy(_Base):
    """Meta: observe-only — proposes an intent flagged SHADOW_ONLY (never to be approved)."""
    kind = StrategyKind.SHADOW_MODEL

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="shadow_model", version=1, kind=cls.kind,
                                 name="Shadow model"))

    def propose(self, *, coin, side, confidence=0.5, context=RunContext.LIVE, now_ms=0):
        if side is IntentSide.FLAT:
            return None
        return _intent(self.strategy_id, coin, side, confidence=confidence,
                       reasons=(SHADOW_REASON,), context=context, now_ms=now_ms)


class RagEvidenceContextStrategy(_Base):
    """Meta: context-only. NEVER produces a tradeable intent; only attaches evidence refs."""
    kind = StrategyKind.RAG_EVIDENCE_CONTEXT

    @classmethod
    def default(cls):
        return cls(make_strategy(strategy_id="rag_evidence_context", version=1, kind=cls.kind,
                                 name="RAG evidence (context only)"))

    def propose(self, *args, **kwargs):
        return None  # context only — never trades

    def evidence(self, *, refs) -> tuple:
        return tuple(str(r) for r in (refs or ()))


def is_shadow(intent) -> bool:
    return bool(intent is not None and SHADOW_REASON in (intent.reasons or ()))


_ALL_CLASSES = [
    FadeImpulseStrategy, FollowImpulseStrategy, WhaleFillEarlyStrategy, DirectionMultiTfStrategy,
    MeanReversionStrategy, MomentumStrategy, SpreadFarmStrategy, VolatilityBreakoutStrategy,
    LowVolScalpingStrategy, CrossSourceDiscrepancyStrategy, DcaSimStrategy, KellySizingStrategy,
    StrategyEnsembleStrategy, ShadowModelStrategy, RagEvidenceContextStrategy,
]


def all_default_strategies() -> list:
    return [cls.default() for cls in _ALL_CLASSES]


def register_all(registry) -> int:
    n = 0
    for strat in all_default_strategies():
        registry.register(strat.definition)
        n += 1
    return n


__all__ = [
    "FadeImpulseStrategy", "FollowImpulseStrategy", "WhaleFillEarlyStrategy", "DirectionMultiTfStrategy",
    "MeanReversionStrategy", "MomentumStrategy", "SpreadFarmStrategy", "VolatilityBreakoutStrategy",
    "LowVolScalpingStrategy", "CrossSourceDiscrepancyStrategy", "DcaSimStrategy", "KellySizingStrategy",
    "StrategyEnsembleStrategy", "ShadowModelStrategy", "RagEvidenceContextStrategy",
    "SHADOW_REASON", "is_shadow", "all_default_strategies", "register_all",
]
