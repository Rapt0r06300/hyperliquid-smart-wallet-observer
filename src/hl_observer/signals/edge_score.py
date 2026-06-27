"""V15 #186 — Composite EDGE-SCORE 0-100 (veto-first + weighted points + penalties).

Transposed from mlmodelpoly's edge_engine: a transparent entry scorer that FIRST applies a
unified veto pipeline (bad data / not warm / gap / stale / thin depth / bad spread / no price),
then awards weighted points and subtracts penalties. Action when score >= threshold. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True, slots=True)
class EdgeScoreInput:
    # vetoes
    quality_ok: bool = True
    warmup_ready: bool = True
    gap_detected: bool = False
    stale: bool = False
    depth_ok: bool = True
    spread_tier: str = "OK"        # OK | DEGRADED | BAD
    has_price: bool = True
    # points
    bias_ok: bool = False
    regime: str = "normal"          # trend | range | normal | ...
    aligned: bool = False
    mispricing_bps: float = 0.0     # |deviation| vs AVWAP
    rvol_spike: bool = False
    impulse: bool = False
    absorption: bool = False
    basis_bps: float = 0.0
    basis_supports: bool = True     # basis aligned with the side
    # penalties
    rsi_overheated: bool = False
    depth_degraded: bool = False


@dataclass(frozen=True, slots=True)
class EdgeScore:
    score: float                    # 0..100
    action: bool                    # score >= threshold and not vetoed
    vetoed: bool
    veto_reason: str | None
    components: dict = field(default_factory=dict)


def compute_edge_score(inp: EdgeScoreInput, *, action_threshold: float = 60.0) -> EdgeScore:
    # --- veto-first pipeline ---
    veto: str | None = None
    if not inp.quality_ok:
        veto = "QUALITY_NOT_OK"
    elif not inp.warmup_ready:
        veto = "WARMUP_NOT_READY"
    elif inp.gap_detected:
        veto = "DATA_GAP"
    elif inp.stale:
        veto = "STALE"
    elif not inp.has_price:
        veto = "NO_PRICE"
    elif not inp.depth_ok:
        veto = "DEPTH_TOO_LOW"
    elif str(inp.spread_tier).upper() == "BAD":
        veto = "SPREAD_BAD"
    if veto is not None:
        return EdgeScore(0.0, False, True, veto, {"veto": veto})

    comp: dict[str, float] = {}
    score = 0.0
    if inp.bias_ok:
        comp["bias"] = 25.0; score += 25.0
    if str(inp.regime).lower() == "trend":
        comp["regime_trend"] = 15.0; score += 15.0
    if inp.aligned:
        comp["alignment"] = 10.0; score += 10.0
    mis = _clamp(abs(float(inp.mispricing_bps)) / 2.0, 0.0, 25.0)  # ~2bps per point, cap 25
    if mis > 0:
        comp["mispricing"] = round(mis, 3); score += mis
    if inp.rvol_spike:
        comp["rvol"] = 10.0; score += 10.0
    if inp.impulse:
        comp["impulse"] = 10.0; score += 10.0
    if inp.absorption:
        comp["absorption"] = 10.0; score += 10.0
    if inp.basis_supports and abs(float(inp.basis_bps)) > 0:
        comp["basis"] = 5.0; score += 5.0

    # --- penalties ---
    if inp.rsi_overheated:
        comp["rsi_penalty"] = -15.0; score -= 15.0
    if inp.depth_degraded:
        comp["depth_penalty"] = -10.0; score -= 10.0
    if not inp.basis_supports:
        comp["basis_penalty"] = -10.0; score -= 10.0

    score = _clamp(score, 0.0, 100.0)
    return EdgeScore(round(score, 3), score >= action_threshold, False, None, comp)


__all__ = ["EdgeScoreInput", "EdgeScore", "compute_edge_score"]
