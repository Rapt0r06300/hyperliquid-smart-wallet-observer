"""[ALL pépite 300] LOW-PROFIT MODULE LOCK : inspiré du LowProfitPairs de Freqtrade. Si un module/coin accumule
ASSEZ d'épisodes complets mais reste sous un seuil de PnL net, on le met en COOLDOWN automatiquement — même sans
gros drawdown. C'est une protection SÉPARÉE du stoploss et du MaxDrawdown : elle cible le « ça ne perd pas
beaucoup mais ça ne gagne rien non plus », qui érode le capital en frais sans jamais déclencher une coupe de
risque. Après verrouillage, les stats se réinitialisent (réévaluation sur une nouvelle fenêtre). Pur, 0 réseau,
0 ordre réel.
"""
from __future__ import annotations

import math
from typing import Any


class VerrouFaibleProfit:
    """Par clé (module/coin) : accumule nombre d'épisodes et PnL net cumulé. Dès min_episodes atteints avec un
    net < seuil_net, verrouille la clé jusqu'à t + cooldown_s, puis réinitialise ses stats. est_verrouille()
    compare à un instant fourni (pur, pas d'horloge interne)."""

    def __init__(self, min_episodes: int = 10, seuil_net: float = 0.0, cooldown_s: float = 3600.0) -> None:
        self._min = max(1, int(min_episodes))
        self._seuil = float(seuil_net)
        self._cooldown = float(cooldown_s)
        self._stats: dict[Any, dict[str, float]] = {}
        self._verrou: dict[Any, float] = {}

    def enregistrer_episode(self, cle: Any, pnl_net: Any, t: Any) -> dict[str, Any]:
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                   for x in (pnl_net, t)):
            return {"ok": False, "raison": "DONNEE_INVALIDE"}
        s = self._stats.setdefault(cle, {"episodes": 0, "net_cumule": 0.0})
        s["episodes"] += 1
        s["net_cumule"] += float(pnl_net)
        if s["episodes"] >= self._min and s["net_cumule"] < self._seuil:
            jusqu_a = float(t) + self._cooldown
            self._verrou[cle] = jusqu_a
            net = s["net_cumule"]
            self._stats[cle] = {"episodes": 0, "net_cumule": 0.0}     # réévaluation nouvelle fenêtre
            return {"verrou_declenche": True, "jusqu_a": jusqu_a, "net_fenetre": round(net, 8)}
        return {"verrou_declenche": False, "episodes": s["episodes"],
                "net_cumule": round(s["net_cumule"], 8)}

    def est_verrouille(self, cle: Any, maintenant: Any) -> dict[str, Any]:
        exp = self._verrou.get(cle)
        if exp is None:
            return {"verrouille": False}
        if isinstance(maintenant, (int, float)) and not isinstance(maintenant, bool) and maintenant >= exp:
            return {"verrouille": False, "raison": "COOLDOWN_EXPIRE"}
        return {"verrouille": True, "jusqu_a": exp, "raison": "FAIBLE_PROFIT"}


__all__ = ["VerrouFaibleProfit"]
