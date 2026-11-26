"""Fusion des fills des lanes GitHub : dédup + préférence causale + fraîcheur."""
from __future__ import annotations

import json
import multiprocessing
from pathlib import Path

import pytest

from hl_observer.collection.copy_vault_checkpoint_socle import (
    CheckpointSourceBusy,
    FillSourceChanged,
    copy_vault_checkpoint_source_lock,
    copy_vault_fill_writer_lock,
)
import tools.fusionner_fills_lanes as fusion_module
from tools.fusionner_fills_lanes import fusionner
from tools.telecharger_fills_ws_lanes_github import telecharger_et_fusionner


def _w(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _fill(tid: int, t: int, obs: int, *, source="LIVE_POLL", snap=False) -> dict:
    return {"vault": "0xV", "coin": "BTC", "time": t, "tid": tid, "oid": 100 + tid,
            "px": "1.0", "sz": "1.0", "side": "B", "source": source,
            "isSnapshot": snap, "observed_at_ms": obs}


def _hold_checkpoint_lock(root: str, entered, release) -> None:
    with copy_vault_checkpoint_source_lock(Path(root), wait_s=2):
        entered.set()
        release.wait(15)


def test_fusion_dedupe_prefere_causal_et_rejette_pollue(tmp_path: Path) -> None:
    root = tmp_path
    cible = root / "runtime" / "data" / "vault_fills_poll.jsonl"
    # Local : un fill frais non-snapshot (tid 1).
    _w(cible, [_fill(1, 1_000, 1_100)])
    # Lane 0 : un nouveau (tid 2), un DOUBLON de tid 1 mais snapshot, un STALE, un NON-CAUSAL.
    _w(root / "dl" / "poll-fills-shard-0" / "vault_fills_poll.jsonl", [
        _fill(2, 2_000, 2_050),
        _fill(1, 1_000, 1_100, snap=True),                 # doublon (snapshot)
        _fill(3, 1_000, 1_000 + 700_000),                  # stale (lag 700 s > 600 s)
        _fill(4, 4_000, 4_050, source="REST_BACKFILL"),    # non causal
    ])
    # Lane 1 : un nouveau (tid 5).
    _w(root / "dl" / "poll-fills-shard-1" / "vault_fills_poll.jsonl", [_fill(5, 3_000, 3_050)])

    rap = fusionner(root, root / "dl", max_lag_ms=600_000)

    assert rap["doublons_retires"] == 1          # tid 1 vu 2 fois
    assert rap["rejets_qualite"] == 2            # stale + non causal
    assert rap["total_final"] == 3               # tids 1, 2, 5

    rows = [json.loads(l) for l in cible.read_text(encoding="utf-8").splitlines()]
    tids = sorted(r["tid"] for r in rows)
    assert tids == [1, 2, 5]
    tid1 = [r for r in rows if r["tid"] == 1][0]
    assert tid1["isSnapshot"] is False           # on a gardé la vue causale, pas le snapshot
    # Backup non destructif de l'ancien fichier local.
    assert (cible.with_suffix(".jsonl.avant-fusion.bak")).exists()


def test_fusion_preserves_prior_backups_instead_of_overwriting_them(tmp_path: Path) -> None:
    root = tmp_path
    cible = root / "runtime" / "data" / "vault_fills_poll.jsonl"
    _w(cible, [_fill(1, 1_000, 1_100)])
    original_bytes = cible.read_bytes()
    artefacts = root / "dl"
    _w(artefacts / "lane-0" / "vault_fills_poll.jsonl", [_fill(2, 2_000, 2_050)])

    first = fusionner(root, artefacts, 600_000)
    first_backup = Path(first["backup_path"])
    first_backup_bytes = first_backup.read_bytes()
    assert first_backup_bytes == original_bytes

    second = fusionner(root, artefacts, 600_000)
    second_backup = Path(second["backup_path"])

    assert first_backup.read_bytes() == first_backup_bytes
    assert second_backup != first_backup
    assert second_backup.exists()


def test_failed_atomic_install_restores_original_fill_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path
    cible = root / "runtime" / "data" / "vault_fills_poll.jsonl"
    _w(cible, [_fill(1, 1_000, 1_100)])
    original_bytes = cible.read_bytes()
    artefacts = root / "dl"
    _w(artefacts / "lane-0" / "vault_fills_poll.jsonl", [_fill(2, 2_000, 2_050)])
    real_replace = fusion_module.os.replace

    def fail_install(source, target):
        if Path(source).name.endswith(".fusion.tmp") and Path(target) == cible:
            raise OSError("simulated atomic install failure")
        return real_replace(source, target)

    monkeypatch.setattr(fusion_module.os, "replace", fail_install)
    with pytest.raises(OSError, match="simulated atomic install failure"):
        fusionner(root, artefacts, 600_000)

    assert cible.read_bytes() == original_bytes
    assert not cible.with_suffix(".jsonl.avant-fusion.bak").exists()
    assert not cible.with_suffix(".jsonl.fusion.tmp").exists()


def test_live_lane_merge_defers_while_forward_checkpoint_owns_source(tmp_path: Path) -> None:
    root = tmp_path
    cible = root / "runtime" / "data" / "vault_fills_live.jsonl"
    original = [_fill(1, 1_000, 1_100, source="LIVE_WS")]
    _w(cible, original)
    artefacts = root / "downloads"
    _w(artefacts / "ws-fills-shard-0" / "vault_fills_ws_lane.jsonl",
       [_fill(2, 2_000, 2_050, source="LIVE_WS")])

    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    release = context.Event()
    holder = context.Process(
        target=_hold_checkpoint_lock,
        args=(str(root), entered, release),
    )
    holder.start()
    try:
        assert entered.wait(10), "checkpoint lock holder did not start"
        # The primary live collector remains able to append while the tailer owns
        # its separate source-replacement guard.
        with copy_vault_fill_writer_lock(root, wait_s=1):
            with cible.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_fill(3, 3_000, 3_050, source="LIVE_WS")) + "\n")
        original_bytes = cible.read_bytes()

        result = telecharger_et_fusionner(
            root,
            gh=lambda *_args, **_kwargs: pytest.fail("GitHub must not be contacted while locked"),
        )
        assert result == {"statut": "deferred_active_checkpoint", "runs": 0, "fusion": None}
        with pytest.raises(CheckpointSourceBusy):
            fusionner(root, artefacts, 600_000, cible_rel=Path("runtime/data/vault_fills_live.jsonl"),
                      motif="vault_fills_ws_lane.jsonl")

        assert cible.read_bytes() == original_bytes
        assert not cible.with_suffix(".jsonl.avant-fusion.bak").exists()
        assert not cible.with_suffix(".jsonl.fusion.tmp").exists()
    finally:
        release.set()
        holder.join(10)
        if holder.is_alive():
            holder.terminate()
            holder.join(5)

    assert holder.exitcode == 0
    merged = fusionner(
        root,
        artefacts,
        600_000,
        cible_rel=Path("runtime/data/vault_fills_live.jsonl"),
        motif="vault_fills_ws_lane.jsonl",
    )
    assert merged["total_final"] == 3
    # 26/11/2026 : le ruban LIVE n'est plus reecrit (ajout seul) : le local reste intact, octet pour octet
    assert cible.read_bytes().startswith(original_bytes)
    assert not cible.with_suffix(".jsonl.avant-fusion.bak").exists()


