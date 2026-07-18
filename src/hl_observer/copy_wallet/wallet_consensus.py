"""C14 — CONSENSUS de wallets INDÉPENDANTS : exiger l'accord de PLUSIEURS, pas d'une baleine.

Un seul gros wallet peut se tromper — ou manipuler (afficher un signal pour piéger les suiveurs).
Exiger N wallets INDÉPENDANTS d'accord sur la même direction filtre le bruit et la manipulation.

Indépendants = adresses DISTINCTES qui ne sont PAS dans le même groupe corrélé (une même entité,
des wallets qui bougent ensemble, comptent pour UN seul).

⚠️ Honnête : la vraie indépendance demande une analyse de corrélation (à mesurer). v1 : adresses
distinctes + groupes corrélés CONNUS repliés sur un représentant. Deny-by-default : sous le quorum,
ou pas de côté dominant -> None (pas de consensus). Un consensus n'est pas un ordre. PAPER only.
"""
from __future__ import annotations

from typing import Any, Iterable

QUORUM_DEFAUT = 3          # au moins 3 wallets indépendants d'accord


def _norm_side(side: str) -> str | None:
    s = str(side or "").upper()
    if s in ("BUY", "LONG", "B"):
        return "LONG"
    if s in ("SELL", "SHORT", "S"):
        return "SHORT"
    return None


def _representant(adresse: str, groupes: Iterable[frozenset] | None) -> str:
    """Replie une adresse corrélée sur un représentant stable (le min du groupe)."""
    for g in groupes or []:
        if adresse in g:
            return min(g)
    return adresse


def consensus(signaux: Iterable[dict], *, min_wallets: int = QUORUM_DEFAUT,
              groupes_correles: Iterable[frozenset] | None = None) -> dict[str, Any] | None:
    """Renvoie {direction, n_independants, n_oppose} si >= min_wallets wallets INDÉPENDANTS sont
    d'accord ET dominent strictement le côté opposé. Sinon None."""
    par_side: dict[str, set] = {"LONG": set(), "SHORT": set()}
    for s in signaux or []:
        if not isinstance(s, dict):
            continue
        side = _norm_side(s.get("side"))
        adr = str(s.get("adresse") or "")
        if side is None or not adr:
            continue
        par_side[side].add(_representant(adr, groupes_correles))
    n_long, n_short = len(par_side["LONG"]), len(par_side["SHORT"])
    if n_long == n_short:
        return None                                   # égalité -> pas de côté net
    gagnant, n, n_opp = ("LONG", n_long, n_short) if n_long > n_short else ("SHORT", n_short, n_long)
    if n >= int(min_wallets):
        return {"direction": gagnant, "n_independants": n, "n_oppose": n_opp}
    return None


__all__ = ["QUORUM_DEFAUT", "consensus"]
