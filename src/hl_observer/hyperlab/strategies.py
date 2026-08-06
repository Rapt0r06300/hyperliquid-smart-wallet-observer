"""[Bloc 38-39/44-45 / AUD-065,066,067,070,075] Les 3 familles ACTIVES -> PaperIntent, sur donnees
canoniques. Copy-Vault (miroir de l'action leader), Lead-Lag (OFI + microprice depuis L1), Cross-Venue
(divergence de mid -> 2 jambes au meme instant). Carry reste DISABLED_BY_SCOPE (absent ici).
Chaque strategie retourne une liste de PaperIntent (vide si pas de signal). deterministe, 0 reseau."""
from __future__ import annotations

from typing import Mapping, Optional

from .paper_engine import PaperIntent

FAMILLES_ACTIVES = ("copy_vault", "lead_lag", "cross_venue")


def microprice(best_bid: float, bid_sz: float, best_ask: float, ask_sz: float) -> Optional[float]:
    tot = (bid_sz or 0) + (ask_sz or 0)
    if tot <= 0:
        return None
    return (best_bid * ask_sz + best_ask * bid_sz) / tot


def ofi(prev: Mapping, cur: Mapping) -> float:
    """Order Flow Imbalance (Cont) depuis L1 : variation nette de pression bid - ask."""
    d = 0.0
    if cur["bid"] > prev["bid"]:
        d += cur["bid_sz"]
    elif cur["bid"] < prev["bid"]:
        d -= prev["bid_sz"]
    else:
        d += cur["bid_sz"] - prev["bid_sz"]
    if cur["ask"] < prev["ask"]:
        d -= cur["ask_sz"]
    elif cur["ask"] > prev["ask"]:
        d += prev["ask_sz"]
    else:
        d -= cur["ask_sz"] - prev["ask_sz"]
    return d


class CopyVault:
    def generer_intents(self, action: Mapping, *, notionnel_usd: float, ts: float) -> list:
        """action = {venue, symbole, side, prix_ref, poids?}. Miroir de l'action du leader (AUD-075)."""
        if action.get("side") not in ("buy", "sell"):
            return []
        n = notionnel_usd * float(action.get("poids", 1.0))
        return [PaperIntent("copy_vault", action["venue"], action["symbole"], action["side"],
                            n, action["prix_ref"], ts)]


class LeadLag:
    def generer_intents(self, l1_prev: Mapping, l1_cur: Mapping, *, venue: str, symbole: str,
                        notionnel_usd: float, ts: float, seuil: float = 0.0) -> list:
        of = ofi(l1_prev, l1_cur)
        mp = microprice(l1_cur["bid"], l1_cur["bid_sz"], l1_cur["ask"], l1_cur["ask_sz"])
        if mp is None or abs(of) <= seuil:
            return []
        side = "buy" if of > 0 else "sell"
        return [PaperIntent("lead_lag", venue, symbole, side, notionnel_usd, mp, ts)]


class CrossVenue:
    def generer_intents(self, mid_a: Optional[float], mid_b: Optional[float], *, venue_a: str,
                        venue_b: str, symbole: str, notionnel_usd: float, ts: float,
                        seuil_bps: float = 5.0) -> list:
        """2 jambes au MEME instant : long la venue la moins chere, short la plus chere (AUD-070)."""
        if mid_a is None or mid_b is None:
            return []
        mid = (mid_a + mid_b) / 2.0
        if mid <= 0:
            return []
        ecart_bps = (mid_a - mid_b) / mid * 1e4
        if abs(ecart_bps) < seuil_bps:
            return []
        if mid_a < mid_b:
            return [PaperIntent("cross_venue", venue_a, symbole, "buy", notionnel_usd, mid_a, ts),
                    PaperIntent("cross_venue", venue_b, symbole, "sell", notionnel_usd, mid_b, ts)]
        return [PaperIntent("cross_venue", venue_b, symbole, "buy", notionnel_usd, mid_b, ts),
                PaperIntent("cross_venue", venue_a, symbole, "sell", notionnel_usd, mid_a, ts)]
