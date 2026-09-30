"""
Tests du parser Full Node Streaming (firehose tous fills + adresses).

100% pur, déterministe, sans réseau ni node. READ-ONLY / PAPER-ONLY.
"""

from __future__ import annotations

from hyper_smart_observer.dydx_v4.full_node_stream import (
    StreamedFill,
    parse_stream_fill,
    parse_stream_response,
)

CLOB_MAP = {0: "BTC-USD", 1: "ETH-USD"}


def _fill_camel():
    return {
        "orders": [
            {"orderId": {"subaccountId": {"owner": "dydx1abc", "number": 0}, "clobPairId": 0},
             "side": "SIDE_BUY", "subticks": "1000000"},
            {"orderId": {"subaccountId": {"owner": "dydx1xyz", "number": 1}, "clobPairId": 1},
             "side": 2, "subticks": "2000000"},
        ],
        "fillAmounts": ["500", "1000"],
    }


def test_parse_fill_extracts_owner_market_side():
    fills = parse_stream_fill(_fill_camel(), CLOB_MAP, block_height=123)
    assert len(fills) == 2
    a, b = fills
    assert a.owner == "dydx1abc" and a.market == "BTC-USD" and a.side == "BUY"
    assert a.cum_fill_quantums == 500 and a.block_height == 123
    assert b.owner == "dydx1xyz" and b.market == "ETH-USD" and b.side == "SELL"
    assert b.subaccount_number == 1


def test_parse_fill_tolerates_snake_case():
    fill = {
        "orders": [
            {"order_id": {"subaccount_id": {"owner": "dydx1snake", "number": 0}, "clob_pair_id": 1},
             "side": 1, "subticks": 999},
        ],
        "fill_amounts": [42],
    }
    fills = parse_stream_fill(fill, CLOB_MAP)
    assert len(fills) == 1
    assert fills[0].owner == "dydx1snake" and fills[0].market == "ETH-USD"
    assert fills[0].side == "BUY" and fills[0].cum_fill_quantums == 42


def test_parse_fill_skips_orders_without_owner():
    fill = {"orders": [{"orderId": {"subaccountId": {"number": 0}, "clobPairId": 0}, "side": 1}],
            "fillAmounts": [10]}
    assert parse_stream_fill(fill, CLOB_MAP) == []


def test_parse_response_filters_finalized_and_order_fill():
    resp = {
        "updates": [
            {"orderFill": _fill_camel(), "execMode": 7, "blockHeight": 100},   # gardé
            {"orderFill": _fill_camel(), "execMode": 0},                       # rejeté (non finalisé)
            {"orderbookUpdate": {"snapshot": True}, "execMode": 7},            # pas un fill → ignoré
        ]
    }
    fills = parse_stream_response(resp, CLOB_MAP, only_finalized=True)
    assert len(fills) == 2  # seul l'unique order_fill finalisé compte
    assert {f.owner for f in fills} == {"dydx1abc", "dydx1xyz"}


def test_parse_response_can_include_optimistic():
    resp = {"updates": [{"orderFill": _fill_camel(), "execMode": 0}]}
    assert parse_stream_response(resp, CLOB_MAP, only_finalized=False)  # non vide


def test_streamed_fill_is_read_only_dataclass():
    f = StreamedFill(owner="dydx1a", subaccount_number=0, clob_pair_id=0, market="BTC-USD",
                     side="BUY", subticks=1, cum_fill_quantums=1)
    # Pas de méthode d'ordre/signature
    forbidden = ("order", "sign", "submit", "place", "withdraw", "deposit", "buy", "sell")
    for name in [n for n in dir(f) if not n.startswith("_")]:
        assert not any(tok in name.lower() for tok in forbidden), name
