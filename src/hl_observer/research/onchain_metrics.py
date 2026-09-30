"""[DATA-102/103/104] Metriques on-chain OFFLINE (calculees sur des donnees FOURNIES, pas fetchees en
live) : NETFLOWS d'exchange (depots-retraits), flux de WHALES (gros mouvements) et REGIME d'open
interest des derives. stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence


def exchange_netflows(mouvements: Sequence[Mapping]) -> dict:
    """Netflow d'exchange = depots - retraits (> 0 = afflux vers l'exchange = pression vendeuse
    potentielle). Calcule sur des mouvements FOURNIS (offline)."""
    depots = sum(m.get("montant", 0.0) for m in mouvements if m.get("direction") == "in")
    retraits = sum(m.get("montant", 0.0) for m in mouvements if m.get("direction") == "out")
    net = depots - retraits
    return {"netflow": net, "depots": depots, "retraits": retraits,
            "biais": "AFFLUX" if net > 0 else ("REFLUX" if net < 0 else "NEUTRE")}


def whale_flows(mouvements: Sequence[Mapping], *, seuil_usd: float = 1_000_000.0) -> dict:
    """Flux de WHALES : ne garde que les mouvements >= seuil (les gros acteurs bougent le marche)."""
    whales = [m for m in mouvements if abs(m.get("montant_usd", 0.0)) >= seuil_usd]
    return {"n_whales": len(whales), "flux_net_usd": sum(m.get("montant_usd", 0.0) for m in whales)}


def regime_open_interest(oi_serie: Sequence[float], *, seuil: float = 0.10) -> dict:
    """Regime d'OI des derives : classe la TENDANCE de l'open interest (variation relative debut->fin).
    EXPANSION (nouveaux positionnements) / CONTRACTION (deleveraging) / STABLE."""
    if len(oi_serie) < 2:
        return {"regime": "INDETERMINE", "variation": 0.0}
    debut, fin = oi_serie[0], oi_serie[-1]
    var = (fin - debut) / debut if debut else 0.0
    regime = "EXPANSION" if var >= seuil else ("CONTRACTION" if var <= -seuil else "STABLE")
    return {"regime": regime, "variation": round(var, 4)}
