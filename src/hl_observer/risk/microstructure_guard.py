"""Runtime microstructure guard for local paper entries.

This module combines the existing V9/V14 primitives:

* top-of-book and top-3 depth checks;
* spread tier checks;
* order book imbalance (OBI) conflict checks;
* historical VaR/CVaR over recent paper returns;
* confidence calibration diagnostics.

It is deliberately pure. It never creates an order, never calls a network
endpoint and never invents a book. Missing data is reported as evidence; only
measurable bad conditions veto a local paper entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from hl_observer.calibration.confidence_buckets import bucketize, calibration_error
from hl_observer.features.orderbook_imbalance import OrderBookImbalance, compute_obi
from hl_observer.risk.var_cvar import RiskMetrics, compute_risk_metrics

# NOTE: `depth_spread_gate` is imported lazily inside the guard function below.
# Importing it at module top creates a circular import:
#   risk/__init__ -> risk.microstructure_guard -> signals.depth_spread_gate
#   -> signals package init -> (back into risk). The lazy import breaks the cycle
#   without changing behaviour.

Levels = tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class MicrostructureGuardConfig:
    min_top1_usd: float = 20.0
    min_top3_usd: float = 60.0
    min_book_depth_usd: float = 200.0
    max_consume_fraction: float = 0.25
    max_spread_bps: float = 80.0
    obi_conflict_strength: float = 0.35
    min_calibration_samples: int = 20
    max_calibration_error: float = 0.30
    max_var_fraction: float = 0.015
    max_cvar_fraction: float = 0.025
    var_confidence: float = 0.95


@dataclass(frozen=True, slots=True)
class MicrostructureGuardDecision:
    ok: bool
    reasons: tuple[str, ...]
    side: str
    spread_bps: float | None
    top1_usd: float | None
    top3_usd: float | None
    bid_depth_usd: float | None
    ask_depth_usd: float | None
    obi_signal: str
    obi_strength: float
    obi_imbalance: float | None
    var_fraction: float | None
    cvar_fraction: float | None
    risk_samples: int
    risk_regime: str
    calibration_error: float | None
    calibration_samples: int
    authoritative_reasons: tuple[str, ...]

    @property
    def authoritative_ok(self) -> bool:
        return len(self.authoritative_reasons) == 0

    def to_log_fields(self, *, prefix: str = "microstructure") -> dict[str, Any]:
        return {
            f"{prefix}_checked": True,
            f"{prefix}_ok": self.ok,
            f"{prefix}_authoritative_ok": self.authoritative_ok,
            f"{prefix}_reason": "|".join(self.reasons),
            f"{prefix}_authoritative_reason": "|".join(self.authoritative_reasons),
            f"{prefix}_side": self.side,
            f"{prefix}_spread_bps": _round_or_none(self.spread_bps),
            f"{prefix}_top1_usd": _round_or_none(self.top1_usd),
            f"{prefix}_top3_usd": _round_or_none(self.top3_usd),
            f"{prefix}_bid_depth_usd": _round_or_none(self.bid_depth_usd),
            f"{prefix}_ask_depth_usd": _round_or_none(self.ask_depth_usd),
            f"{prefix}_obi_signal": self.obi_signal,
            f"{prefix}_obi_strength": round(self.obi_strength, 6),
            f"{prefix}_obi_imbalance": _round_or_none(self.obi_imbalance),
            f"{prefix}_var_fraction": _round_or_none(self.var_fraction),
            f"{prefix}_cvar_fraction": _round_or_none(self.cvar_fraction),
            f"{prefix}_risk_samples": self.risk_samples,
            f"{prefix}_risk_regime": self.risk_regime,
            f"{prefix}_calibration_error": _round_or_none(self.calibration_error),
            f"{prefix}_calibration_samples": self.calibration_samples,
        }


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _clean_levels(levels: Iterable[tuple[float, float]] | None) -> Levels:
    clean: list[tuple[float, float]] = []
    for item in levels or ():
        try:
            px = float(item[0])
            sz = float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if px > 0 and sz > 0:
            clean.append((px, sz))
    return tuple(clean)


def _depth_usd(levels: Levels, limit: int | None = None) -> float:
    rows = levels if limit is None else levels[:limit]
    return sum(px * sz for px, sz in rows)


def _spread_bps_from_levels(bids: Levels, asks: Levels) -> float | None:
    if not bids or not asks:
        return None
    bid = bids[0][0]
    ask = asks[0][0]
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return max(0.0, (ask - bid) / mid * 10_000.0)


def _side_to_book_side(side: str) -> str:
    normalized = str(side or "").upper()
    if normalized in {"LONG", "BUY", "OPEN_LONG"}:
        return "ASK"
    if normalized in {"SHORT", "SELL", "OPEN_SHORT"}:
        return "BID"
    return "UNKNOWN"


def side_conflicts_with_obi(
    side: str,
    obi_signal: str,
    strength: float,
    threshold: float,
) -> bool:
    if strength < threshold:
        return False
    normalized_side = str(side or "").upper()
    signal = str(obi_signal or "").upper()
    if normalized_side in {"LONG", "BUY", "OPEN_LONG"}:
        return signal == "SHORT_BIAS"
    if normalized_side in {"SHORT", "SELL", "OPEN_SHORT"}:
        return signal == "LONG_BIAS"
    return False


def _risk_reasons(metrics: RiskMetrics, config: MicrostructureGuardConfig) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    authoritative: list[str] = []
    if metrics.var is not None and metrics.var > config.max_var_fraction:
        reasons.append("VAR_TOO_HIGH")
        authoritative.append("VAR_TOO_HIGH")
    if metrics.cvar is not None and metrics.cvar > config.max_cvar_fraction:
        reasons.append("CVAR_TOO_HIGH")
        authoritative.append("CVAR_TOO_HIGH")
    if metrics.samples < 2:
        reasons.append("RISK_SAMPLE_INSUFFICIENT")
    return reasons, authoritative


def _calibration_reasons(
    confidence_samples: list[tuple[float, float | bool | int]],
    config: MicrostructureGuardConfig,
) -> tuple[float | None, int, list[str], list[str]]:
    sample_count = len(confidence_samples)
    if sample_count < config.min_calibration_samples:
        return None, sample_count, ["CALIBRATION_SAMPLE_INSUFFICIENT"], []
    err = calibration_error(bucketize(confidence_samples))
    if err is None:
        return None, sample_count, ["CALIBRATION_UNAVAILABLE"], []
    if err > config.max_calibration_error:
        return err, sample_count, ["CALIBRATION_ERROR_TOO_HIGH"], ["CALIBRATION_ERROR_TOO_HIGH"]
    return err, sample_count, [], []


def evaluate_microstructure_guard(
    *,
    side: str,
    needed_usd: float,
    asks: Iterable[tuple[float, float]] | None = None,
    bids: Iterable[tuple[float, float]] | None = None,
    spread_bps: float | None = None,
    recent_returns: Iterable[float] | None = None,
    confidence_samples: Iterable[tuple[float, float | bool | int]] | None = None,
    sigma_bps: float | None = None,
    config: MicrostructureGuardConfig | None = None,
) -> MicrostructureGuardDecision:
    # Lazy import to avoid the risk<->signals circular import at module load.
    from hl_observer.signals.depth_spread_gate import DepthSpreadConfig, depth_spread_gate

    cfg = config or MicrostructureGuardConfig()
    clean_asks = _clean_levels(asks)
    clean_bids = _clean_levels(bids)
    reasons: list[str] = []
    authoritative: list[str] = []

    if not clean_asks or not clean_bids:
        reasons.append("BOOK_MISSING")
        risk_metrics = compute_risk_metrics(list(recent_returns or ()), confidence=cfg.var_confidence, sigma_bps=sigma_bps)
        risk_reasons, risk_authoritative = _risk_reasons(risk_metrics, cfg)
        reasons.extend(risk_reasons)
        authoritative.extend(risk_authoritative)
        cal_err, cal_n, cal_reasons, cal_authoritative = _calibration_reasons(list(confidence_samples or ()), cfg)
        reasons.extend(cal_reasons)
        authoritative.extend(cal_authoritative)
        return MicrostructureGuardDecision(
            ok=not authoritative,
            reasons=tuple(dict.fromkeys(reasons)),
            side=str(side or "").upper(),
            spread_bps=None,
            top1_usd=None,
            top3_usd=None,
            bid_depth_usd=None,
            ask_depth_usd=None,
            obi_signal="NEUTRAL",
            obi_strength=0.0,
            obi_imbalance=None,
            var_fraction=risk_metrics.var,
            cvar_fraction=risk_metrics.cvar,
            risk_samples=risk_metrics.samples,
            risk_regime=risk_metrics.regime,
            calibration_error=cal_err,
            calibration_samples=cal_n,
            authoritative_reasons=tuple(dict.fromkeys(authoritative)),
        )

    side_book = _side_to_book_side(side)
    target_levels = clean_asks if side_book == "ASK" else clean_bids
    top1_usd = _depth_usd(target_levels, 1)
    top3_usd = _depth_usd(target_levels, 3)
    bid_depth_usd = _depth_usd(clean_bids)
    ask_depth_usd = _depth_usd(clean_asks)
    effective_spread = spread_bps if spread_bps is not None else _spread_bps_from_levels(clean_bids, clean_asks)

    depth_cfg = DepthSpreadConfig(
        min_top1_usd=cfg.min_top1_usd,
        min_top3_usd=cfg.min_top3_usd,
        min_book_depth_usd=cfg.min_book_depth_usd,
        max_consume_fraction=cfg.max_consume_fraction,
        degraded_spread_bps=cfg.max_spread_bps,
        bad_spread_bps=cfg.max_spread_bps,
    )
    gate = depth_spread_gate(
        top1_usd=top1_usd,
        top3_usd=top3_usd,
        bid_depth_usd=bid_depth_usd,
        ask_depth_usd=ask_depth_usd,
        side=side,
        needed_usd=needed_usd,
        config=depth_cfg,
        spread_bps=effective_spread or 0.0,
    )
    if not gate.ok and gate.reason:
        reasons.append(gate.reason)
        authoritative.append(gate.reason)
    if effective_spread is not None and effective_spread > cfg.max_spread_bps:
        reasons.append("SPREAD_TOO_WIDE")
        authoritative.append("SPREAD_TOO_WIDE")

    obi: OrderBookImbalance = compute_obi(clean_bids, clean_asks, threshold=cfg.obi_conflict_strength)
    if side_conflicts_with_obi(side, obi.signal, obi.strength, cfg.obi_conflict_strength):
        reasons.append("OBI_CONFLICTS_WITH_SIDE")
        authoritative.append("OBI_CONFLICTS_WITH_SIDE")

    risk_metrics = compute_risk_metrics(list(recent_returns or ()), confidence=cfg.var_confidence, sigma_bps=sigma_bps)
    risk_reasons, risk_authoritative = _risk_reasons(risk_metrics, cfg)
    reasons.extend(risk_reasons)
    authoritative.extend(risk_authoritative)

    cal_err, cal_n, cal_reasons, cal_authoritative = _calibration_reasons(list(confidence_samples or ()), cfg)
    reasons.extend(cal_reasons)
    authoritative.extend(cal_authoritative)

    unique_reasons = tuple(dict.fromkeys(reasons))
    unique_authoritative = tuple(dict.fromkeys(authoritative))
    return MicrostructureGuardDecision(
        ok=len(unique_authoritative) == 0,
        reasons=unique_reasons,
        side=str(side or "").upper(),
        spread_bps=effective_spread,
        top1_usd=top1_usd,
        top3_usd=top3_usd,
        bid_depth_usd=bid_depth_usd,
        ask_depth_usd=ask_depth_usd,
        obi_signal=obi.signal,
        obi_strength=obi.strength,
        obi_imbalance=obi.imbalance,
        var_fraction=risk_metrics.var,
        cvar_fraction=risk_metrics.cvar,
        risk_samples=risk_metrics.samples,
        risk_regime=risk_metrics.regime,
        calibration_error=cal_err,
        calibration_samples=cal_n,
        authoritative_reasons=unique_authoritative,
    )


__all__ = [
    "MicrostructureGuardConfig",
    "MicrostructureGuardDecision",
    "evaluate_microstructure_guard",
    "side_conflicts_with_obi",
]