def test_merge_defers_if_collector_appends_during_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path
    cible = root / "runtime" / "data" / "vault_fills_poll.jsonl"
    _w(cible, [_fill(1, 1_000, 1_100)])
    artefacts = root / "dl"
    _w(artefacts / "lane-0" / "vault_fills_poll.jsonl", [_fill(2, 2_000, 2_050)])
    original_merge = fusion_module.merge_dedup_fills

    def append_during_prepare(*sources):
        with copy_vault_fill_writer_lock(root, wait_s=1):
            with cible.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(_fill(3, 3_000, 3_050)) + "\n")
        return original_merge(*sources)

    monkeypatch.setattr(fusion_module, "merge_dedup_fills", append_during_prepare)
    with pytest.raises(FillSourceChanged):
        fusionner(root, artefacts, 600_000)

    rows = [json.loads(line) for line in cible.read_text(encoding="utf-8").splitlines()]
    assert sorted(row["tid"] for row in rows) == [1, 3]
    assert not cible.with_suffix(".jsonl.avant-fusion.bak").exists()
    assert not cible.with_suffix(".jsonl.fusion.tmp").exists()


def test_le_ruban_live_garde_les_fills_du_collecteur_ws(tmp_path: Path) -> None:
    """26/11/2026 : le collecteur WS ecrit ``ts_ms``/``received_at_ms`` ; le filtre des lanes exige ``time``/
    ``observed_at_ms``. La fusion retirait donc TOUTES les lignes locales du ruban live (777 sur 777 mesurees)."""
    root = tmp_path
    cible = root / "runtime" / "data" / "vault_fills_live.jsonl"
    locales = [{"vault": "0xabc", "coin": "NEO", "px": 1.5, "sz": 2.0, "signe": 1, "ts_ms": 1_000 + i,
                "received_at_ms": 1_400 + i, "tid": 100 + i, "source": "LIVE_WS"} for i in range(3)]
    _w(cible, locales)
    avant = cible.read_bytes()
    artefacts = root / "dl"
    _w(artefacts / "ws-fills-shard-0" / "vault_fills_ws_lane.jsonl",
       [_fill(7, 2_000, 2_050, source="LIVE_WS"), {**_fill(8, 3_000, 3_050, source="LIVE_WS"), "tid": 101,
                                                   "vault": "0xabc", "coin": "NEO"}])
    rap = fusionner(root, artefacts, 600_000, cible_rel=Path("runtime/data/vault_fills_live.jsonl"),
                    motif="vault_fills_ws_lane.jsonl")
    apres = cible.read_bytes()
    assert apres.startswith(avant)                                   # aucune ligne du collecteur retiree
    ajout = [json.loads(x) for x in apres[len(avant):].decode("utf-8").splitlines()]
    assert [r["tid"] for r in ajout] == [7]                          # le tid 101, deja la, n'est pas double
    assert rap["mode"] == "AJOUT_SEUL" and rap["locales"] == 3 and rap["ajoutees"] == 1
