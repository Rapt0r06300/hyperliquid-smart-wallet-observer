from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from hl_observer.scoring.leader_realized_history import round_trip_moves, wallet_round_trip_moves_from_session
from hl_observer.scoring.shortlist_quality_filter import filter_to_qualified
from hl_observer.storage.models import PositionDeltaModel


def _d(wallet, coin, action, previous_size, new_size, price, timestamp):
    return {
        "wallet": wallet,
        "coin": coin,
        "action": action,
        "previous_size": previous_size,
        "new_size": new_size,
        "fill_size": abs(new_size - previous_size),
        "price": price,
        "exchange_ts": timestamp,
        "event_identity": f"{wallet}:{coin}:{timestamp}",
        "source": "user_fills",
        "confidence_score": 1.0,
        "is_paper_eligible": True,
    }


def test_round_trip_moves_long_and_short():
    deltas = [
        _d("0xA", "BTC", "OPEN", 0.0, 1.0, 100.0, 1),
        _d("0xA", "BTC", "CLOSE", 1.0, 0.0, 110.0, 2),   # +1000 bps
        _d("0xB", "SOL", "OPEN", 0.0, -2.0, 200.0, 3),
        _d("0xB", "SOL", "CLOSE", -2.0, 0.0, 180.0, 4),  # prix baisse -> +1000 bps short
        _d("0xC", "ETH", "OPEN", 0.0, 1.0, 50.0, 5),      # jamais fermé -> ignoré
    ]
    m = round_trip_moves(deltas)
    assert round(m["0xa"][0]) == 1000
    assert round(m["0xb"][0]) == 1000
    assert "0xc" not in m


def test_round_trip_moves_weights_adds_and_partial_closes():
    deltas = [
        _d("0xA", "BTC", "OPEN", 0.0, 1.0, 100.0, 1),
        _d("0xA", "BTC", "ADD", 1.0, 2.0, 120.0, 2),
        _d("0xA", "BTC", "REDUCE", 2.0, 1.0, 130.0, 3),
        _d("0xA", "BTC", "CLOSE", 1.0, 0.0, 120.0, 4),
    ]

    moves = round_trip_moves(deltas)

    # Basis = 100 + 120; realized gross PnL = 20 + 10.
    assert moves["0xa"] == [30 / 220 * 10_000]


def test_round_trip_moves_ignores_unverified_duplicate_and_incomplete_events():
    opening = _d("0xA", "BTC", "OPEN", 0.0, 1.0, 100.0, 1)
    close = _d("0xA", "BTC", "CLOSE", 1.0, 0.0, 120.0, 2)
    duplicate = dict(close)
    later_unverified = _d("0xA", "BTC", "OPEN", 0.0, 1.0, 121.0, 3)
    later_unverified["is_paper_eligible"] = False
    rows = [
        opening,
        duplicate,
        later_unverified,
        _d("0xB", "ETH", "OPEN", 0.0, 1.0, 50.0, 3),
        {**_d("0xB", "ETH", "CLOSE", 1.0, 0.0, 60.0, 4), "event_identity": None},
    ]

    moves = round_trip_moves(rows)

    assert moves["0xa"] == [2000.0]
    assert "0xb" not in moves


def test_round_trip_moves_rejects_cycle_after_bad_transition():
    opening = _d("0xA", "BTC", "OPEN", 0.0, 1.0, 100.0, 1)
    invalid_reduce = _d("0xA", "BTC", "REDUCE", 1.0, 0.5, 110.0, 2)
    invalid_reduce["fill_size"] = 0.25
    close = _d("0xA", "BTC", "CLOSE", 1.0, 0.0, 120.0, 3)

    assert round_trip_moves([opening, invalid_reduce, close]) == {}


def test_round_trip_moves_rejects_same_timestamp_without_persisted_order():
    opening = _d("0xA", "BTC", "OPEN", 0.0, 1.0, 100.0, 1)
    reduction = _d("0xA", "BTC", "REDUCE", 1.0, 0.5, 110.0, 2)
    reduction["event_identity"] = "a-reduction"
    closing = _d("0xA", "BTC", "CLOSE", 0.5, 0.0, 110.0, 2)
    closing["event_identity"] = "b-close"

    assert round_trip_moves([opening, reduction, closing]) == {}

    reduction["source_sequence"] = 10
    closing["source_sequence"] = 11
    assert round_trip_moves([opening, closing, reduction])["0xa"] == [1000.0]


def test_session_loader_uses_persisted_order_for_same_timestamp_fills():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    PositionDeltaModel.__table__.create(engine)
    with Session(engine) as session:
        rows = (
            (1, 0.0, 1.0, 100.0, "OPEN"),
            (2, 1.0, 0.5, 110.0, "REDUCE"),
            (2, 0.5, 0.0, 110.0, "CLOSE"),
        )
        for timestamp, previous, new, price, action in rows:
            session.add(
                PositionDeltaModel(
                    wallet_address="0xA",
                    coin="BTC",
                    previous_size=previous,
                    current_size=new,
                    new_size=new,
                    delta_size=new - previous,
                    action=action,
                    exchange_ts=timestamp,
                    price=price,
                    fill_size=abs(new - previous),
                    confidence_score=0.95,
                    is_paper_eligible=True,
                    source="user_fills",
                    delta_hash=f"ordered-{timestamp}-{previous}-{new}",
                )
            )
        session.commit()
        assert wallet_round_trip_moves_from_session(session, ["0xA"]) == {
            "0xa": [1000.0]
        }
    engine.dispose()


