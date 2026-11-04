from __future__ import annotations

import json

from hl_observer.backtesting.copy_vault_causal_selection import cluster_metaorders
from hl_observer.backtesting.copy_vault_book_loader import load_observed_books
from hl_observer.backtesting.copy_vault_executable import execute_metaorder


def _entry() -> dict[str, object]:
    return {
        "event_id": "future-book-entry",
        "ts_ms": 1_000,
        "coin": "BTC",
        "direction": 1,
        "action": "OPEN",
        "dir": "Open Long",
        "vault": "0xA",
        "taille_usd": 100.0,
        "move_frac": 0.01,
    }


def _book(ts_ms: int) -> dict[str, object]:
    return {
        "ts_ms": ts_ms,
        "bid": 99.0,
        "ask": 101.0,
        "capacity_usd": 1_000.0,
        "bids5": [[99.0, 20.0]],
        "asks5": [[101.0, 20.0]],
        "causal_observation": True,
    }


def test_un_book_recu_apres_le_signal_ne_devient_pas_la_reference():
    metaorder = cluster_metaorders([_entry()])[0][0]

    trade, reason = execute_metaorder(
        metaorder,
        [_book(1_001), _book(61_000), _book(361_000)],
        horizon_ms=300_000,
    )

    assert trade is None
    assert reason == "STALE_OR_MISSING_REFERENCE_BOOK"


def test_loader_applique_le_cutoff_de_reception_avant_de_rendre_les_books_visibles(tmp_path):
    data_dir = tmp_path / "runtime" / "data"
    data_dir.mkdir(parents=True)
    observed = data_dir / "carnet_venues.jsonl"
    observed.write_text(
        "\n".join(
            json.dumps(
                {
                    "coin": "BTC",
                    "collecte_ts": timestamp,
                    "hl_bid": 99.0,
                    "hl_ask": 101.0,
                    "taille_min_usd": 1_000.0,
                }
            )
            for timestamp in (1.000, 2.000)
        )
        + "\n",
        encoding="utf-8",
    )

    books, audit = load_observed_books(tmp_path, as_of_ms=1_000)

    assert [row["ts_ms"] for row in books["BTC"]] == [1_000]
    assert audit["as_of_ms"] == 1_000
    assert audit["future_rows_rejected"] == 1
