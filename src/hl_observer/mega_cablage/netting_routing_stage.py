"""[CABLAGE étage D] NETTING / ROUTING : toutes les intentions d'un tick (copie + hedge cross-venue + autres)
convergent ici AVANT le PaperEngine. On compose les VRAIES primitives :
  - execution_core.cross_module_self_trade_prevention : signale les auto-croisements (achat+vente même venue/coin) ;
  - execution_core.economic_priority_allocator        : ordonne par priorité économique (hedge > close > entry) ;
  - execution_core.global_intent_netting              : nette par (venue, coin) → un delta net (économie du spread) ;
  - routing.route_graph                                : choisit la route au COÛT EXÉCUTABLE total le plus bas ;
  - execution_core.canonical_order_candidate           : point d'entrée UNIQUE et pré-validé vers le PaperEngine.
Un net nul → aucun candidat (pas d'ordre inutile). Prix absent → candidat refusé (fail-closed). 0 réseau, 0 ordre.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from hl_observer.execution_core.global_intent_netting import netter
from hl_observer.execution_core.cross_module_self_trade_prevention import detecter as detecter_self_trade
from hl_observer.execution_core.economic_priority_allocator import ordonnancer
from hl_observer.routing.route_graph import classer as classer_routes
from hl_observer.execution_core.canonical_order_candidate import creer_candidat


def netter_et_router(intentions: Iterable[dict[str, Any]], *, prix_par_coin: dict[str, Any],
                     routes_par_cle: dict[str, list] | None = None,
                     budget_par_cle: dict[str, float] | None = None,
                     seuil_notional: float = 1e-6, type_exec_defaut: str = "TAKER") -> dict[str, Any]:
    """Retourne {self_trade, priorite, netting, candidats:[{cle,venue,coin,net,cote,candidat,route,raison}]}.
    Chaque candidat non nul passe par creer_candidat (canonical) : structure validée avant le PaperEngine."""
    intentions = list(intentions)
    self_trade = detecter_self_trade(intentions)
    priorite = ordonnancer(intentions)
    net = netter(intentions)
    routes_par_cle = routes_par_cle or {}
    budget_par_cle = budget_par_cle or {}
    candidats: list[dict[str, Any]] = []
    for cle, agg in net["net_par_cle"].items():
        venue, _, coin = cle.partition("/")
        net_signe = agg["net"]
        base = {"cle": cle, "venue": venue, "coin": coin, "net": net_signe}
        if abs(net_signe) < seuil_notional:
            candidats.append({**base, "candidat": None, "raison": "NET_NUL"})
            continue
        prix = prix_par_coin.get(coin)
        if not isinstance(prix, (int, float)) or prix <= 0:
            candidats.append({**base, "candidat": None, "raison": "PRIX_ABSENT"})
            continue
        cote = "BUY" if net_signe > 0 else "SELL"
        type_exec = type_exec_defaut
        meilleure_route = None
        routes = routes_par_cle.get(cle)
        if routes:
            classement = classer_routes(routes)
            meilleure_route = classement.get("meilleure")
            if meilleure_route:
                parts = str(meilleure_route.get("cle", "")).split("|")
                if len(parts) == 4 and parts[3] in ("MAKER", "TAKER"):
                    type_exec = parts[3]
        quantite = abs(net_signe) / float(prix)
        budget = budget_par_cle.get(cle, abs(net_signe))
        cand = creer_candidat(coin=coin, cote=cote, quantite=quantite, prix=float(prix),
                              type_exec=type_exec, budget_disponible=budget)
        candidats.append({**base, "cote": cote, "candidat": cand, "route": meilleure_route,
                          "raison": ("OK" if cand.get("valide") else "CANDIDAT_REFUSE")})
    return {"self_trade": self_trade, "priorite": priorite, "netting": net, "candidats": candidats}


__all__ = ["netter_et_router"]
