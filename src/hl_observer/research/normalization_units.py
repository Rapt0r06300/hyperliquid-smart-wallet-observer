"""[AUD-305/307/341/345/346/349] Normalisation d'unites : OPEN INTEREST vers une unite commune
(notionnel USD), SENS de liquidation canonique (ordre force BUY/SELL), methodologies MARK/INDEX
VERSIONNEES et symbol master POINT-IN-TIME. stdlib pure, 0 reseau."""
from __future__ import annotations

from typing import Mapping, Sequence


def normaliser_open_interest(oi: float, *, unite: str, prix: float = 1.0, multiplicateur: float = 1.0) -> dict:
    """OI en unite COMMUNE (notionnel USD). base/contracts -> *prix*multiplicateur ; usd/quote -> tel
    quel. Sans normalisation, comparer l'OI de deux venues n'a aucun sens."""
    u = unite.lower()
    if u in ("usd", "quote", "notional"):
        notionnel = float(oi)
    elif u in ("base", "coin", "contracts", "contract"):
        notionnel = float(oi) * float(prix) * float(multiplicateur)
    else:
        raise ValueError("unite OI inconnue: %s" % unite)
    return {"oi_usd": notionnel, "unite_source": unite}


def normaliser_sens_liquidation(side: str, *, convention: str = "position") -> dict:
    """Sens de liquidation CANONIQUE -> toujours l'ordre FORCE (BUY/SELL). convention='position' : un
    long liquide = vente forcee ; convention='order' : le side est deja celui de l'ordre."""
    s = side.lower()
    if convention == "position":
        ordre = "SELL" if s in ("long", "buy") else "BUY"
    else:
        ordre = "BUY" if s in ("buy", "bid") else "SELL"
    return {"ordre_force": ordre, "side_source": side, "convention": convention}


class MethodologieMarkIndex:
    """Methodologies mark/index VERSIONNEES : le calcul change parfois (ponderation, sources). Chaque
    version est enregistree pour rejouer a l'identique le passe."""

    def __init__(self) -> None:
        self._versions: dict = {}

    def enregistrer(self, version: str, *, description: str, formule: str) -> None:
        self._versions[version] = {"version": version, "description": description, "formule": formule}

    def obtenir(self, version: str):
        return self._versions.get(version)

    def versions(self) -> list:
        return sorted(self._versions)


def symbol_master_pit(historique: Sequence[Mapping], venue: str, symbole: str, asof: float) -> dict:
    """Symbol master POINT-IN-TIME : le 'BTC' d'une venue a pu changer de contrat au fil du temps. On
    rend le canonique EN VIGUEUR a `asof` (dernier mapping <= asof), jamais un futur."""
    candidats = [h for h in historique
                 if h.get("venue") == venue and h.get("symbole") == symbole and h.get("depuis", 0) <= asof]
    if not candidats:
        return {"canonique": None, "asof": None}
    h = max(candidats, key=lambda x: x.get("depuis", 0))
    return {"canonique": h.get("canonique"), "asof": h.get("depuis")}
