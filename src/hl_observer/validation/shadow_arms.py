"""GAP VALID — Bras shadow permanents: des configs candidates évaluées en continu.

Au lieu d'un A/B ponctuel, 2-3 configs candidates tournent en shadow sur le MÊME
flux que la config active. On accumule leur PnL et on propose une promotion quand
une candidate bat l'active de façon stable (marge + persistance). Pur, déterministe.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ShadowArm:
    name: str
    pnls: list[float] = field(default_factory=list)

    def record(self, pnl: float) -> None:
        self.pnls.append(float(pnl))

    def total(self) -> float:
        return round(sum(self.pnls), 6)

    def n(self) -> int:
        return len(self.pnls)


class ShadowArmRegistry:
    def __init__(self, active_name: str = "active") -> None:
        self.active = ShadowArm(active_name)
        self.candidates: dict[str, ShadowArm] = {}

    def add_candidate(self, name: str) -> None:
        self.candidates.setdefault(name, ShadowArm(name))

    def record(self, arm_pnls: dict[str, float]) -> None:
        """Un tick: PnL de l'active + de chaque candidate sur le même événement."""
        for name, pnl in (arm_pnls or {}).items():
            if name == self.active.name:
                self.active.record(pnl)
            elif name in self.candidates:
                self.candidates[name].record(pnl)

    def promotion_suggestion(self, *, min_ticks: int = 50, min_margin_usdc: float = 1.0) -> dict:
        """Suggère une promotion si une candidate bat l'active durablement."""
        best = None
        for cand in self.candidates.values():
            if cand.n() < min_ticks:
                continue
            margin = cand.total() - self.active.total()
            if margin >= min_margin_usdc and (best is None or margin > best[1]):
                best = (cand.name, margin)
        if best is None:
            return {"suggest_promotion": False, "reason": "NO_CANDIDATE_BEATS_ACTIVE_STABLY",
                    "active_total": self.active.total()}
        return {"suggest_promotion": True, "candidate": best[0],
                "margin_usdc": round(best[1], 6), "active_total": self.active.total(),
                "note": "suggestion seulement; promotion réelle passe par replay A/B (règle produit)"}


__all__ = ["ShadowArm", "ShadowArmRegistry"]
