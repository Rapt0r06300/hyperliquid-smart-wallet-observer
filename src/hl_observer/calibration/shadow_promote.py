"""Shadow -> primary promotion gate (S7 — V9, PolyWeather A4).

A shadow model is trained/scored offline and *never acts*. It is promoted to
primary only when it has enough samples and a real Brier advantage over the
current primary. The acting flag is hard-wired to False for the shadow.

SAFETY: the shadow has no path to action; promotion only swaps which model's
*paper* probabilities are read.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelScore:
    name: str
    brier: float | None
    samples: int
    acting: bool = False


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    ready_for_promotion: bool
    reasons: tuple[str, ...]
    shadow_acts: bool = False  # invariant: a shadow never acts


def shadow_never_acts(shadow: ModelScore) -> bool:
    """Invariant guard: a shadow model must never be in an acting state."""
    return shadow.acting is False


def ready_for_promotion(
    shadow: ModelScore,
    primary: ModelScore,
    *,
    min_samples: int = 200,
    min_advantage: float = 0.01,
) -> PromotionDecision:
    reasons: list[str] = []

    if not shadow_never_acts(shadow):
        # Defensive: refuse to promote anything that claims to be acting.
        return PromotionDecision(False, ("SHADOW_CLAIMS_ACTING_REFUSED",), shadow_acts=False)

    if shadow.samples < min_samples:
        reasons.append(f"INSUFFICIENT_SAMPLES_{shadow.samples}<{min_samples}")
    if shadow.brier is None or primary.brier is None:
        reasons.append("MISSING_BRIER")
        return PromotionDecision(False, tuple(reasons), shadow_acts=False)

    advantage = primary.brier - shadow.brier  # positive => shadow better
    if advantage < min_advantage:
        reasons.append(f"ADVANTAGE_{advantage:.4f}<{min_advantage}")

    ready = not reasons
    if ready:
        reasons.append(f"PROMOTE_advantage={advantage:.4f}")
    return PromotionDecision(ready_for_promotion=ready, reasons=tuple(reasons), shadow_acts=False)
