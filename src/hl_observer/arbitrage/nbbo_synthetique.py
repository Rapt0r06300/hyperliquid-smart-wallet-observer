"""ALPHA-6 — NBBO synthétique EXÉCUTABLE et normalisation de carnet multi-venues (pur, 0 réseau, 0 ordre).

Inspiré du principe de normalisation de Cryptofeed : ramener chaque venue au même schéma, puis calculer un
NBBO **directionnel**. Ce module ne remplace pas `arbitrage/cross_venue_contract` (contrat de sens à deux
jambes, bloc 2) : il le prolonge à N venues et lui fournit des routes exécutables.

Les quatre règles qui empêchent de fabriquer un faux arbitrage :

1. **Mapping de symboles versionné.** Un actif canonique n'existe que s'il est déclaré. Un symbole inconnu
   n'est jamais deviné : il est signalé. Si le mapping change, les actifs touchés passent en QUARANTAINE —
   un edge mesuré sous l'ancien mapping ne vaut plus rien sous le nouveau.
2. **Fraîcheur à l'horloge COURANTE** (`now - recv_wall_ts_ms`), jamais un âge persisté au moment de
   l'écriture : un collecteur mort ne doit pas produire une venue éternellement « fraîche ».
3. **Routes séparées.** La route d'achat consomme le meilleur ASK, la route de vente frappe le meilleur BID.
   Aucun mid n'apparaît dans une décision.
4. **Aucun écart de mid n'est un arbitrage.** Une opportunité exige un vrai croisement exécutable
   (meilleur bid > meilleur ask) sur **deux venues différentes**, et sa taille est bornée par la plus
   petite des deux jambes.

Donnée absente ⇒ venue exclue et raison nommée ; jamais un 0 traité comme un prix.
0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from hl_observer.arbitrage.cross_venue_contract import (
    BUY_HL_SELL_BINANCE,
    SELL_HL_BUY_BINANCE,
    CrossVenueDirection,
    VenueAction,
)

MAPPING_VERSION = "nbbo_map_v1"
AGE_MAX_MS_DEFAUT = 1_000.0

#: Mapping PRÉ-DÉCLARÉ actif canonique -> {venue: symbole}. Rien n'est deviné hors de cette table.
MAPPING_DEFAUT: dict[str, dict[str, str]] = {
    "BTC": {"HL": "BTC", "BINANCE": "BTCUSDT"},
    "ETH": {"HL": "ETH", "BINANCE": "ETHUSDT"},
    "SOL": {"HL": "SOL", "BINANCE": "SOLUSDT"},
}


@dataclass(frozen=True, slots=True)
class QuoteVenue:
    """Cotation normalisée d'une venue. `recv_wall_ts_ms` = horloge murale de RÉCEPTION (persistable)."""

    venue: str
    symbole: str
    actif: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    recv_wall_ts_ms: int

    def age_ms(self, now_ms: float) -> float:
        return float(now_ms) - float(self.recv_wall_ts_ms)

    def as_dict(self) -> dict[str, Any]:
        return {"venue": self.venue, "symbole": self.symbole, "actif": self.actif, "bid": self.bid,
                "ask": self.ask, "bid_size": self.bid_size, "ask_size": self.ask_size,
                "recv_wall_ts_ms": self.recv_wall_ts_ms}


@dataclass(frozen=True, slots=True)
class Route:
    """Jambe exécutable : un côté du carnet d'une venue précise. Jamais un mid."""

    venue: str
    actif: str
    action: VenueAction
    prix: float
    taille: float

    def as_dict(self) -> dict[str, Any]:
        return {"venue": self.venue, "actif": self.actif, "action": self.action.value,
                "prix": self.prix, "taille": self.taille}


# ════════════════════════════ mapping versionné ════════════════════════════
def hash_mapping(mapping: Mapping[str, Mapping[str, str]]) -> str:
    brut = json.dumps({k: dict(v) for k, v in mapping.items()}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:16]


