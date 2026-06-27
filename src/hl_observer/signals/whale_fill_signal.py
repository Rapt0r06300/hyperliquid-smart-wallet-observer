"""V9 / S6 §2.1 — Signal PRIMAIRE "whale fill" (inspiré Harrier A1).

Traite un fill FRAIS et significatif d'un leader comme le signal de copie le plus
rapide : un gros OPEN/ADD récent d'un wallet de qualité est l'évènement à copier en
priorité. Ce module ne fait que QUALIFIER et NOTER le signal (0..1) ; il ne décide pas
l'entrée (c'est le scorer/risk qui gardent la décision finale). read-only / paper-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import log10


ENTRY_ACTIONS = {"OPEN_LONG", "OPEN_SHORT", "ADD", "INCREASE"}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True, slots=True)
class WhaleFillConfig:
    max_age_ms: int = 30_000
    min_notional_usdc: float = 2_000.0      # plancher "whale"
    strong_notional_usdc: float = 50_000.0  # au-delà = signal fort
    min_leader_score: float = 60.0          # qualité minimale du leader
    read_only: bool = True
    execution: str = "forbidden"


@dataclass(frozen=True, slots=True)
class WhaleFillSignal:
    coin: str
    side: str
    action_type: str
    notional_usdc: float
    age_ms: int
    is_primary: bool
    strength: float                 # 0..1
    reasons: tuple[str, ...] = field(default_factory=tuple)
    read_only: bool = True
    execution: str = "forbidden"


def build_whale_fill_signal(
    *,
    action_type: str,
    coin: str,
    side: str,
    leader_notional_usdc: float,
    fill_age_ms: int,
    leader_score: float,
    consensus_wallets: int = 1,
    config: WhaleFillConfig | None = None,
) -> WhaleFillSignal | None:
    """Qualifie un fill frais en signal whale primaire, ou None s'il ne l'est pas.

    None = ce n'est pas un signal d'entrée whale (sortie, périmé, trop petit).
    """
    cfg = config or WhaleFillConfig()
    action = str(action_type or "").upper()
    notional = max(0.0, float(leader_notional_usdc or 0.0))
    age = max(0, int(fill_age_ms))

    if action not in ENTRY_ACTIONS:
        return None                      # un signal primaire = une ENTRÉE
    if age > max(0, int(cfg.max_age_ms)):
        return None                      # pas frais
    if notional < cfg.min_notional_usdc:
        return None                      # pas une "whale"

    # facteur taille : log entre min et strong (0..1)
    lo, hi = log10(cfg.min_notional_usdc), log10(max(cfg.strong_notional_usdc, cfg.min_notional_usdc * 1.0001))
    notional_factor = _clamp((log10(max(notional, 1.0)) - lo) / max(hi - lo, 1e-9))
    score_factor = _clamp(float(leader_score or 0.0) / 100.0)
    fresh_factor = _clamp(1.0 - age / max(1, int(cfg.max_age_ms)))
    consensus_boost = _clamp(1.0 + 0.08 * max(0, int(consensus_wallets) - 1), 1.0, 1.25)

    strength = _clamp((0.50 * notional_factor + 0.30 * score_factor + 0.20 * fresh_factor) * consensus_boost)

    reasons: list[str] = []
    if notional >= cfg.strong_notional_usdc:
        reasons.append("LARGE_NOTIONAL")
    if float(leader_score or 0.0) >= cfg.min_leader_score:
        reasons.append("QUALITY_LEADER")
    if consensus_wallets >= 2:
        reasons.append("CONSENSUS")
    if fresh_factor >= 0.5:
        reasons.append("FRESH")

    is_primary = (
        notional >= cfg.strong_notional_usdc
        or (float(leader_score or 0.0) >= cfg.min_leader_score and fresh_factor >= 0.5)
    )
    if is_primary:
        reasons.append("PRIMARY")

    return WhaleFillSignal(
        coin=str(coin or "").upper(),
        side=str(side or "").upper(),
        action_type=action,
        notional_usdc=round(notional, 2),
        age_ms=age,
        is_primary=is_primary,
        strength=round(strength, 6),
        reasons=tuple(reasons),
    )


__all__ = ["ENTRY_ACTIONS", "WhaleFillConfig", "WhaleFillSignal", "build_whale_fill_signal"]
