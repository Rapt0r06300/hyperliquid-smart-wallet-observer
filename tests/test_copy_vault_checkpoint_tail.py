from __future__ import annotations

import json
from pathlib import Path

from hl_observer.backtesting.copy_vault_executable import (
    cluster_metaorders,
    select_observed_continuations,
)
from hl_observer.collection.copy_vault_checkpoint_tail import (
    COMPANION_PROTOCOL,
    CONTINUATION_SIGNAL_FILL_COUNT,
    COPY_DELAY_MS,
    HORIZONS_MS,
    INPUT_RELPATH,
    MAX_TARGET_LAG_MS,
    OUTPUT_RELPATH,
    STATE_RELPATH,
    CopyVaultCheckpointTail,
)
from hl_observer.collection.vault_fills_backfill import canonical_fill_id


VAULT = "0x" + "a" * 40


def _fill(
    now_ms: int,
    *,
    event: str = "one",
    direction: int = 1,
    dir_label: str | None = None,
    start_position: float = 0.0,
) -> dict:
    return {
        "vault": VAULT,
        "coin": "BTC",
        "px": 60_000.0,
        "sz": 0.01,
        "signe": direction,
        "ts_ms": now_ms - 5,
        "dir": dir_label or ("Open Long" if direction > 0 else "Open Short"),
        "start_position": start_position,
        "hash": f"0x{event}",
        "tid": event,
        "oid": event,
        "isSnapshot": False,
        "source": "LIVE_WS",
        "stable_event_id": event,
        "received_at_ms": now_ms,
    }


def test_close_et_contradiction_ne_programment_jamais_une_entree(tmp_path: Path) -> None:
    now = [900_000]
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )
    input_path = tmp_path / INPUT_RELPATH

    _append(input_path, _fill(now[0], event="close", dir_label="Close Short"))
    close_result = engine.poll_once()
    assert close_result["captured"] == 0
    assert close_result["pending"] == 0
    assert close_result["counters"]["non_entry_rejected"] == 1

    now[0] += 1_000
    _append(
        input_path,
        _fill(now[0], event="contradiction", direction=-1, dir_label="Open Long"),
    )
    contradiction_result = engine.poll_once()
    assert contradiction_result["captured"] == 0
    assert contradiction_result["pending"] == 0
    assert contradiction_result["counters"]["direction_contradictions_rejected"] == 1

    now[0] += 1_000
    _append(input_path, _fill(now[0], event="valid-open"))
    valid_result = engine.poll_once()
    assert valid_result["captured"] == 1
    assert valid_result["pending"] == 1


def _append(path: Path, payload: dict, *, newline: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(json.dumps(payload).encode("utf-8"))
        if newline:
            handle.write(b"\n")


def _book(now_ms: int) -> dict:
    return {
        "time": now_ms,
        "levels": [
            [{"px": "59999", "sz": "2"}, {"px": "59998", "sz": "3"}],
            [{"px": "60001", "sz": "2.5"}, {"px": "60002", "sz": "4"}],
        ],
    }


def test_first_start_baselines_existing_fills_without_replaying_history(tmp_path: Path) -> None:
    input_path = tmp_path / INPUT_RELPATH
    _append(input_path, _fill(1_000, event="historical"))
    now = [2_000]
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )

    result = engine.poll_once()

    assert result["lines"] == 0
    assert result["captured"] == 0
    assert not (tmp_path / OUTPUT_RELPATH).exists()
    state = json.loads((tmp_path / STATE_RELPATH).read_text(encoding="utf-8"))
    assert state["input_offset"] == input_path.stat().st_size
    assert state["protocol"] == COMPANION_PROTOCOL


def test_forward_fill_captures_reference_entry_and_real_exit_without_lookahead(
    tmp_path: Path,
) -> None:
    now = [1_000_000]
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )
    _append(tmp_path / INPUT_RELPATH, _fill(now[0]))

    first = engine.poll_once()
    assert first["captured"] == 1
    assert first["pending"] == 1

    now[0] += COPY_DELAY_MS
    entry = engine.poll_once()
    assert entry["captured"] == 1
    assert entry["pending"] == len(HORIZONS_MS)

    now[0] += HORIZONS_MS[0]
    exit_result = engine.poll_once()
    assert exit_result["captured"] == 1

    rows = [
        json.loads(line)
        for line in (tmp_path / OUTPUT_RELPATH).read_text(encoding="utf-8").splitlines()
    ]
    assert [row["checkpoint_stage"] for row in rows] == [
        "REFERENCE",
        "ENTRY",
        f"EXIT_{HORIZONS_MS[0]}",
    ]
    assert len({row["checkpoint_id"] for row in rows}) == 3
    assert all(row["source"] == "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT" for row in rows)
    assert all(row["collector_protocol"] == COMPANION_PROTOCOL for row in rows)
    assert all(row["paper_read_only"] is True and row["real_execution"] is False for row in rows)
    assert all(
        0 <= row["received_at_ms"] - row["checkpoint_target_ms"] <= MAX_TARGET_LAG_MS
        for row in rows
    )