def actif_canonique(venue: str, symbole: str, mapping: Mapping[str, Mapping[str, str]] | None = None) -> str | None:
    """Actif canonique, ou `None` si le couple (venue, symbole) n'est pas déclaré. Jamais deviné."""
    table = mapping if mapping is not None else MAPPING_DEFAUT
    for actif, par_venue in table.items():
        if str(par_venue.get(str(venue).upper()) or "").upper() == str(symbole).upper():
            return actif
    return None


def quarantaine_mapping(ancien_hash: str | None, mapping: Mapping[str, Mapping[str, str]] | None = None) -> dict[str, Any]:
    """Un changement de mapping met les actifs en QUARANTAINE : les mesures antérieures ne sont plus comparables."""
    table = mapping if mapping is not None else MAPPING_DEFAUT
    courant = hash_mapping(table)
    change = ancien_hash is not None and ancien_hash != courant
    return {"mapping_version": MAPPING_VERSION, "hash_courant": courant, "hash_precedent": ancien_hash,
            "change": bool(change), "statut": "QUARANTAINE" if change else "STABLE",
            "actifs_en_quarantaine": sorted(table) if change else [],
            "raison": "mapping modifie : les mesures anterieures ne sont plus comparables" if change else None}


# ════════════════════════════ normalisation ════════════════════════════
def normaliser(quotes_brutes: Iterable[Mapping[str, Any]],
               mapping: Mapping[str, Mapping[str, str]] | None = None) -> dict[str, Any]:
    """Ramène des cotations hétérogènes au schéma unique. Rend {`quotes`, `rejets`} — rien n'est deviné."""
    quotes: list[QuoteVenue] = []
    rejets: list[dict[str, Any]] = []
    for brut in quotes_brutes:
        venue = str(brut.get("venue") or "").upper()
        symbole = str(brut.get("symbole") or brut.get("symbol") or "")
        actif = actif_canonique(venue, symbole, mapping)
        if not venue or not symbole:
            rejets.append({"venue": venue, "symbole": symbole, "raison": "IDENTITE_INCOMPLETE"})
            continue
        if actif is None:
            rejets.append({"venue": venue, "symbole": symbole, "raison": "SYMBOLE_NON_MAPPE"})
            continue
        try:
            bid = float(brut["bid"])
            ask = float(brut["ask"])
            recv = int(brut["recv_wall_ts_ms"])
        except (KeyError, TypeError, ValueError):
            rejets.append({"venue": venue, "symbole": symbole, "raison": "CHAMPS_MANQUANTS"})
            continue
        if bid <= 0 or ask <= 0 or bid > ask:
            rejets.append({"venue": venue, "symbole": symbole, "raison": "CARNET_INVALIDE"})
            continue
        quotes.append(QuoteVenue(
            venue=venue, symbole=symbole, actif=actif, bid=bid, ask=ask,
            bid_size=float(brut.get("bid_size") or 0.0), ask_size=float(brut.get("ask_size") or 0.0),
            recv_wall_ts_ms=recv,
        ))
    return {"quotes": quotes, "rejets": rejets, "mapping_hash": hash_mapping(mapping or MAPPING_DEFAUT)}


def venues_fraiches(quotes: Sequence[QuoteVenue], *, now_ms: float,
                    age_max_ms: float = AGE_MAX_MS_DEFAUT) -> tuple[list[QuoteVenue], list[dict[str, Any]]]:
    """Fraîcheur calculée à l'horloge COURANTE. Un collecteur mort devient stale, il ne reste jamais frais."""
    vivantes, exclues = [], []
    for q in quotes:
        age = q.age_ms(now_ms)
        if age < 0:
            exclues.append({"venue": q.venue, "raison": "HORODATAGE_DANS_LE_FUTUR", "age_ms": age})
        elif age > age_max_ms:
            exclues.append({"venue": q.venue, "raison": "VENUE_PERIMEE", "age_ms": age})
        else:
            vivantes.append(q)
    return vivantes, exclues


