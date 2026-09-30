"""[DATA lot2 #98] PROCESSUS RECORDER SÉPARÉ DU MOTEUR DE DÉCISION : le recorder (écriture disque des données) est
DÉCOUPLÉ du moteur de décision et communique par file/IPC, pour qu'une GROSSE écriture disque ne ralentisse JAMAIS la
détection d'arbitrage (VeighNa : RPC service + data recorder séparables). On modélise le découplage : enfiler un
enregistrement est immédiat (non bloquant) ; le drain se fait à part. La latence de décision est indépendante du
disque. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


class RecorderDecouple:
    """File non bloquante entre le moteur de décision et le recorder. `enfiler` ne bloque pas sur le disque."""

    def __init__(self, *, capacite: int = 100_000) -> None:
        self.capacite = int(capacite)
        self._file: list[Any] = []
        self.deposes = 0
        self.perdus = 0

    def enfiler(self, enregistrement: Any) -> dict[str, Any]:
        """Dépose un enregistrement (immédiat, non bloquant). File pleine → l'enregistrement est DROPPÉ et compté
        (jamais bloquer la décision pour écrire ; la perte est explicite, pas masquée)."""
        if len(self._file) >= self.capacite:
            self.perdus += 1
            return {"depose": False, "raison": "FILE_PLEINE_DROP", "perdus": self.perdus}
        self._file.append(enregistrement)
        self.deposes += 1
        return {"depose": True, "en_attente": len(self._file)}

    def drainer(self, *, lot: int = 1000) -> dict[str, Any]:
        """Le recorder (processus séparé) draine un lot pour écriture. N'affecte pas le chemin de décision."""
        n = min(int(lot), len(self._file))
        ecrits = self._file[:n]
        self._file = self._file[n:]
        return {"ecrits": len(ecrits), "reste": len(self._file)}


__all__ = ["RecorderDecouple"]
