"""[AUD-298/299] Politique CEX : n'utiliser QUE des donnees CEX PUBLIQUES (jamais d'endpoint prive/
authentifie d'ordre ou de compte) et marquer tout wallet CEX comme NON COPIABLE (un compte interne
d'exchange n'est pas un leader reproductible). stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

from typing import Mapping, Sequence

_PRIVES = ("/order", "/account", "/private", "signed=true", "apikey", "/withdraw", "/position")


def verifier_cex_public_seulement(endpoints: Sequence[str]) -> dict:
    """Refuse tout endpoint CEX PRIVE/authentifie (ordre, compte, retrait). Seules les donnees
    publiques (orderbook, trades, funding) sont autorisees -> lecture seule stricte, 0 ordre reel."""
    prives = [e for e in endpoints if any(p in e.lower() for p in _PRIVES)]
    return {"public_seulement": len(prives) == 0, "endpoints_prives": prives}


def marquer_wallet_cex_non_copiable(wallet: Mapping) -> dict:
    """Un wallet CEX (compte interne d'exchange) n'est PAS un leader copiable : marque explicitement
    non-copiable pour qu'il ne soit jamais propose comme cible de copy-trading."""
    est_cex = bool(wallet.get("is_cex") or str(wallet.get("type", "")).upper() == "CEX")
    return {**dict(wallet), "copiable": not est_cex,
            "raison": "WALLET_CEX_NON_COPIABLE" if est_cex else None}