def test_partial_duplicate_stale_and_continuation_fills_cannot_fabricate_checkpoints(
    tmp_path: Path,
) -> None:
    now = [2_000_000]
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )
    input_path = tmp_path / INPUT_RELPATH
    partial = _fill(now[0], event="partial")
    _append(input_path, partial, newline=False)
    assert engine.poll_once()["lines"] == 0

    with input_path.open("ab") as handle:
        handle.write(b"\n")
    assert engine.poll_once()["captured"] == 1
    _append(input_path, partial)
    duplicate = engine.poll_once()
    assert duplicate["captured"] == 0
    assert duplicate["counters"]["duplicates_rejected"] == 1

    now[0] += 1_000
    _append(input_path, _fill(now[0], event="continuation", start_position=0.01))
    continuation = engine.poll_once()
    assert continuation["captured"] == 0
    assert continuation["counters"]["continuations"] == 1

    stale = _fill(now[0] - MAX_TARGET_LAG_MS - 1, event="stale")
    _append(input_path, stale)
    result = engine.poll_once()
    assert result["captured"] == 0
    assert result["counters"]["stale_rejected"] == 1


def test_troisieme_fill_live_planifie_des_checkpoints_de_continuation(tmp_path: Path) -> None:
    now = [2_500_000]
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )
    input_path = tmp_path / INPUT_RELPATH
    fills = [_fill(now[0], event="first", start_position=0.0)]
    _append(input_path, fills[-1])
    assert engine.poll_once()["captured"] == 1

    for index in range(2, CONTINUATION_SIGNAL_FILL_COUNT + 1):
        now[0] += 1_000
        fills.append(_fill(now[0], event=f"fill-{index}", start_position=0.01 * (index - 1)))
        _append(input_path, fills[-1])
        result = engine.poll_once()

    assert result["captured"] == 1
    assert result["counters"]["continuation_signals_started"] == 1
    replay_rows = [{
        **fill,
        "event_id": canonical_fill_id(fill),
        "direction": 1,
        "action": "OPEN" if index == 0 else "ADD",
        "observed_at_ms": fill["received_at_ms"],
        "is_snapshot": False,
    } for index, fill in enumerate(fills)]
    continuation = select_observed_continuations(cluster_metaorders(replay_rows)[0])[0][0]
    checkpoints = [
        json.loads(line)
        for line in (tmp_path / OUTPUT_RELPATH).read_text(encoding="utf-8").splitlines()
    ]
    assert checkpoints[-1]["checkpoint_stage"] == "REFERENCE"
    assert checkpoints[-1]["metaorder_id"] == continuation["metaorder_id"]


def test_live_tail_et_replay_partagent_identite_immuable(tmp_path: Path) -> None:
    now = [3_000_000]
    fill = _fill(now[0], event="identity")
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )
    _append(tmp_path / INPUT_RELPATH, fill)

    assert engine.poll_once()["captured"] == 1
    checkpoint = json.loads(
        (tmp_path / OUTPUT_RELPATH).read_text(encoding="utf-8").splitlines()[0]
    )
    replay_event = {
        **fill,
        "fill_id": canonical_fill_id(fill),
        "event_id": canonical_fill_id(fill),
        "direction": 1,
        "action": "OPEN",
        "observed_at_ms": fill["received_at_ms"],
        "is_snapshot": False,
    }
    replay_metaorder = cluster_metaorders([replay_event])[0][0]

    assert checkpoint["metaorder_id"] == replay_metaorder["metaorder_id"]


def test_open_explicite_redemarre_un_metaordre_meme_dans_la_fenetre(tmp_path: Path) -> None:
    now = [4_000_000]
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )
    input_path = tmp_path / INPUT_RELPATH
    _append(input_path, _fill(now[0], event="first", start_position=0.0))
    assert engine.poll_once()["captured"] == 1
    first_id = json.loads(
        (tmp_path / OUTPUT_RELPATH).read_text(encoding="utf-8").splitlines()[0]
    )["metaorder_id"]

    now[0] += 1_000
    _append(input_path, _fill(now[0], event="second", start_position=0.0))
    assert engine.poll_once()["captured"] == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / OUTPUT_RELPATH).read_text(encoding="utf-8").splitlines()
    ]
    assert rows[-1]["metaorder_id"] != first_id
