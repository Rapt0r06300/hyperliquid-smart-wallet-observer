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
    (tmp_path / "runtime" / "data" / "vault_snapshots.jsonl").write_text(json.dumps({"vault": "0xA", "nav_usd": 100_000}))
    episodes = [
        {"ts_ms": 1, "vault": "0xA", "coin": "SOL", "action": "OPEN", "direction": 1, "taille_usd": 9000.0},
        {"ts_ms": 2, "vault": "0xA", "coin": "BTC", "action": "REDUCE", "direction": 1, "taille_usd": 5000.0,
         "retrait_probable": True, "retrait_source": "ledger"},        # retrait ledger -> exclu
    ]
    (tmp_path / "runtime" / "data" / "vault_episodes.jsonl").write_text("\n".join(json.dumps(e) for e in episodes))
    entrees = PR.charger_entrees_alpha(tmp_path)
    assert len(entrees) == 1 and entrees[0]["coin"] == "SOL" and entrees[0]["move_frac"] == 0.09


def test_construire_need_more_data_sans_historique(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_episodes.jsonl").write_text("")
    rap = PR.construire(tmp_path)
    assert rap["mesure"]["statut"] == "NEED_MORE_DATA" and "gel" not in rap
