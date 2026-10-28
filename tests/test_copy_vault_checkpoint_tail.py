from __future__ import annotations

import json
from pathlib import Path

import pytest

import hl_observer.collection.copy_vault_checkpoint_tail as checkpoint_module
from hl_observer.backtesting.copy_vault_executable import (
    cluster_metaorders,
    load_observed_books,
    select_observed_continuations,
)
from hl_observer.backtesting.copy_vault_protocol import INSTRUMENT_IDENTITY_SCHEMA
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
    coin: str = "BTC",
) -> dict:
    return {
        "vault": VAULT,
        "coin": coin,
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


@pytest.mark.parametrize(
    "bids,asks",
    [
        ([{"px": "59998", "sz": "2"}, {"px": "59999", "sz": "3"}],
         [{"px": "60001", "sz": "2.5"}]),
        ([{"px": "59999", "sz": "2"}],
         [{"px": "60001", "sz": "2.5"}, {"px": "60001", "sz": "4"}]),
    ],
)
def test_checkpoint_parser_refuse_les_niveaux_l2_invalides(bids, asks) -> None:
    raw = {"time": 2_000, "levels": [bids, asks]}

    assert checkpoint_module._parse_book(raw, received_at_ms=2_010) is None


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
    assert state["writer_run_id"].startswith("copy-writer-")
    assert state["clean_epoch_ms"] == 2_000


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
    assert all(row["instrument_identity_schema"] == INSTRUMENT_IDENTITY_SCHEMA for row in rows)
    assert all(row["writer_run_id"] == engine.state["writer_run_id"] for row in rows)
    assert all(row["clean_epoch_ms"] == engine.state["clean_epoch_ms"] for row in rows)
    assert all(row["vault"] == VAULT for row in rows)
    assert all(row["direction"] == 1 for row in rows)
    assert all(row["signal_ts_ms"] == 1_000_000 for row in rows)
    assert all(row["signal_event_id"] == canonical_fill_id(_fill(1_000_000)) for row in rows)
    assert all(row["signal_action"] == "OPEN" for row in rows)
    assert all(row["paper_read_only"] is True and row["real_execution"] is False for row in rows)
    assert all(
        0 <= row["received_at_ms"] - row["checkpoint_target_ms"] <= MAX_TARGET_LAG_MS
        for row in rows
    )

    _, audit = load_observed_books(tmp_path, coins={"BTC"})
    receipt = audit["clean_epoch_receipt"]
    assert receipt["receipt_valid"] is True
    assert receipt["writer_run_id"] == engine.state["writer_run_id"]
    assert receipt["checkpoint_rows"] == 3
    assert receipt["duplicate_checkpoint_ids"] == 0
    assert receipt["quarantined_checkpoint_metaorders"] == 0


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


def test_checkpoints_simultanes_du_meme_coin_partagent_une_observation_l2(
    tmp_path: Path,
) -> None:
    now = [5_000_000]
    fetches = []

    def fetch(coin: str) -> dict:
        fetches.append(coin)
        return _book(now[0])

    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=fetch,
        clock_ms=lambda: now[0],
    )
    engine.state["pending"] = [
        {
            "coin": "BTC",
            "metaorder_id": f"meta-{index}",
            "stage": "REFERENCE",
            "checkpoint_id": f"meta-{index}:REFERENCE",
            "target_wall_ms": now[0],
            "attempts": 0,
        }
        for index in range(2)
    ]

    result = engine.poll_once()

    assert result["captured"] == 2
    assert fetches == ["BTC"]
    rows = [
        json.loads(line)
        for line in (tmp_path / OUTPUT_RELPATH).read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 2
    assert len({row["checkpoint_id"] for row in rows}) == 2
    assert len({row["received_at_ms"] for row in rows}) == 1


def test_checkpoint_conserve_et_rejoue_le_symbole_native_case_sensitive(tmp_path: Path):
    now = [8_000_000]
    fetched: list[str] = []

    def fetch(coin: str) -> dict:
        fetched.append(coin)
        return _book(now[0])

    engine = CopyVaultCheckpointTail(
        tmp_path, fetch_book=fetch, clock_ms=lambda: now[0]
    )
    fill = _fill(now[0], event="kpepe", coin="kPEPE")
    _append(tmp_path / INPUT_RELPATH, fill)

    result = engine.poll_once()
    rows = [
        json.loads(line)
        for line in (tmp_path / OUTPUT_RELPATH).read_text(encoding="utf-8").splitlines()
    ]
    books, audit = load_observed_books(tmp_path, coins={"kPEPE"})

    assert result["captured"] == 1
    assert fetched == ["kPEPE"]
    assert rows[0]["coin"] == "kPEPE"
    assert books["kPEPE"][0]["coin"] == "kPEPE"
    assert audit["causal_forward_rows"] == 1


def test_ancienne_identite_de_checkpoint_est_reinitialisee_sans_rejouer_historique(
    tmp_path: Path,
):
    input_path = tmp_path / INPUT_RELPATH
    _append(input_path, _fill(1_000_000, event="legacy", coin="KPEPE"))
    output_path = tmp_path / OUTPUT_RELPATH
    _append(output_path, {"coin": "KPEPE", "checkpoint_id": "legacy:ENTRY"})
    (tmp_path / STATE_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / STATE_RELPATH).write_text(
        json.dumps({
            "schema_version": "hypersmart.copy_vault_checkpoint_tail.v2",
            "protocol": (
                "copy_vault_checkpoint_companion_v2_for_"
                "copy_vault_executable_walk_forward_v8_explicit_l2_gap_identity"
            ),
            "paper_read_only": True,
            "real_execution": False,
            "input_offset": 0,
            "output_start_offset": 0,
            "pending": [{"coin": "KPEPE", "checkpoint_id": "old:ENTRY"}],
        }),
        encoding="utf-8",
    )

    engine = CopyVaultCheckpointTail(tmp_path, clock_ms=lambda: 2_000_000)
    result = engine.poll_once()

    assert result["lines"] == 0
    assert result["pending"] == 0
    assert result["counters"]["identity_migration_resets"] == 1
    assert result["identity_migration_reset"]["reason"] == (
        "INSTRUMENT_IDENTITY_SCHEMA_CHANGED_OR_UNVERIFIED"
    )
    archived_state = tmp_path / result["identity_migration_reset"]["preserved_state_path"]
    assert json.loads(archived_state.read_text(encoding="utf-8"))["pending"] == [
        {"coin": "KPEPE", "checkpoint_id": "old:ENTRY"}
    ]
    assert engine.state["input_offset"] == input_path.stat().st_size
    assert engine.state["output_start_offset"] == output_path.stat().st_size


def test_file_replacement_is_recovered_but_invalidates_clean_epoch(tmp_path: Path) -> None:
    now = [6_000_000]
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )
    input_path = tmp_path / INPUT_RELPATH
    _append(input_path, _fill(now[0], event="before-rotation"))
    assert engine.poll_once()["captured"] == 1

    now[0] += 1_000
    input_path.unlink()
    _append(input_path, _fill(now[0], event="replacement-with-a-longer-id"))
    result = engine.poll_once()

    assert result["lines"] == 1
    assert result["captured"] == 1
    assert result["counters"]["input_rotations"] == 1
    assert result["replay_evidence_complete"] is False
    _, audit = load_observed_books(tmp_path, coins={"BTC"})
    assert audit["clean_epoch_receipt"]["receipt_valid"] is False
    assert audit["clean_epoch_receipt"]["collector_gap_count"] == 1


def test_pending_overflow_retains_existing_work_and_fails_closed(
    tmp_path: Path, monkeypatch,
) -> None:
    now = [7_000_000]
    monkeypatch.setattr(checkpoint_module, "MAX_PENDING", 2)
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )
    existing = {
        "coin": "ETH", "metaorder_id": "existing", "stage": "ENTRY",
        "checkpoint_id": "existing:ENTRY", "target_wall_ms": now[0] + 1_000,
        "attempts": 0,
    }
    engine.state["pending"] = [existing]

    engine._schedule_fill(_fill(now[0], event="overflow"), now_ms=now[0])

    assert engine.state["pending"] == [existing]
    assert engine.state["counters"]["pending_overflow_rejected"] == 2
    result = engine.poll_once()
    assert result["replay_evidence_complete"] is False
    _, audit = load_observed_books(tmp_path, coins={"BTC", "ETH"})
    assert audit["clean_epoch_receipt"]["receipt_valid"] is False
    assert audit["clean_epoch_receipt"]["collector_gap_count"] == 2
