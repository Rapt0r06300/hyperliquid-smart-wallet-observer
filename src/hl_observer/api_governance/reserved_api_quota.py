"""[ARB lot2 #24] QUOTA API RÉSERVÉ cancel/reconcile/hedge : une partie du quota API est réservée EN PERMANENCE aux
opérations critiques (cancel, reconcile, hedge) et n'est JAMAIS consommée par la discovery (scan/scoring). Sinon une
rafale de discovery peut épuiser le quota au pire moment — quand il faut annuler ou se couvrir. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

CRITIQUE = ("CANCEL", "RECONCILE", "HEDGE")
DISCOVERY = "DISCOVERY"


class QuotaReserve:
    """Sépare le quota en pool réservé (critique) et pool libre. La discovery ne peut toucher qu'au pool libre."""

    def __init__(self, *, quota_total: float, reserve_critique: float) -> None:
        self.quota_total = float(quota_total)
        self.reserve_critique = min(float(reserve_critique), float(quota_total))
        self._utilise = 0.0

    def libre_pour_discovery(self) -> float:
        return round(max(0.0, self.quota_total - self.reserve_critique - self._utilise), 6)

    def peut_consommer(self, categorie: Any, *, cout: float = 1.0) -> dict[str, Any]:
        """Les opérations critiques peuvent puiser dans tout le quota restant ; la discovery seulement dans le
        pool libre (hors réserve critique)."""
        cat = str(categorie).upper()
        restant_total = self.quota_total - self._utilise
        if cat in CRITIQUE:
            ok = float(cout) <= restant_total + 1e-9
            return {"ok": bool(ok), "categorie": cat, "raison": ("OK" if ok else "QUOTA_EPUISE")}
        ok = float(cout) <= self.libre_pour_discovery() + 1e-9
        return {"ok": bool(ok), "categorie": DISCOVERY,
                "raison": ("OK" if ok else "RESERVE_CRITIQUE_PROTEGEE")}

    def consommer(self, categorie: Any, *, cout: float = 1.0) -> bool:
        if not self.peut_consommer(categorie, cout=cout)["ok"]:
            return False
        self._utilise += float(cout)
        return True


__all__ = ["QuotaReserve", "CRITIQUE", "DISCOVERY"]
