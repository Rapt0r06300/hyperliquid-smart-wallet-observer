"""Compare les prix de plusieurs sources en lecture seule -- SUR DES PRIX EXECUTABLES.

Q2 (2026-07-13). Ce comparateur classait les venues par MID (`min(values, key=mid)`) et rendait
l'ecart de mid. Deux consequences, la seconde bien pire que la premiere :

1. L'ecart annonce n'etait pas encaissable (surestime de `(spread_A + spread_B)/2`).

2. **Il pouvait designer la MAUVAISE venue comme « la moins chere ».** Le mid le plus bas
   n'est pas l'ask le plus bas. Une venue au mid serre mais au spread large peut avoir un ASK
   plus haut qu'une venue au mid plus eleve mais au spread etroit. On achete a l'ask -- pas au
   mid. Classer par mid, c'est classer sur un prix qu'on ne paye pas.

On garde `low_mid` / `high_mid` / `spread_bps` (diagnostic, compatibilite descendante) et on
ajoute ce qui compte : le sens EXECUTABLE et son edge reel.

Module PUR. Lecture seule. Aucun ordre.
"""

from __future__ import annotations

from dataclasses import dataclass

from hl_observer.arbitrage.executable_legs import (
    edge_mid_bps,
    edge_top_of_book_bps,
    surestimation_du_mid_bps,
)


@dataclass(frozen=True, slots=True)
class CrossSourcePrice:
    source: str
    coin: str
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (float(self.bid) + float(self.ask)) / 2.0

    @property
    def spread_bps(self) -> float:
        m = self.mid
        if m <= 0.0:
            return 0.0
        return (float(self.ask) - float(self.bid)) / m * 10_000.0


@dataclass(frozen=True, slots=True)
class CrossSourceDiscrepancy:
    coin: str
    low_source: str
    high_source: str
    low_mid: float
    high_mid: float
    spread_bps: float                       # DIAGNOSTIC : ecart de MID. Inexecutable.
    # --- Q2 : ce qu'on peut REELLEMENT prendre -------------------------------
    source_achat: str = ""                  # on paye SON ask
    source_vente: str = ""                  # on encaisse SON bid
    prix_achat: float = 0.0
    prix_vente: float = 0.0
    edge_executable_bps: float = 0.0
    surestimation_du_mid_bps: float = 0.0
    executable: bool = False                # edge_executable_bps > 0 (AVANT frais)


def compare_cross_source_prices(prices: list[CrossSourcePrice]) -> list[CrossSourceDiscrepancy]:
    by_coin: dict[str, list[CrossSourcePrice]] = {}
    for price in prices:
        if price.bid > 0 and price.ask > 0 and price.ask >= price.bid:
            by_coin.setdefault(price.coin.upper(), []).append(price)

    rows: list[CrossSourceDiscrepancy] = []
    for coin, values in by_coin.items():
        if len(values) < 2:
            continue

        # DIAGNOSTIC (mid) -- conserve pour ne rien casser en aval.
        low = min(values, key=lambda item: item.mid)
        high = max(values, key=lambda item: item.mid)
        if low.source == high.source or low.mid <= 0:
            continue
        spread_mid = edge_mid_bps(a_bid=low.bid, a_ask=low.ask, b_bid=high.bid, b_ask=high.ask)

        # EXECUTABLE : on achete a l'ASK le plus bas, on vend au BID le plus haut. Ce ne sont
        # PAS forcement les venues designees par le mid.
        moins_cher = min(values, key=lambda item: float(item.ask))    # ou l'on ACHETE
        mieux_paye = max(values, key=lambda item: float(item.bid))    # ou l'on VEND

        ref = (float(moins_cher.ask) + float(mieux_paye.bid)) / 2.0
        edge = edge_top_of_book_bps(
            a_ask=float(moins_cher.ask), b_bid=float(mieux_paye.bid), reference=ref
        )

        # Si le meilleur ask ET le meilleur bid sont sur la MEME venue, il n'y a pas d'arbitrage
        # cross-source : on paierait juste le spread de cette venue. On le DIT (edge negatif,
        # venues nommees) plutot que de le cacher derriere des champs vides -- car « les deux
        # jambes tombent au meme endroit » EST le resultat, et il doit etre lisible.
        meme_venue = moins_cher.source == mieux_paye.source

        surest = surestimation_du_mid_bps(
            a_bid=low.bid, a_ask=low.ask, b_bid=high.bid, b_ask=high.ask
        )

        rows.append(
            CrossSourceDiscrepancy(
                coin=coin,
                low_source=low.source,
                high_source=high.source,
                low_mid=round(low.mid, 10),
                high_mid=round(high.mid, 10),
                spread_bps=round(spread_mid, 8),
                source_achat=moins_cher.source,
                source_vente=mieux_paye.source,
                prix_achat=round(float(moins_cher.ask), 10),
                prix_vente=round(float(mieux_paye.bid), 10),
                edge_executable_bps=round(edge, 8),
                surestimation_du_mid_bps=round(surest, 8),
                executable=(edge > 0.0) and not meme_venue,
            )
        )

    # Trie sur l'edge REELLEMENT prenable -- pas sur le mirage.
    return sorted(rows, key=lambda row: row.edge_executable_bps, reverse=True)


__all__ = ["CrossSourceDiscrepancy", "CrossSourcePrice", "compare_cross_source_prices"]
