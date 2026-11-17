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
    coverage_receipt,
)
from hl_observer.collection.vault_fills_backfill import canonical_fill_id

VAULT = "0x" + "a" * 40


@pytest.mark.parametrize("incident", ("checkpoints_expired", "pending_overflow_rejected", "input_rotations"))
def test_recu_couverture_refuse_les_incidents_meme_si_lignes_completes(incident: str) -> None:
    counters = {
        "complete_lines": 10, "checkpoints_captured": 20,
        "reconnect_backfill_blocked": 0, "invalid_rejected": 0,
        "input_rotations": 0, "checkpoints_expired": 0,
        "pending_overflow_rejected": 0,
    }
    assert coverage_receipt(counters, expected_lines=10)["status"] == "PROVEN"
    counters[incident] = 1
    result = coverage_receipt(counters, expected_lines=10)
    assert result["status"] == "UNMEASURABLE"
    assert result["gap_count"] == 1


def test_recu_couverture_refuse_un_compteur_manquant_ou_invalide() -> None:
    counters = {
        "complete_lines": 10, "checkpoints_captured": 20,
        "reconnect_backfill_blocked": 0, "invalid_rejected": 0,
        "input_rotations": 0, "checkpoints_expired": 0,
        "pending_overflow_rejected": 0,
    }
    for value in (None, True, -1):
        damaged = dict(counters)
        if value is None:
            damaged.pop("checkpoints_expired")
        else:
            damaged["checkpoints_expired"] = value
        result = coverage_receipt(damaged, expected_lines=10)
        assert result["status"] == "UNMEASURABLE"
        assert result["reason"] == "COUNTERS_INCOMPLETE_OR_INVALID"


def test_recu_couverture_ne_compte_pas_deux_fois_une_rotation() -> None:
    counters = {
        "complete_lines": 10, "checkpoints_captured": 20,
        "reconnect_backfill_blocked": 1, "invalid_rejected": 0,
        "input_rotations": 1, "checkpoints_expired": 0,
        "pending_overflow_rejected": 0,
    }
    assert coverage_receipt(counters, expected_lines=10)["gap_count"] == 1


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


@pytest.mark.parametrize("invalid_time", [True, 2_000.0, "2000", 0, -1])
def test_checkpoint_parser_rejette_les_timestamps_l2_ambigus(invalid_time) -> None:
    raw = {
        "time": invalid_time,
        "levels": [
            [["99", "1"]],
            [["101", "1"]],
        ],
    }

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


def test_checkpoint_accepte_le_marqueur_is_snapshot_snake_case(tmp_path: Path) -> None:
    now = [2_000]
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )
    fill = _fill(now[0], event="snake-case")
    fill.pop("isSnapshot")
    fill["is_snapshot"] = False
    _append(tmp_path / INPUT_RELPATH, fill)

    result = engine.poll_once()

    assert result["captured"] == 1
    assert result["counters"]["valid_live_fills"] == 1


def test_checkpoint_rejette_les_marqueurs_snapshot_contradictoires(tmp_path: Path) -> None:
    now = [2_000]
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )
    fill = _fill(now[0], event="conflicting-snapshot-markers")
    fill["is_snapshot"] = True
    _append(tmp_path / INPUT_RELPATH, fill)

    result = engine.poll_once()

    assert result["captured"] == 0
    assert result["pending"] == 0
    assert result["counters"]["invalid_rejected"] == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [("signe", True), ("ts_ms", 1_000.5), ("received_at_ms", True)],
)
def test_checkpoint_rejette_direction_et_timestamps_non_stricts(
    tmp_path: Path, field: str, value: object,
) -> None:
    now = [2_000]
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: _book(now[0]),
        clock_ms=lambda: now[0],
    )
    fill = _fill(now[0], event=f"invalid-{field}")
    fill[field] = value
    _append(tmp_path / INPUT_RELPATH, fill)

    result = engine.poll_once()

    assert result["captured"] == 0
    assert result["counters"]["invalid_rejected"] == 1


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


