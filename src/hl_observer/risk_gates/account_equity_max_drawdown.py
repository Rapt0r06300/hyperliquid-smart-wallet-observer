"""[RISK lot2 #100] ACCOUNT-EQUITY MaxDrawdown + COOLDOWN : couper temporairement un module quand la VRAIE equity du
compte chute d'un seuil depuis son pic, puis imposer un COOLDOWN avant reprise. On travaille sur l'equity RÉELLE du
compte (pas un PnL de stratégie isolé), à la manière du MaxDrawdown amélioré de Freqtrade. Un drawdown au-delà du
seuil → HALTED ; après le cooldown → reprise autorisée. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

RUNNING = "RUNNING"
HALTED = "HALTED"


class MaxDrawdownCooldown:
    """Suit le pic d'equity du compte ; HALTED si drawdown > seuil ; reprise après cooldown_ms."""

    def __init__(self, *, seuil_drawdown_pct: float = 10.0, cooldown_ms: float = 3_600_000.0) -> None:
        self.seuil_pct = float(seuil_drawdown_pct)
        self.cooldown_ms = float(cooldown_ms)
        self._pic: Any = None
        self._halt_jusqu: Any = None

    def evaluer(self, equity: Any, *, now_ms: Any) -> dict[str, Any]:
        """Met à jour le pic, calcule le drawdown, déclenche/maintient le HALT + cooldown. Equity/temps invalide →
        HALTED (prudence : on ne trade pas sans mesure d'equity fiable)."""
        if not all(isinstance(x, (int, float)) for x in (equity, now_ms)):
            return {"etat": HALTED, "raison": "EQUITY_OU_TEMPS_INVALIDE"}
        if self._pic is None or float(equity) > self._pic:
            self._pic = float(equity)
        drawdown_pct = (self._pic - float(equity)) / self._pic * 100.0 if self._pic > 0 else 0.0
        if self._halt_jusqu is not None and float(now_ms) < self._halt_jusqu:
            return {"etat": HALTED, "drawdown_pct": round(drawdown_pct, 4),
                    "reste_cooldown_ms": round(self._halt_jusqu - float(now_ms), 3), "raison": "EN_COOLDOWN"}
        if drawdown_pct > self.seuil_pct:
            self._halt_jusqu = float(now_ms) + self.cooldown_ms
            return {"etat": HALTED, "drawdown_pct": round(drawdown_pct, 4),
                    "raison": "MAX_DRAWDOWN_DEPASSE"}
        return {"etat": RUNNING, "drawdown_pct": round(drawdown_pct, 4), "pic": round(self._pic, 8)}


__all__ = ["MaxDrawdownCooldown", "RUNNING", "HALTED"]
