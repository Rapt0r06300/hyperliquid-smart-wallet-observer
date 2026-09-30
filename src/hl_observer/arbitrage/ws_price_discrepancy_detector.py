"""Detecte les ecarts de prix entre sources -- SUR DES PRIX EXECUTABLES.

Q2 (2026-07-13). CE DETECTEUR EST BRANCHE DANS LE MOTEUR LIVE (`strategies/fusion_runtime.py`,
`refactor_fusion/runner.py`). Il calculait son ecart **sur le mid** :

    spread = abs(a.mid - b.mid) / ... * 10_000        # <-- l'ancienne ligne 28

Deux fautes dans une seule ligne.

**1. Le mid n'est pas un prix.** On achete a l'ASK et on vend au BID. `PriceEvent` PORTE le bid
et l'ask -- le detecteur les recevait et les jetait pour en faire une moyenne inexecutable.
L'ecart de mid surestime tout arbitrage d'exactement `(spread_A + spread_B) / 2` (identite
algebrique, demontree et testee dans `arbitrage/executable_legs.py`). Deux venues a 20 bps
d'ecart de mid, avec 12 bps de spread chacune, offrent 8 bps -- pas 20.

**2. `abs()` efface le SENS.** Un arbitrage a une direction : on achete quelque part, on vend
ailleurs. La valeur absolue rend le meme chiffre dans les deux sens, donc elle « trouve » une
opportunite meme quand le seul sens realisable est perdant.

🚩 Le test historique passait parce qu'il utilisait des carnets a spread ZERO
(`PriceEvent("hl","HYPE",100,100,1)`) -- des carnets qui n'existent pas. Quand bid == ask, le
mid ne ment pas. C'est le seul cas ou l'ancien code etait juste, et c'est celui qu'on testait.

Le champ `spread_bps` conserve son ancienne semantique (ecart de MID) pour ne rien casser en
aval, mais il est desormais explicitement un **diagnostic**. Le declenchement, lui, se fait sur
`edge_executable_bps`.

Lecture seule. Aucun ordre.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from hl_observer.arbitrage.executable_legs import (
    edge_mid_bps,
    edge_top_of_book_bps,
    surestimation_du_mid_bps,
)
from hl_observer.realtime.multi_source_price_stream import PriceEvent

DECISION_EXECUTABLE = "PAPER_DISCREPANCY"
DECISION_MID_SEULEMENT = "NO_TRADE_MID_ONLY_NOT_EXECUTABLE"


@dataclass(frozen=True, slots=True)
class PriceDiscrepancy:
    coin: str
    source_a: str
    source_b: str
    spread_bps: float                      # DIAGNOSTIC : l'ecart de MID. Non encaissable.
    decision: str
    # --- Q2 : ce qu'on peut REELLEMENT prendre -------------------------------
    edge_executable_bps: float = 0.0       # acheter a l'ask du moins cher, vendre au bid de l'autre
    source_achat: str = ""
    source_vente: str = ""
    prix_achat: float = 0.0                # l'ASK qu'on paye
    prix_vente: float = 0.0                # le BID qu'on encaisse
    surestimation_du_mid_bps: float = 0.0  # = (spread_A + spread_B) / 2. Toujours >= 0.
    executable: bool = False

    @property
    def paper_only(self) -> bool:
        return True


def _paire(a: PriceEvent, b: PriceEvent, min_spread_bps: float) -> PriceDiscrepancy | None:
    a_bid, a_ask = float(a.bid), float(a.ask)
    b_bid, b_ask = float(b.bid), float(b.ask)
    if min(a_bid, a_ask, b_bid, b_ask) <= 0.0 or a_ask < a_bid or b_ask < b_bid:
        return None

    ref = (a_bid + a_ask + b_bid + b_ask) / 4.0
    if ref <= 0.0:
        return None

    # Les DEUX sens, sur des prix qu'on peut vraiment avoir. Jamais d'abs().
    ab = edge_top_of_book_bps(a_ask=a_ask, b_bid=b_bid, reference=ref)   # acheter A, vendre B
    ba = edge_top_of_book_bps(a_ask=b_ask, b_bid=a_bid, reference=ref)   # acheter B, vendre A

    if ab >= ba:
        edge, src_achat, src_vente, px_a, px_v = ab, a.source, b.source, a_ask, b_bid
        mid = edge_mid_bps(a_bid=a_bid, a_ask=a_ask, b_bid=b_bid, b_ask=b_ask)
    else:
        edge, src_achat, src_vente, px_a, px_v = ba, b.source, a.source, b_ask, a_bid
        mid = edge_mid_bps(a_bid=b_bid, a_ask=b_ask, b_bid=a_bid, b_ask=a_ask)

    surest = surestimation_du_mid_bps(a_bid=a_bid, a_ask=a_ask, b_bid=b_bid, b_ask=b_ask)
    executable = edge >= float(min_spread_bps)

    # On ne remonte que ce qui a un interet : soit c'est executable, soit le mid criait
    # « opportunite » et il faut pouvoir le PROUVER (c'est la trace qui explique nos refus).
    if not executable and abs(mid) < float(min_spread_bps):
        return None

    return PriceDiscrepancy(
        coin=a.coin.upper(),
        source_a=a.source,
        source_b=b.source,
        spread_bps=round(abs(mid), 8),
        decision=DECISION_EXECUTABLE if executable else DECISION_MID_SEULEMENT,
        edge_executable_bps=round(edge, 8),
        source_achat=src_achat,
        source_vente=src_vente,
        prix_achat=round(px_a, 10),
        prix_vente=round(px_v, 10),
        surestimation_du_mid_bps=round(surest, 8),
        executable=executable,
    )


def detect_ws_price_discrepancies(
    events: Iterable[PriceEvent],
    *,
    min_spread_bps: float = 20.0,
    executables_seulement: bool = True,
) -> tuple[PriceDiscrepancy, ...]:
    """Ecarts entre sources, juges sur des prix EXECUTABLES (bid/ask), jamais sur le mid.

    `executables_seulement=True` (defaut) : on ne rend que ce qu'on pourrait vraiment prendre.
    A `False`, on rend AUSSI les « mirages du mid » (`decision=NO_TRADE_MID_ONLY_NOT_EXECUTABLE`)
    -- utile pour l'audit et le dashboard : ce sont eux qui expliquent pourquoi on refuse.
    """
    by_coin: dict[str, list[PriceEvent]] = {}
    for event in events:
        by_coin.setdefault(event.coin.upper(), []).append(event)

    out: list[PriceDiscrepancy] = []
    for _coin, rows in by_coin.items():
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                if a.source == b.source:
                    continue
                row = _paire(a, b, min_spread_bps)
                if row is None:
                    continue
                if executables_seulement and not row.executable:
                    continue
                out.append(row)
    return tuple(out)


__all__ = [
    "PriceDiscrepancy",
    "detect_ws_price_discrepancies",
    "DECISION_EXECUTABLE",
    "DECISION_MID_SEULEMENT",
]
