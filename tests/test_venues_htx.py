from __future__ import annotations

import gzip
import json

import pytest

from hl_observer.venues import htx
from hl_observer.venues._canon import ReseauRequisError


def test_htx_decodes_gzip_and_normalizes_incremental_mbp() -> None:
    payload = {
        "ch": "market.BTC-USDT.depth.size_150.high_freq",
        "ts": 1005,
        "tick": {
            "seqNum": 12,
            "prevSeqNum": 11,
            "bids": [[60000, 2]],
            "asks": [[60001, 3]],
        },
    }
    decoded = htx.decode_frame(gzip.compress(json.dumps(payload).encode()))
    book = htx.normalize_mbp(decoded)
    assert book["seq"] == 12
    assert book["prev_seq"] == 11
    assert book["bids"][0] == {"prix": 60000.0, "taille": 2.0}


def test_htx_gap_requires_resync() -> None:
    result = htx.appliquer_flux_book(
        [
            {"type": "snapshot", "tick": {"seqNum": 10, "bids": [], "asks": []}},
            {"tick": {"seqNum": 12, "prevSeqNum": 9, "bids": [], "asks": []}},
        ]
    )
    assert result["synchronise"] is False
    assert result["resyncs"][0]["raison"] == "prev_mismatch"


def test_htx_plan_is_bounded_tier_a_and_read_only() -> None:
    plan = htx.public_subscription_plan(["eth-usdt", "btc-usdt"], depth=150, max_symbols=1)
    assert plan == {
        "channels": ["market.BTC-USDT.depth.size_150.high_freq"],
        "authenticated": False,
        "read_only": True,
    }
    with pytest.raises(ValueError):
        htx.public_subscription_plan(["BTC-USDT"], depth=42)


def test_htx_live_boundary_is_honest() -> None:
    with pytest.raises(ReseauRequisError):
        htx.LiveClientHtx().souscrire("market.BTC-USDT.depth.size_150.high_freq")
