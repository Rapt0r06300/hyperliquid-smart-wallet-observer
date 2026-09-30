from types import SimpleNamespace

from hl_observer.scoring.leader_realized_history import round_trip_moves
from hl_observer.scoring.shortlist_quality_filter import filter_to_qualified, qualified_wallets


def _d(wallet, coin, side, action, price):
    return {"wallet": wallet, "coin": coin, "side": side, "action": action, "price": price}


def test_round_trip_moves_long_and_short():
    deltas = [
        _d("0xA", "BTC", "LONG", "OPEN_LONG", 100.0),
        _d("0xA", "BTC", "LONG", "CLOSE_LONG", 110.0),   # +1000 bps
        _d("0xB", "SOL", "SHORT", "OPEN_SHORT", 200.0),
        _d("0xB", "SOL", "SHORT", "CLOSE_SHORT", 180.0),  # prix baisse -> +1000 bps short
        _d("0xC", "ETH", "LONG", "OPEN_LONG", 50.0),      # jamais fermé -> ignoré
    ]
    m = round_trip_moves(deltas)
    assert round(m["0xA"][0]) == 1000
    assert round(m["0xB"][0]) == 1000
    assert "0xC" not in m


def test_filter_keeps_only_qualified_when_history_exists():
    rows = [SimpleNamespace(wallet_address=w) for w in ("0xGOOD", "0xBAD", "0xMEH")]
    moves = {
        "0xGOOD": [30, 25, 40, 35, 28],          # winrate 100%, edge fort -> qualifie
        "0xBAD": [-20, -30, 10, -25, -40, -15],  # perdant -> rejeté
        "0xMEH": [2, -3, 4, -2, 3],              # winrate ok mais move < coûts -> rejeté
    }
    kept, qual = filter_to_qualified(rows, moves)
    assert qual == {"0xGOOD"}
    assert [r.wallet_address for r in kept] == ["0xGOOD"]


def test_warmup_does_not_freeze_shortlist():
    rows = [SimpleNamespace(wallet_address=w) for w in ("0xA", "0xB")]
    moves = {"0xA": [50, 60], "0xB": []}   # trop peu d'historique -> personne qualifié
    kept, qual = filter_to_qualified(rows, moves)
    assert qual == set()
    assert len(kept) == 2   # ne gèle pas: on garde tout pendant le warmup
