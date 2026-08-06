"""[DATA connecteurs venues] Socle COMMUN des adaptateurs de venues : erreurs honnetes de frontiere
reseau/cle, construction de lignes au schema CANONIQUE (aligne medallion.CHAMPS_SILVER), detection de
trous de sequence (snapshot/delta), et client live-gate qui LEVE toujours (jamais de faux succes).
0 reseau, 0 cle, 0 ordre reel : ce module prouve la LOGIQUE de parsing/normalisation hors-ligne ; le
pull live reste explicitement derriere une frontiere REQUIRES_NETWORK / REQUIRES_KEY."""
from __future__ import annotations

from typing import Mapping, Optional, Sequence

# --- statut honnete de capacite (aligne research.venue_capabilities) ---
OFFLINE_READY = "OFFLINE_READY"          # adaptateur + tests offline presents
REQUIRES_NETWORK = "REQUIRES_NETWORK"    # pull live exige un reseau (non prouvable en sandbox)
REQUIRES_KEY = "REQUIRES_KEY"            # exige en plus une cle API read-only (fournisseur paye)

CHAMPS_SILVER = ("ts", "venue", "symbole", "type", "prix", "taille", "side")
SIDE_ACHAT, SIDE_VENTE = "buy", "sell"


class ReseauRequisError(RuntimeError):
    """Levee quand on tente un pull LIVE dans un environnement sans reseau (frontiere honnete)."""


class CleRequiseError(RuntimeError):
    """Levee quand un fournisseur exige une cle API read-only non fournie (Nansen/Dune/Glassnode)."""


def to_float(x) -> Optional[float]:
    """Conversion sure -> float, None si vide/illisible (jamais un faux 0)."""
    try:
        return float(x) if x is not None and x != "" else None
    except (TypeError, ValueError):
        return None


def norm_side(v) -> Optional[str]:
    """Normalise un sens agressor/taker vers buy/sell (AUD-347). None si inconnu (jamais invente)."""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("b", "buy", "bid", "long"):
        return SIDE_ACHAT
    if s in ("s", "sell", "ask", "short"):
        return SIDE_VENTE
    return None


def ligne(*, ts, venue, symbole, type_, prix=None, taille=None, side=None, **extra) -> dict:
    """Construit une ligne au schema CANONIQUE (medallion silver). Champ absent -> None (jamais invente)."""
    d = {"ts": ts, "venue": venue, "symbole": symbole, "type": type_,
         "prix": to_float(prix) if prix is not None else None,
         "taille": to_float(taille) if taille is not None else None,
         "side": norm_side(side) if side is not None else None}
    if extra:
        d["_extra"] = dict(extra)
    return d


def niveaux(rows: Sequence[Sequence]) -> list:
    """[[prix, taille], ...] -> [{prix, taille}]. taille 0 = suppression de niveau (delta)."""
    out = []
    for r in rows or ():
        try:
            out.append({"prix": float(r[0]), "taille": float(r[1])})
        except (TypeError, ValueError, IndexError):
            continue
    return out


def nbbo(bids: Sequence[Mapping], asks: Sequence[Mapping]) -> dict:
    """Meilleur bid/ask a partir de niveaux normalises (taille > 0)."""
    bb = max((n["prix"] for n in (bids or ()) if n.get("taille", 0) > 0), default=None)
    ba = min((n["prix"] for n in (asks or ()) if n.get("taille", 0) > 0), default=None)
    return {"best_bid": bb, "best_ask": ba,
            "spread": (ba - bb) if (bb is not None and ba is not None) else None}


class DetecteurSequence:
    """Detecte les TROUS de sequence dans un flux snapshot/delta (u / seq / prevSeqId).
    resync=True quand un delta arrive avant le snapshot ou qu'un id est saute -> il FAUT re-synchroniser
    (AUD-338 / DATA-047 / 053 / 069). Ne masque jamais un trou : il le signale explicitement."""

    def __init__(self) -> None:
        self._dernier: Optional[int] = None
        self._synchronise = False

    @property
    def synchronise(self) -> bool:
        return self._synchronise

    def snapshot(self, uid) -> None:
        self._dernier = int(uid)
        self._synchronise = True

    def delta(self, uid, prev=None) -> dict:
        uid = int(uid)
        if not self._synchronise or self._dernier is None:
            self._synchronise = False
            return {"applique": False, "resync": True, "raison": "delta_avant_snapshot"}
        if prev is not None:
            if int(prev) != self._dernier:
                self._synchronise = False
                return {"applique": False, "resync": True, "raison": "prev_mismatch"}
        elif uid != self._dernier + 1:
            self._synchronise = False
            return {"applique": False, "resync": True, "raison": "trou_sequence"}
        self._dernier = uid
        return {"applique": True, "resync": False, "raison": None}


class ClientLiveBase:
    """Client LIVE-gate : toute methode de pull LEVE ReseauRequisError / CleRequiseError. On ne renvoie
    JAMAIS un faux succes ni des donnees inventees (AUD-313 / 384). Le parsing/replay se fait hors-ligne."""

    statut = REQUIRES_NETWORK
    exige_cle = False

    def __init__(self, *, venue: str) -> None:
        self.venue = venue

    def _refuser(self, quoi: str):
        if self.exige_cle:
            raise CleRequiseError(
                "%s: pull live '%s' exige reseau + cle read-only (absent en sandbox)" % (self.venue, quoi))
        raise ReseauRequisError(
            "%s: pull live '%s' exige un reseau (absent en sandbox paper)" % (self.venue, quoi))
