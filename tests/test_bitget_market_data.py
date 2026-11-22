"""L'univers d'instruments Bitget : un statut ABSENT ne vaut pas << negociable >>.

MESURE DU 21/11/2026 -- inventaire des pertes et des refus manques a la collecte. Trois
bourses sur quatre partageaient le meme defaut de famille, et la version honnete existait
deja dans le depot :

    coin_universe.py:117  (OKX)     `state` absent        -> ECARTE      <- honnete
    bitget_market_data.py (ici)     `symbolStatus` absent -> "normal"    <- accepte
    bybit_market_data.py            `status` absent       -> "Trading"   <- accepte

Un marche suspendu qui entre dans l'univers consomme du quota et pollue la comparaison de
funding entre bourses avec un marche mort. Les charges reelles portent toujours le champ,
donc ce refus ne mord que si l'API change de forme : exactement le moment ou l'on veut un
refus plutot qu'une acceptation muette.
"""
from __future__ import annotations

from hl_observer.collection.bitget_market_data import parse_bitget_instruments


def test_un_symbolStatus_absent_est_refuse():
    """Le defaut `"normal"` faisait passer un statut ABSENT pour negociable.

    Precedent interne : `coin_universe.py` (OKX) ecarte un `state` absent. Les charges
    reelles du depot portent toujours `symbolStatus`.
    """
    base = {"symbol": "ETHUSDT", "baseCoin": "ETH", "quoteCoin": "USDT"}
    assert parse_bitget_instruments({"data": [dict(base, symbolStatus="normal")]}) == [("ETH", "ETHUSDT")]
    assert parse_bitget_instruments({"data": [dict(base)]}) == [], "statut absent accepte"
    assert parse_bitget_instruments({"data": [dict(base, symbolStatus="halt")]}) == []