def test_checkpoint_rejette_un_etat_persistant_corrompu(tmp_path: Path) -> None:
    now = [8_000_000]
    engine = CopyVaultCheckpointTail(tmp_path, clock_ms=lambda: now[0])
    state_path = tmp_path / STATE_RELPATH
    state = dict(engine.state)
    state["input_offset"] = True
    state["pending"] = "not-a-list"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    reloaded = CopyVaultCheckpointTail(tmp_path, clock_ms=lambda: now[0])

    assert reloaded.state["identity_migration_reset"]["reason"] == (
        "INSTRUMENT_IDENTITY_SCHEMA_CHANGED_OR_UNVERIFIED"
    )
    assert reloaded.state["input_offset"] == 0
    assert reloaded.state["pending"] == []


def test_file_replacement_is_recovered_and_SEGMENTS_the_clean_epoch(tmp_path: Path) -> None:
    """16/11/2026 — CONTRAT CHANGE, ET RESSERRE.

    AVANT : ce test exigeait `receipt_valid is False` apres une rotation, c'est-a-dire que le
    moindre incident ferme l'epoque ENTIERE. C'etait le bloqueur P0 de l'audit du 15/11 : la
    campagne reelle comptait 43 expirations et une rotation, donc 100 % des 25 875 checkpoints
    etaient non certifiables, y compris ceux des minutes sans incident. Zero trade executable.

    MAINTENANT : la spec autorise des trous globaux a condition de ne certifier que des intervalles
    `EXECUTION_REPLAY_SAFE`. L'ecrivain publie la FENETRE de chaque trou, et on verifie ici la
    propriete qui compte vraiment, plus forte que l'ancienne assertion : la ligne recue DANS la
    fenetre de rotation est refusee, celle recue APRES est certifiee, et le trou reste compte.
    """
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

    assert result["lines"] == 0
    assert result["captured"] == 0
    assert result["counters"]["input_rotations"] == 1
    assert result["counters"]["reconnect_backfill_blocked"] == 1
    assert result["replay_evidence_complete"] is False

    # The replacement file's pre-existing contents are a reconnect snapshot or
    # backfill and must not be replayed as causal LIVE_WS evidence. Only a row
    # appended after the new identity was baselined may be admitted.
    now[0] += 1_000
    _append(input_path, _fill(now[0], event="post-reconnect-live"))
    post_reconnect = engine.poll_once()
    assert post_reconnect["lines"] == 1
    assert post_reconnect["captured"] == 1
    _, audit = load_observed_books(tmp_path, coins={"BTC"})
    recu = audit["clean_epoch_receipt"]
    # Le trou n'est PAS effacé : il reste compté, et sa position est connue.
    assert recu["collector_gap_count"] == 1
    assert recu["gap_segmentation_reason"] == "OK", (
        "la position du trou doit etre expliquee, sinon la porte doit rester fermee")
    assert recu["safe_interval_count"] >= 1
    # La ligne d'AVANT la rotation tombe dans la fenetre du trou : elle est refusee.
    assert recu["rows_inside_gap_window"] >= 1, (
        "la ligne capturee juste avant la rotation est dans la fenetre : elle ne peut pas etre "
        "certifiee, sinon la segmentation ne servirait a rien")
    # Celle d'apres est une observation legitime : elle, elle compte.
    assert recu["checkpoint_rows"] >= 1 and recu["receipt_valid"] is True


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


# ───────── 17/11/2026 : l'arret de l'ecrivain est un trou declare, meme sans checkpoint en attente ─────────

