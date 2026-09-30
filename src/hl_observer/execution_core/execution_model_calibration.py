"""[ALL #99] EXECUTION-MODEL CALIBRATION BY REALIZED SHORTFALL : chaque modèle d'exécution enregistre son
predicted_fill_price face au realized paper executable price. Si son biais devient SYSTÉMATIQUE (il prédit
constamment mieux que la réalité), le modèle est automatiquement marqué NON FIABLE — on ne lui fait plus confiance
pour chiffrer un edge. Rapprocher trajectoires sim vs réel (esprit hftbacktest). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


class CalibrationModele:
    """Suit l'erreur (prédit − réalisé) d'un modèle. Un biais systématique au-delà d'un seuil → NON FIABLE."""

    def __init__(self) -> None:
        self._erreurs_bps: list[float] = []

    def enregistrer(self, predicted_fill_price: Any, realized_executable_price: Any, *,
                    sens: Any = "ACHAT") -> dict[str, Any]:
        """Erreur orientée « optimisme » : un modèle qui prédit un meilleur prix que la réalité a un biais positif.
        À l'achat, prédire moins cher que réalisé = optimiste (+). À la vente, prédire plus cher = optimiste (+)."""
        if not all(isinstance(x, (int, float)) for x in (predicted_fill_price, realized_executable_price)) \
                or float(realized_executable_price) <= 0:
            return {"ok": False, "raison": "PRIX_INVALIDE"}
        diff = (float(realized_executable_price) - float(predicted_fill_price)) / float(realized_executable_price) * 1e4
        if str(sens).upper() in ("VENTE", "SELL", "SHORT"):
            diff = -diff
        self._erreurs_bps.append(round(diff, 4))
        return {"ok": True, "erreur_bps": round(diff, 4), "n": len(self._erreurs_bps)}

    def biais_bps(self) -> Any:
        if not self._erreurs_bps:
            return UNMEASURABLE
        return round(sum(self._erreurs_bps) / len(self._erreurs_bps), 4)

    def fiable(self, *, seuil_biais_bps: float = 5.0, min_echantillons: int = 20) -> dict[str, Any]:
        """Fiable seulement avec assez d'échantillons ET un biais moyen sous le seuil. Trop peu d'échantillons →
        UNKNOWN (jamais déclaré fiable par défaut)."""
        n = len(self._erreurs_bps)
        if n < int(min_echantillons):
            return {"fiable": None, "raison": "ECHANTILLON_INSUFFISANT", "n": n}
        b = self.biais_bps()
        ok = abs(b) <= float(seuil_biais_bps)
        return {"fiable": bool(ok), "biais_bps": b, "n": n,
                "raison": ("OK" if ok else "BIAIS_SYSTEMATIQUE_NON_FIABLE")}


__all__ = ["CalibrationModele", "UNMEASURABLE"]