def test_round_trip_moves_accepts_snapshot_only_with_fill_proofs():
    opening = _d("0xA", "BTC", "OPEN", 0.0, 1.0, 100.0, 1)
    close = _d("0xA", "BTC", "CLOSE", 1.0, 0.0, 110.0, 2)
    proof = {
        "has_fills": True,
        "size_match": True,
        "temporal_consistency": True,
        "price_from_fill": True,
    }
    rows = [
        {**opening, "source": "snapshot", "proofs": proof},
        {**close, "source": "snapshot", "proofs": proof},
    ]

    assert round_trip_moves(rows)["0xa"] == [1000.0]
    rows[1]["proofs"] = {**proof, "size_match": False}
    assert round_trip_moves(rows) == {}


def test_session_loader_reads_latest_rows_in_exchange_order():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    PositionDeltaModel.__table__.create(engine)
    with Session(engine) as session:
        for timestamp, previous, new, price in (
            (1, 0.0, 1.0, 100.0),
            (2, 1.0, 0.0, 90.0),
            (3, 0.0, -1.0, 100.0),
            (4, -1.0, 0.0, 90.0),
        ):
            session.add(
                PositionDeltaModel(
                    wallet_address="0xA",
                    coin="BTC",
                    previous_size=previous,
                    current_size=new,
                    new_size=new,
                    delta_size=new - previous,
                    action="OPEN" if previous == 0.0 else "CLOSE",
                    exchange_ts=timestamp,
                    fill_id=timestamp,
                    price=price,
                    fill_size=abs(new - previous),
                    confidence_score=0.95,
                    is_paper_eligible=True,
                    source="hyperliquid_ws:userFills:stream",
                    delta_hash=f"delta-{timestamp}",
                )
            )
        session.commit()

        assert wallet_round_trip_moves_from_session(session, ["0xA"], max_rows=2) == {"0xa": [1000.0]}

    engine.dispose()


def test_session_loader_shares_global_budget_across_wallets():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    PositionDeltaModel.__table__.create(engine)
    with Session(engine) as session:
        events = [
            ("0xB", 1, 0.0, 1.0, 100.0, "OPEN"),
            ("0xB", 2, 1.0, 0.0, 110.0, "CLOSE"),
        ]
        for timestamp in range(10, 18, 2):
            events.extend(
                [
                    ("0xA", timestamp, 0.0, 1.0, 100.0, "OPEN"),
                    ("0xA", timestamp + 1, 1.0, 0.0, 110.0, "CLOSE"),
                ]
            )
        for wallet, timestamp, previous, new, price, action in events:
            session.add(
                PositionDeltaModel(
                    wallet_address=wallet,
                    coin="BTC",
                    previous_size=previous,
                    current_size=new,
                    new_size=new,
                    delta_size=new - previous,
                    action=action,
                    exchange_ts=timestamp,
                    fill_id=timestamp,
                    price=price,
                    fill_size=abs(new - previous),
                    confidence_score=0.95,
                    is_paper_eligible=True,
                    source="hyperliquid_ws:userFills:stream",
                    delta_hash=f"{wallet}-{timestamp}",
                )
            )
        session.commit()

        moves = wallet_round_trip_moves_from_session(session, ["0xA", "0xB"], max_rows=4)

    assert moves == {"0xb": [1000.0], "0xa": [1000.0]}
    engine.dispose()


def test_filter_keeps_only_qualified_when_history_exists():
    rows = [SimpleNamespace(wallet_address=w) for w in ("0xGOOD", "0xBAD", "0xMEH")]
    moves = {
        "0xGOOD": [30, 25, 40, 35, 28] * 4,      # 20 cycles, edge net prudent -> qualifie
        "0xBAD": [-20, -30, 10, -25, -40, -15],  # perdant -> rejeté
        "0xMEH": [2, -3, 4, -2, 3],              # winrate ok mais move < coûts -> rejeté
    }
    kept, qual = filter_to_qualified(rows, moves)
    assert qual == {"0xgood"}
    assert [r.wallet_address for r in kept] == ["0xGOOD"]


def test_warmup_keeps_observation_candidates_available():
    rows = [SimpleNamespace(wallet_address=w) for w in ("0xA", "0xB")]
    moves = {"0xA": [50, 60], "0xB": []}   # trop peu d'historique -> personne qualifié
    kept, qual = filter_to_qualified(rows, moves)
    assert qual == set()
    assert [row.wallet_address for row in kept] == ["0xA", "0xB"]