# ════════════════════════════ NBBO directionnel ════════════════════════════
def nbbo_directionnel(quotes: Sequence[QuoteVenue], *, now_ms: float,
                      age_max_ms: float = AGE_MAX_MS_DEFAUT) -> dict[str, Any]:
    """Route d'achat (meilleur ASK) et route de vente (meilleur BID), séparées. Aucun mid n'est produit."""
    vivantes, exclues = venues_fraiches(quotes, now_ms=now_ms, age_max_ms=age_max_ms)
    base: dict[str, Any] = {"venues_exclues": exclues, "n_venues_vivantes": len(vivantes),
                            "buy_route": None, "sell_route": None}
    if not vivantes:
        return {**base, "statut": "AUCUNE_VENUE_FRAICHE"}
    actifs = {q.actif for q in vivantes}
    if len(actifs) > 1:
        return {**base, "statut": "ACTIFS_MELANGES", "raison": "un NBBO ne se calcule que sur un actif canonique"}
    actif = actifs.pop()

    meilleur_ask = min(vivantes, key=lambda q: q.ask)
    meilleur_bid = max(vivantes, key=lambda q: q.bid)
    return {**base, "statut": "OK", "actif": actif,
            "buy_route": Route(meilleur_ask.venue, actif, VenueAction.BUY, meilleur_ask.ask, meilleur_ask.ask_size),
            "sell_route": Route(meilleur_bid.venue, actif, VenueAction.SELL, meilleur_bid.bid, meilleur_bid.bid_size)}


def _direction_hl_binance(venue_achat: str, venue_vente: str) -> CrossVenueDirection | None:
    """Traduit deux venues dans le contrat de sens du bloc 2 quand il s'agit de HL et Binance."""
    if venue_achat == "HL" and venue_vente == "BINANCE":
        return BUY_HL_SELL_BINANCE
    if venue_achat == "BINANCE" and venue_vente == "HL":
        return SELL_HL_BUY_BINANCE
    return None


def opportunite_executable(nbbo: Mapping[str, Any], *, cout_ar_bps: float = 0.0) -> dict[str, Any]:
    """Opportunité SEULEMENT sur un croisement exécutable entre DEUX venues distinctes.

    Un écart de mid, même énorme, ne produit jamais d'opportunité : il ne se traduit par aucune paire
    d'ordres exécutables.
    """
    if nbbo.get("statut") != "OK":
        return {"statut": "DONNEES_INSUFFISANTES", "raison": nbbo.get("statut"), "executable": False}
    achat: Route = nbbo["buy_route"]
    vente: Route = nbbo["sell_route"]
    if achat.venue == vente.venue:
        return {"statut": "AUCUN_CROISEMENT_INTER_VENUES", "executable": False,
                "raison": "meilleur bid et meilleur ask sur la meme venue : ce serait franchir son propre spread"}
    if vente.prix <= achat.prix:
        return {"statut": "AUCUN_CROISEMENT", "executable": False,
                "ecart_bps": round((vente.prix - achat.prix) / achat.prix * 1e4, 4),
                "raison": "pas de croisement executable ; un ecart de mid n'est pas un arbitrage"}

    ecart_bps = (vente.prix - achat.prix) / achat.prix * 1e4
    net_bps = ecart_bps - float(cout_ar_bps)
    taille = min(achat.taille, vente.taille)
    return {
        "statut": "EXECUTABLE" if net_bps > 0 else "NON_RENTABLE_APRES_COUTS",
        "executable": bool(net_bps > 0 and taille > 0),
        "actif": nbbo.get("actif"),
        "buy_route": achat.as_dict(), "sell_route": vente.as_dict(),
        "ecart_bps": round(ecart_bps, 4), "cout_ar_bps": float(cout_ar_bps), "net_bps": round(net_bps, 4),
        "taille_appariee": taille,
        "taille_bornee_par": achat.venue if achat.taille <= vente.taille else vente.venue,
        "direction_hl_binance": (
            d.as_dict() if (d := _direction_hl_binance(achat.venue, vente.venue)) is not None else None
        ),
        "real_execution": False,
    }


__all__ = [
    "MAPPING_VERSION", "MAPPING_DEFAUT", "AGE_MAX_MS_DEFAUT", "QuoteVenue", "Route",
    "hash_mapping", "actif_canonique", "quarantaine_mapping", "normaliser", "venues_fraiches",
    "nbbo_directionnel", "opportunite_executable",
]
