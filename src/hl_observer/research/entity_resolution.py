"""[AUD-285/286] Resolution d'ENTITES (fusionner par Union-Find les wallets d'un meme acteur
cross-protocole a partir de liens declares -> ne pas compter un acteur comme N wallets independants,
sinon le crowding est faux) et PROVENANCE des labels (chaque label porte source + asof, jamais un
label orphelin non tracable). stdlib pure, 0 reseau."""
from __future__ import annotations

from typing import Sequence, Tuple


def resoudre_entites(liens: Sequence[Tuple[str, str]]) -> dict:
    """Union-Find sur des liens (wallet_a, wallet_b) declares equivalents -> regroupe les wallets d'un
    MEME acteur. Deterministe (groupes tries)."""
    parent: dict[str, str] = {}

    def trouver(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def unir(a: str, b: str) -> None:
        ra, rb = trouver(a), trouver(b)
        if ra != rb:
            parent[ra] = rb

    for a, b in liens:
        unir(a, b)
    groupes: dict[str, set] = {}
    for x in list(parent):
        groupes.setdefault(trouver(x), set()).add(x)
    entites = sorted(sorted(g) for g in groupes.values())
    return {"n_entites": len(entites), "entites": entites}


def provenance_label(label: str, *, source: str, asof: float) -> dict:
    """Un label SANS provenance est inexploitable (on ne peut pas le remonter a un rapport). La source
    est OBLIGATOIRE ; l'asof (point-in-time) evite d'utiliser un label anachronique."""
    if not source:
        raise ValueError("un label doit porter une source (provenance obligatoire)")
    return {"label": label, "source": source, "asof": asof, "tracable": True}
