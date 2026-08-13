"""Orchestrateur du pipeline RÉEL (rectif Flo 23/07) : charge les entrées alpha des épisodes backfillés
+ NAV, mesure OOS purgée. NEED_MORE_DATA honnête sans historique. Sans réseau (fichiers locaux)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


PR = _mod("pipeline_copie_reel")


def test_charger_entrees_alpha_exclut_retraits_et_ajoute_move_frac(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_snapshots.jsonl").write_text(
        json.dumps({"vault": "0xA", "ts_ms": 1, "nav_usd": 100_000})
    )
    episodes = [
        {"ts_ms": 1, "vault": "0xA", "coin": "SOL", "action": "OPEN", "direction": 1, "taille_usd": 9000.0},
        {"ts_ms": 2, "vault": "0xA", "coin": "BTC", "action": "REDUCE", "direction": 1, "taille_usd": 5000.0,
         "retrait_probable": True, "retrait_source": "ledger"},        # retrait ledger -> exclu
    ]
    (tmp_path / "runtime" / "data" / "vault_episodes.jsonl").write_text("\n".join(json.dumps(e) for e in episodes))
    entrees = PR.charger_entrees_alpha(tmp_path)
    assert len(entrees) == 1 and entrees[0]["coin"] == "SOL" and entrees[0]["move_frac"] == 0.09


def test_nav_asof_interdit_fuite_future_et_deduplique_episodes(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    snapshots = [
        {"vault": "0xA", "ts_ms": 100, "nav_usd": 1_000},
        {"vault": "0xA", "ts_ms": 300, "nav_usd": 10_000},
    ]
    (data / "vault_snapshots.jsonl").write_text("\n".join(map(json.dumps, snapshots)))
    old = {"ts_ms": 50, "vault": "0xA", "coin": "BTC", "action": "OPEN", "direction": 1,
           "taille_usd": 100.0, "fill_id": "old"}
    valid = {"ts_ms": 200, "vault": "0xA", "coin": "SOL", "action": "OPEN", "direction": 1,
             "taille_usd": 100.0, "fill_id": "same"}
    (data / "vault_episodes.jsonl").write_text("\n".join(map(json.dumps, [old, valid, valid])))

    entries, audit = PR.charger_entrees_alpha_avec_audit(tmp_path)

    assert len(entries) == 1
    assert entries[0]["nav_at_signal_usd"] == 1_000
    assert entries[0]["move_frac"] == 0.1
    assert audit["duplicate_episodes_rejected"] == 1
    assert audit["missing_or_stale_asof_nav_rejected"] == 1


def test_pipeline_reconstruit_depuis_fills_dedupliques_et_preserve_identite(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_snapshots.jsonl").write_text(json.dumps(
        {"vault": "0xA", "ts_ms": 100, "nav_usd": 10_000}
    ))
    fill = {"vault": "0xA", "ts_ms": 200, "coin": "BTC", "px": 100.0, "sz": 1.0,
            "signe": 1, "dir": "Open Long", "start_position": 0.0, "oid": 42, "hash": "0xabc"}
    (data / "vault_fills.jsonl").write_text("\n".join(map(json.dumps, [fill, fill])))

    entries, audit = PR.charger_entrees_alpha_avec_audit(tmp_path)

    assert len(entries) == 1
    assert entries[0]["oid"] == 42 and entries[0]["fill_id"]
    assert audit["duplicate_fills_rejected"] == 1
    assert audit["episode_source"] == "vault_fills_deduped_reconstructed"


def test_construire_need_more_data_sans_historique(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_episodes.jsonl").write_text("")
    rap = PR.construire(tmp_path)
    assert rap["mesure"]["statut"] == "NEED_MORE_DATA" and "gel" not in rap
