"""[EXEC pépite 250] DUST ACCUMULATOR : plusieurs minuscules résidus COMPATIBLES (même coin, même sens) peuvent être
AGRÉGÉS jusqu'à devenir une fermeture économiquement exécutable (au-dessus du minimum notional). Au lieu de laisser
chaque miette bloquée, on les cumule et on déclenche la fermeture dès que le cumul franchit le seuil. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any


class AccumulateurDust:
    """Cumule les résidus dust par coin ; signale quand le cumul (en notional) devient exécutable."""

    def __init__(self, *, min_notional: float) -> None:
        self.min_notional = float(min_notional)
        self._cumul: dict[str, float] = {}

    def ajouter(self, coin: str, qte: Any, *, prix: Any) -> dict[str, Any]:
        """Ajoute un résidu et indique si le cumul atteint le minimum notional exécutable. Données invalides →
        refus (on n'exécute pas sur un cumul incertain)."""
        if not all(isinstance(x, (int, float)) for x in (qte, prix)) or float(prix) <= 0:
            return {"ok": False, "raison": "DONNEE_INVALIDE"}
        c = str(coin).upper()
        self._cumul[c] = round(self._cumul.get(c, 0.0) + float(qte), 12)
        notional = abs(self._cumul[c]) * float(prix)
        executable = notional >= self.min_notional
        return {"ok": True, "cumul_qte": self._cumul[c], "notional": round(notional, 8),
                "executable": bool(executable),
                "raison": ("CUMUL_EXECUTABLE" if executable else "ENCORE_SOUS_MINIMUM")}

    def vider(self, coin: str) -> None:
        """Après exécution du cumul, on remet le compteur du coin à zéro."""
        self._cumul[str(coin).upper()] = 0.0


__all__ = ["AccumulateurDust"]
