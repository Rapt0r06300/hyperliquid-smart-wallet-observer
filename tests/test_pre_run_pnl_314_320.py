from __future__ import annotations

import importlib.util
from pathlib import Path
import urllib.error

from hl_observer.collection import collecte_fiable as CF
from hl_observer.collection import vault_fills_backfill as VB
from hl_observer.collection import vault_ledger as VL
from hl_observer.collection.copy_vault_checkpoint_tail import (
    INPUT_RELPATH,
    MAX_TARGET_LAG_MS,
    CopyVaultCheckpointTail,
)
from hl_observer.ops.canonical_775_guard import (
    KNOWN_CANONICAL_ANCHORS,
    ROADMAP_ID,
    ROADMAP_TOTAL,
    validate_manifest,
)

RACINE = Path(__file__).resolve().parents[1]
VAULT = "0x" + "a" * 40


def _tool():
    spec = importlib.util.spec_from_file_location(
        "pre_run_backfill_vault_fills", RACINE / "tools" / "backfill_vault_fills.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BF = _tool()


def _raw_fill(
    ts: int,
    *,
    side: str,
    size: float,
    start: float,
    direction_label: str,
    coin: str = "BTC",
    ref: str = "x",
) -> dict:
    return {
        "time": ts,
        "coin": coin,
        "px": "100",
        "sz": str(size),
        "side": side,
        "dir": direction_label,
        "startPosition": str(start),
        "hash": f"0x{ref}",
        "tid": ref,
        "oid": ref,
    }


def test_314_flip_un_seul_fill_cloture_puis_rouvre_le_reliquat() -> None:
    fills = VB.parser_fills([
        _raw_fill(1, side="B", size=10, start=0, direction_label="Open Long", ref="open"),
        _raw_fill(2, side="A", size=15, start=10, direction_label="Close Long", ref="flip"),
    ], vault=VAULT)

    events = VB.reconstruire_episodes(fills)

    assert [event["action"] for event in events] == ["OPEN", "CLOSE", "OPEN"]
    close, reopen = events[1], events[2]
    assert (close["pos_avant"], close["pos_apres"], close["direction"]) == (10.0, 0.0, 1)
    assert (reopen["pos_avant"], reopen["pos_apres"], reopen["direction"]) == (0.0, -5.0, -1)
    assert close["fill_id"] == reopen["fill_id"]
    assert close["event_id"] != reopen["event_id"]
    assert [close["fill_component_index"], reopen["fill_component_index"]] == [0, 1]
    assert reopen["dir"] == "Open Short"


def test_314_start_position_recale_chaque_fill_apres_un_trou() -> None:
    fills = VB.parser_fills([
        _raw_fill(1, side="B", size=10, start=0, direction_label="Open Long", ref="a"),
        # Un historique incomplet ferait croire à pos=10. Le startPosition réel
        # prouve que la position vaut déjà 30 juste avant ce nouveau fill.
        _raw_fill(2, side="B", size=5, start=30, direction_label="Open Long", ref="b"),
    ], vault=VAULT)

    events = VB.reconstruire_episodes(fills)

    assert events[1]["action"] == "ADD"
    assert events[1]["pos_avant"] == 30.0
    assert events[1]["pos_apres"] == 35.0
    assert events[1]["position_rebased"] is True


def test_315_depot_ne_devient_pas_pnl_et_retrait_marque_la_reduction() -> None:
    ledger = VL.parser_ledger([
        {"time": 100, "delta": {"type": "deposit", "usdc": "1000"}},
        {"time": 200, "delta": {"type": "withdraw", "usdc": "-400"}},
    ], vault=VAULT.upper())
    assert [row["est_retrait"] for row in ledger] == [False, True]

    fills = VB.parser_fills([
        _raw_fill(1, side="B", size=10, start=0, direction_label="Open Long", ref="a"),
        _raw_fill(200, side="A", size=4, start=10, direction_label="Close Long", ref="b"),
    ], vault=VAULT)
    events = VB.reconstruire_episodes(fills)
    VL.marquer_retraits_ledger(events, ledger, fenetre_ms=1_000)
    reduce = next(event for event in events if event["action"] == "REDUCE")
    assert reduce["retrait_probable"] is True
    assert reduce["retrait_source"] == "ledger"


def test_316_identite_wallet_vault_est_stable_entre_casse_et_sources() -> None:
    assert VB.normaliser_vault(" 0xAbCd ") == "0xabcd"
    upper = "0x" + "A" * 40
    lower = upper.lower()
    raw = _raw_fill(1, side="B", size=10, start=0, direction_label="Open Long", ref="same")
    a = VB.parser_fills([raw], vault=upper)[0]
    b = VB.parser_fills([raw], vault=lower)[0]
    assert VB.fill_identity(a) == VB.fill_identity(b)

    fills = VB.parser_fills([
        _raw_fill(1, side="B", size=10, start=0, direction_label="Open Long", ref="open"),
        _raw_fill(200, side="A", size=2, start=10, direction_label="Close Long", ref="reduce"),
    ], vault=upper)
    events = VB.reconstruire_episodes(fills)
    assert {event["vault"] for event in events} == {lower}
    ledger = VL.parser_ledger([
        {"time": 200, "delta": {"type": "withdraw", "usdc": "-1"}},
    ], vault=upper)
    VL.marquer_retraits_ledger(events, ledger, fenetre_ms=1_000)
    assert next(event for event in events if event["action"] == "REDUCE")["retrait_source"] == "ledger"


def test_317_318_page_cappee_est_subdivisee_jusqu_a_couverture_complete(monkeypatch) -> None:
    monkeypatch.setattr(BF.time, "time", lambda: 1_000_000.0)
    calls: list[tuple[int, int]] = []

    def poster(_vault: str, start: int, end: int):
        calls.append((start, end))
        span = end - start
        if span > 6 * VB.MS_PAR_HEURE:
            # cap=2 : cette page est ambiguë/tronquée et doit être subdivisée.
            return [
                _raw_fill(start + 1, side="B", size=1, start=0, direction_label="Open Long", ref=f"c{start}"),
                _raw_fill(start + 2, side="B", size=1, start=1, direction_label="Open Long", ref=f"d{start}"),
            ]
        return [
            _raw_fill(start + 1, side="B", size=1, start=0, direction_label="Open Long", ref=f"u{start}"),
        ]

    fills, audit = BF.backfill_un_vault_avec_audit(
        Path("."), VAULT, lookback_j=1, limiteur=CF.Limiteur(0.0),
        poster=poster, cap=2, fenetre_ms=24 * VB.MS_PAR_HEURE,
        min_fenetre_ms=60_000,
    )

    assert audit["complete"] is True
    assert audit["capped_responses"] > 0
    assert audit["split_windows"] > 0
    assert audit["failed_windows"] == []
    assert audit["cap_blocked_windows"] == []
    assert len(calls) > 1
    assert fills


def test_317_echec_reseau_rend_le_backfill_explicitement_incomplet(monkeypatch) -> None:
    monkeypatch.setattr(BF.time, "time", lambda: 1_000_000.0)

    def poster(_vault: str, _start: int, _end: int):
        raise urllib.error.URLError("offline")

    fills, audit = BF.backfill_un_vault_avec_audit(
        Path("."), VAULT, lookback_j=1, limiteur=CF.Limiteur(0.0), poster=poster
    )

    assert fills == []
    assert audit["complete"] is False
    assert len(audit["failed_windows"]) == 1
    assert audit["paper_read_only"] is True
    assert audit["real_execution"] is False


def test_319_dedup_conserve_live_ws_quel_que_soit_l_ordre_des_sources() -> None:
    common = {
        "vault": VAULT,
        "ts_ms": 1_000,
        "coin": "BTC",
        "px": 100.0,
        "sz": 1.0,
        "dir": "Open Long",
        "hash": "0xsame",
    }
    rest = {**common, "source": "REST_BACKFILL", "tid": 7, "oid": 8}
    live = {
        **common,
        "source": "LIVE_WS",
        "isSnapshot": False,
        "received_at_ms": 1_005,
    }

    left = VB.dedupliquer([rest, live])
    right = VB.dedupliquer([live, rest])

    assert left == right == [live]
    assert VB.fill_identity(rest) == VB.fill_identity(live)


def test_320_leader_trop_vieux_est_refuse_avant_checkpoint(tmp_path: Path) -> None:
    now = [2_000_000]
    engine = CopyVaultCheckpointTail(
        tmp_path,
        fetch_book=lambda _coin: None,
        clock_ms=lambda: now[0],
    )
    input_path = tmp_path / INPUT_RELPATH
    input_path.parent.mkdir(parents=True, exist_ok=True)
    received = now[0] - MAX_TARGET_LAG_MS - 1
    payload = {
        "vault": VAULT,
        "coin": "BTC",
        "px": 100.0,
        "sz": 1.0,
        "signe": 1,
        "ts_ms": received - 5,
        "dir": "Open Long",
        "hash": "0xstale",
        "tid": "stale",
        "oid": "stale",
        "isSnapshot": False,
        "source": "LIVE_WS",
        "stable_event_id": "stale",
        "received_at_ms": received,
    }
    with input_path.open("a", encoding="utf-8") as handle:
        import json
        handle.write(json.dumps(payload) + "\n")

    result = engine.poll_once()

    assert result["captured"] == 0
    assert result["pending"] == 0
    assert result["counters"]["stale_rejected"] == 1


def test_garde_775_refuse_labels_factices_et_preuve_generique_reutilisee() -> None:
    labels = ["x"] * ROADMAP_TOTAL
    for number, label in KNOWN_CANONICAL_ANCHORS.items():
        labels[number - 1] = label
    manifest = {
        "roadmap_id": ROADMAP_ID,
        "total": ROADMAP_TOTAL,
        "status": "DONE",
        "legacy_master_v6_equivalent": False,
        "anchors": {str(number): label for number, label in KNOWN_CANONICAL_ANCHORS.items()},
        "labels": labels,
        "proofs": {str(number): "pytest tests/test_everything.py" for number in range(1, ROADMAP_TOTAL + 1)},
    }

    result = validate_manifest(manifest)

    assert result["ok"] is False
    assert "DONE_REQUIRES_LITERAL_NON_PLACEHOLDER_LABELS" in result["issues"]
    assert "DONE_REQUIRES_775_DISTINCT_EXECUTABLE_PROOFS" in result["issues"]
