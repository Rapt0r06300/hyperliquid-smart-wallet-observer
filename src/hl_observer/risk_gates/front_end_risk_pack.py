"""[RISK lot2 #99] FRONT-END RISK PACK : une batterie de limites « garde-fou » par module — ordres/seconde, nombre
d'ordres actifs, volume max par ordre, total d'annulations et ratio de cancel. Ces limites attrapent un module qui
part en boucle (spam d'ordres, churn massif) AVANT qu'il ne fasse des dégâts ou ne se fasse bannir (catégorie exposée
par le risk_manager de VeighNa). Toute limite dépassée → ordre refusé. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class ControleFrontEnd:
    """Applique les limites front-end par module. Un dépassement (débit, actifs, volume, ratio cancel) refuse."""

    def __init__(self, *, max_ordres_par_s: float = 10.0, max_ordres_actifs: int = 50,
                 volume_max_par_ordre: float = 1e6, ratio_cancel_max: float = 0.9) -> None:
        self.max_ordres_par_s = float(max_ordres_par_s)
        self.max_ordres_actifs = int(max_ordres_actifs)
        self.volume_max_par_ordre = float(volume_max_par_ordre)
        self.ratio_cancel_max = float(ratio_cancel_max)

    def valider_ordre(self, *, debit_ordres_par_s: Any, ordres_actifs: Any, volume_ordre: Any,
                      n_envois: Any = 1, n_cancels: Any = 0) -> dict[str, Any]:
        """Refuse si une limite est franchie. Donnée manquante → refus (fail-closed). Le ratio de cancel n'est
        évalué que sur un échantillon significatif (≥ 10 envois)."""
        if not all(isinstance(x, (int, float)) for x in (debit_ordres_par_s, ordres_actifs, volume_ordre)):
            return {"ok": False, "raison": "DONNEE_INVALIDE"}
        violations = []
        if float(debit_ordres_par_s) > self.max_ordres_par_s:
            violations.append("DEBIT_ORDRES")
        if int(ordres_actifs) > self.max_ordres_actifs:
            violations.append("ORDRES_ACTIFS")
        if abs(float(volume_ordre)) > self.volume_max_par_ordre:
            violations.append("VOLUME_ORDRE")
        if isinstance(n_envois, (int, float)) and int(n_envois) >= 10 and isinstance(n_cancels, (int, float)):
            if (float(n_cancels) / float(n_envois)) > self.ratio_cancel_max:
                violations.append("RATIO_CANCEL")
        ok = not violations
        return {"ok": bool(ok), "violations": violations, "raison": ("OK" if ok else "LIMITE_FRONT_END_DEPASSEE")}


__all__ = ["ControleFrontEnd"]
