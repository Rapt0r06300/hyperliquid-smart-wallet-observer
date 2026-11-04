from __future__ import annotations

import pytest

from hl_observer.backtesting.copy_vault_causal_selection import (
    confirmed_causal_l2_observation,
    select_causal_protocol_inputs,
)


def _metaorder(signal_ts_ms: int, name: str) -> dict[str, object]:
    return {
        "causal_forward_eligible": True,
        "signal_source": "LIVE_WS",
        "signal_ts_ms": signal_ts_ms,
        "metaorder_id": name,
        "coin": "BTC",
    }


def test_cutoff_rejete_signaux_et_books_futurs():
    selected, books, audit = select_causal_protocol_inputs(
        [_metaorder(1_000, "past"), _metaorder(3_000, "future")],
        {"BTC": [
            {"causal_observation": True, "ts_ms": 1_500},
            {"causal_observation": True, "ts_ms": 3_500},
        ]},
        cutoff_ms=2_000,
    )

    assert [row["metaorder_id"] for row in selected] == ["past"]
    assert [row["ts_ms"] for row in books["BTC"]] == [1_500]
    assert audit["cutoff_ms"] == 2_000
    assert audit["post_cutoff_metaorders_rejected"] == 1
    assert audit["post_cutoff_book_rows_rejected"] == 1


@pytest.mark.parametrize("cutoff", [True, 0, -1, 1.5, "future"])
def test_cutoff_ambigu_refuse(cutoff: object):
    with pytest.raises(ValueError):
        select_causal_protocol_inputs([], {}, cutoff_ms=cutoff)  # type: ignore[arg-type]


def test_entree_l2_confirmee_exige_provenance_safe_et_niveaux():
    confirmed = {
        "causal_observation": True,
        "source": "HYPERLIQUID_L2_WS",
        "data_origin": "REAL_OBSERVED",
        "exchange_ts_ms": 2_000,
        "received_at_ms": 2_010,
        "bids5": [[100.0, 2.0]],
        "asks5": [[102.0, 2.0]],
        "source_quality_status": "SAFE",
        "source_manifest_verified": True,
        "source_replay_compatible": True,
        "ts_ms": 2_010,
    }
    incomplete = {**confirmed, "source_quality_status": "UNAVAILABLE"}

    assert confirmed_causal_l2_observation(confirmed) is True
    assert confirmed_causal_l2_observation(incomplete) is False
    _selected, books, audit = select_causal_protocol_inputs(
        [_metaorder(2_100, "signal")],
        {"BTC": [confirmed, incomplete]},
        require_confirmed_l2=True,
    )

    assert [row["ts_ms"] for row in books["BTC"]] == [2_010]
    assert audit["require_confirmed_l2"] is True
    assert audit["unconfirmed_causal_book_rows_rejected"] == 1
