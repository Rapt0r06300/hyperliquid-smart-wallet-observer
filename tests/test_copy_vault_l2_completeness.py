from __future__ import annotations

import json

from hl_observer.backtesting.copy_vault_book_loader import load_observed_books


def _causal_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "schema_version": "hypersmart.copy_vault_l2.v1",
        "coin": "BTC",
        "received_at_ms": 2_010,
        "exchange_ts_ms": 2_000,
        "bid": 100.0,
        "ask": 102.0,
        "capacity_usd": 700.0,
        "source": "HYPERLIQUID_L2_WS",
        "data_origin": "REAL_OBSERVED",
        "causal_observation": True,
    }
    row.update(overrides)
    return row


def _write_tape(tmp_path, row: dict[str, object]) -> None:
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "copy_vault_l2_tape.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )


def test_causal_l2_sans_niveaux_est_rejete(tmp_path):
    _write_tape(tmp_path, _causal_row())

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert len(books["BTC"]) == 1
    assert audit["incomplete_causal_l2_rows"] == 1
    assert audit["replay_grade_ready"] is False
    assert "CAUSAL_L2_LEVELS_INCOMPLETE" in audit["replay_grade_blockers"]


def test_causal_l2_complet_reste_admissible(tmp_path):
    _write_tape(
        tmp_path,
        _causal_row(
            bids5=[[100.0, 2.0]],
            asks5=[[102.0, 2.0]],
        ),
    )

    books, audit = load_observed_books(tmp_path, coins={"BTC"})

    assert len(books["BTC"]) == 1
    assert audit["invalid_l2_structure_rows"] == 0
