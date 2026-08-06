"""[AUD-268..291 / DATA-048,276,320] Registre AGREGE des adaptateurs de venues. Chaque venue porte
desormais un adaptateur OFFLINE prouve (normalizers + tests) ET une frontiere de pull LIVE honnete :
REQUIRES_NETWORK (public, reseau) ou REQUIRES_KEY (fournisseur paye). On ne declare JAMAIS 'live-ok' :
le pull live reste gate. Complementaire de research.venue_capabilities (etat prudent par defaut).
stdlib pure, 0 reseau."""
from __future__ import annotations

from . import (bybit, coinbase, defillama, deribit, drift, dune, glassnode, gmx, kraken, nansen, okx)

_MODULES = (bybit, okx, coinbase, deribit, kraken, drift, gmx, nansen, dune, glassnode, defillama)


def registre() -> dict:
    """venue -> capacites() (adaptateur offline + frontiere live)."""
    return {m.VENUE: m.capacites() for m in _MODULES}


def offline_ready() -> list:
    return sorted(v for v, c in registre().items() if c["adaptateur"] == "OFFLINE_READY")


def par_frontiere_live() -> dict:
    """Repartit les venues par frontiere de pull live (REQUIRES_NETWORK vs REQUIRES_KEY)."""
    out: dict = {}
    for v, c in registre().items():
        out.setdefault(c["pull_live"], []).append(v)
    return {k: sorted(vs) for k, vs in out.items()}


def ready_multi_venue(requis=("bybit", "okx", "coinbase", "deribit", "kraken")) -> dict:
    """READY_MULTI_VENUE = toutes les venues requises ont un adaptateur OFFLINE_READY (AUD-276/320)."""
    reg = registre()
    manquants = [v for v in requis if reg.get(v, {}).get("adaptateur") != "OFFLINE_READY"]
    return {"ready": not manquants, "manquants": manquants,
            "offline_ready": offline_ready(), "n_venues": len(reg)}