def test_un_arret_SANS_checkpoint_en_attente_est_declare(tmp_path: Path) -> None:
    """Avant : une coupure sans checkpoint en attente ne laissait aucune fenetre de trou."""
    from hl_observer.collection import copy_vault_gap_windows as GAPS

    now = [5_000_000]
    engine = CopyVaultCheckpointTail(tmp_path, fetch_book=lambda _coin: _book(now[0]),
                                     clock_ms=lambda: now[0])
    engine.poll_once()
    assert engine.state["counters"]["writer_outages"] == 0 and not engine.state.get("gap_windows")

    now[0] += 42 * 60_000                                   # la veille du PC
    engine.poll_once()
    assert engine.state["counters"]["writer_outages"] == 1
    fenetres = engine.state["gap_windows"]
    assert len(fenetres) == 1 and fenetres[0]["nature"] == GAPS.TROU_ARRET
    assert fenetres[0]["debut_ms"] == 5_000_000 + GAPS.MARGE_MS + 1
    assert fenetres[0]["fin_ms"] == now[0] - MAX_TARGET_LAG_MS
    assert GAPS.journal_coherent(engine.state) == (True, "OK")
    intervalles, raison = GAPS.intervalles_depuis_etat(engine.state, fin_ms=now[0])
    assert raison == "OK"
    assert GAPS.est_sur(5_000_000, intervalles), "la derniere passe d'avant la coupure reste sure"
    assert not GAPS.est_sur(5_000_000 + 20 * 60_000, intervalles)
    assert GAPS.est_sur(now[0], intervalles), "la passe de reprise est sure"


def test_une_cadence_normale_ne_declare_aucun_arret(tmp_path: Path) -> None:
    now = [5_000_000]
    engine = CopyVaultCheckpointTail(tmp_path, fetch_book=lambda _coin: _book(now[0]),
                                     clock_ms=lambda: now[0])
    for _ in range(40):
        engine.poll_once()
        now[0] += MAX_TARGET_LAG_MS                         # pile la tolerance : pas un arret
    assert engine.state["counters"]["writer_outages"] == 0 and not engine.state.get("gap_windows")


def test_un_arret_compte_dans_les_trous_du_collecteur(tmp_path: Path) -> None:
    now = [5_000_000]
    engine = CopyVaultCheckpointTail(tmp_path, fetch_book=lambda _coin: _book(now[0]),
                                     clock_ms=lambda: now[0])
    assert engine.poll_once()["replay_evidence_complete"] is True
    now[0] += 10 * 60_000
    resultat = engine.poll_once()
    assert resultat["collector_gap_count"] == 1 and resultat["replay_evidence_complete"] is False


def test_au_chargement_le_journal_d_une_coupure_est_ramene_a_un_intervalle(tmp_path: Path) -> None:
    """L'etat reel du 17/11 : 302 fenetres pour une seule coupure, dans un journal plafonne a 512."""
    from hl_observer.collection import copy_vault_gap_windows as GAPS

    now = [5_000_000]
    engine = CopyVaultCheckpointTail(tmp_path, fetch_book=lambda _coin: _book(now[0]),
                                     clock_ms=lambda: now[0])
    engine.poll_once()
    etat = json.loads((tmp_path / STATE_RELPATH).read_text(encoding="utf-8"))
    etat["gap_windows_schema"] = GAPS.SCHEMA_FENETRES
    etat["gap_windows_dropped"] = 0
    etat["gap_windows"] = [{"nature": GAPS.TROU_EXPIRATION, "debut_ms": 5_100_000 + i * 1_000,
                            "fin_ms": 7_700_000, "n": 1} for i in range(302)]
    etat["counters"]["checkpoints_expired"] = 302
    (tmp_path / STATE_RELPATH).write_text(json.dumps(etat), encoding="utf-8")

    now[0] += 1_000
    repris = CopyVaultCheckpointTail(tmp_path, fetch_book=lambda _coin: _book(now[0]),
                                     clock_ms=lambda: now[0])
    assert len(repris.state["gap_windows"]) == 1
    assert repris.state["gap_windows"][0]["n"] == 302
    assert GAPS.journal_coherent(repris.state) == (True, "OK")
