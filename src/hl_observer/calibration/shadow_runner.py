"""V9 / S7 — Runner stateful shadow -> primary (opère les primitives existantes).

Accumule des prédictions APPARIÉES (primary vs shadow) sur le même résultat observé,
calcule leurs scores de Brier, et expose la décision de promotion via le gate existant
`calibration.shadow_promote.ready_for_promotion`.

INVARIANT DE SÉCURITÉ : le modèle shadow n'AGIT JAMAIS. Il ne fait qu'observer en parallèle.
La "promotion" ne change que QUELLE probabilité paper est lue — jamais une action réelle.
read-only / paper-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.calibration.brier import brier_score
from hl_observer.calibration.shadow_promote import (
    ModelScore,
    PromotionDecision,
    ready_for_promotion,
)


@dataclass(slots=True)
class ShadowCalibrationRunner:
    primary_name: str = "primary"
    shadow_name: str = "shadow"
    min_samples: int = 200
    min_advantage: float = 0.01
    _primary: list[tuple[float, float]] = field(default_factory=list)
    _shadow: list[tuple[float, float]] = field(default_factory=list)
    # Invariant : reste False pour toujours. Le shadow ne déclenche aucune action.
    shadow_has_acted: bool = False

    def observe(self, *, primary_prob: float, shadow_prob: float, outcome: float | bool | int) -> None:
        """Enregistre une paire de prédictions et le résultat réel observé (0/1)."""
        self._primary.append((float(primary_prob), outcome))
        self._shadow.append((float(shadow_prob), outcome))

    @property
    def samples(self) -> int:
        return len(self._shadow)

    def scores(self) -> tuple[ModelScore, ModelScore]:
        primary = ModelScore(
            name=self.primary_name,
            brier=brier_score(self._primary),
            samples=len(self._primary),
            acting=True,
        )
        shadow = ModelScore(
            name=self.shadow_name,
            brier=brier_score(self._shadow),
            samples=len(self._shadow),
            acting=False,  # invariant : un shadow n'agit jamais
        )
        return primary, shadow

    def decision(self) -> PromotionDecision:
        primary, shadow = self.scores()
        return ready_for_promotion(
            shadow,
            primary,
            min_samples=self.min_samples,
            min_advantage=self.min_advantage,
        )


__all__ = ["ShadowCalibrationRunner"]
