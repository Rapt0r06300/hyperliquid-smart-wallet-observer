from __future__ import annotations

import gzip
import json
from pathlib import Path

from hl_observer.backtesting.lead_lag_source_alignment import (
    discover_market_tick_windows,
    load_aligned_binance_trade_tape,
    select_aligned_bbo_sources,
)


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _bbo_row(ts_ms: int, *, coin: str = "ETH", event_id: str = "trade") -> dict:
    return {
        "event_id": event_id,
        "venue": "BIN_TRADE",
        "coin": coin,
        "ts_wall_ms": ts_ms,
        "px": 100.0,
        "sz": 0.5,
        "side": "BUY",
    }


def test_selection_retient_uniquement_les_shards_chevauchant_le_marche(tmp_path: Path) -> None:
    target = 1_786_552_000_000
    ticks = tmp_path / "runtime" / "data" / "market_ticks"
    _write(
        ticks / f"hyperliquid_market_ticks.{target}-{target + 999}.1.jsonl.gz",
        [{"received_ts_ms": target, "written_ts_ms": target + 1}],
    )
    old_end = target - 10_000
    old = tmp_path / "runtime" / "data" / "bbo_shards" / f"bbo_tape_{old_end * 1_000_000}.jsonl.gz"
    aligned_end = target + 800
    aligned = tmp_path / "runtime" / "data" / "bbo_shards_archive" / f"bbo_tape_{aligned_end * 1_000_000}.jsonl.gz"
    _write(old, [_bbo_row(target - 20_000, event_id="old")])
    _write(aligned, [_bbo_row(target + 10, event_id="aligned")])

    selected, meta = select_aligned_bbo_sources(tmp_path)

    assert selected == [aligned.resolve()]
    assert meta["candidate_sources"] == 2
    assert meta["selected_sources"] == 1
    assert meta["selection_policy"].startswith("BBO_WALL_WINDOW_INTERSECTS")
    assert meta["real_execution"] is False


def test_chargeur_filtre_coin_fenetre_et_doublons(tmp_path: Path) -> None:
    target = 1_786_552_000_000
    ticks = tmp_path / "runtime" / "data" / "market_ticks"
    _write(
        ticks / f"hyperliquid_market_ticks.{target}-{target + 100}.1.jsonl.gz",
        [{"received_ts_ms": target, "written_ts_ms": target + 1}],
    )
    source = tmp_path / "runtime" / "data" / "bbo_shards" / f"bbo_tape_{(target + 500) * 1_000_000}.jsonl.gz"
    duplicate = _bbo_row(target + 20, event_id="same")
    _write(
        source,
        [
            _bbo_row(target - 1, event_id="before"),
            duplicate,
            duplicate,
            _bbo_row(target + 30, coin="BTC", event_id="btc"),
            _bbo_row(target + 101, event_id="after"),
        ],
    )

    windows = discover_market_tick_windows(tmp_path)
    tape, meta = load_aligned_binance_trade_tape(
        tmp_path,
        [source],
        market_windows=windows,
    )

    assert tape["ETH"]["TRADE"] == [(int(target + 20) * 1_000_000, 100.0, 1.0)]
    assert meta["lead_trades"] == 1
    assert meta["duplicates_rejected"] == 1
    assert meta["rows_outside_execution_windows"] == 2
    assert meta["stopped_reason"] == "COMPLETED"


def test_absence_de_fenetre_refuse_honnetement_le_replay(tmp_path: Path) -> None:
    source = tmp_path / "runtime" / "data" / "bbo_tape.jsonl"
    _write(source, [_bbo_row(1_786_552_000_000)])

    tape, meta = load_aligned_binance_trade_tape(tmp_path, [source])

    assert tape["ETH"]["TRADE"] == []
    assert meta["stopped_reason"] == "NO_MARKET_WINDOWS"
    assert meta["real_execution"] is False
