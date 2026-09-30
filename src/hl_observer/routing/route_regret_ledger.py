"""[CROSS-VENUE pépite 242] ROUTE-REGRET LEDGER : après chaque épisode, calculer le PnL OBTENU versus la MEILLEURE
route qui était réellement DISPONIBLE au timestamp de décision. Le « regret » = ce qu'on a laissé sur la table en
choisissant la mauvaise route. Accumulé, il dit si le moteur de routage se trompe systématiquement (regret positif
persistant) — un signal d'amélioration, mesuré honnêtement sur des routes qui existaient vraiment. Pur, 0 réseau.
"""
from __future__ import annotations

from typing import Any


class RegretLedger:
    """Accumule le regret de routage : (meilleur PnL disponible − PnL réalisé) par épisode."""

    def __init__(self) -> None:
        self._regrets: list[float] = []

    def enregistrer(self, *, pnl_realise: Any, pnl_meilleure_route_dispo: Any) -> dict[str, Any]:
        """Regret = meilleur PnL réellement disponible à la décision − PnL réalisé. Données invalides → non
        enregistré (on ne fabrique pas un regret). Un regret négatif (on a fait mieux que la 'meilleure' estimée)
        est borné à 0."""
        if not all(isinstance(x, (int, float)) for x in (pnl_realise, pnl_meilleure_route_dispo)):
            return {"ok": False, "raison": "PNL_INVALIDE"}
        regret = max(0.0, float(pnl_meilleure_route_dispo) - float(pnl_realise))
        self._regrets.append(regret)
        return {"ok": True, "regret": round(regret, 8)}

    def resume(self) -> dict[str, Any]:
        n = len(self._regrets)
        total = sum(self._regrets)
        return {"n_episodes": n, "regret_total": round(total, 8),
                "regret_moyen": round(total / n, 8) if n else 0.0}


__all__ = ["RegretLedger"]
