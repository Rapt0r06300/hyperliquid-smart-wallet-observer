"""Runner de mesure réelle de l'edge de copie (rectif Flo 23/07) : charge les entrées alpha depuis les
épisodes, attache move_frac via le NAV du vault, mesure OOS. Sans réseau (fichiers locaux)."""
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


MC = _mod("mesurer_copie")


def test_charger_entrees_alpha_attache_move_frac(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_snapshots.jsonl").write_text(
        json.dumps({"vault": "0xA", "nav_usd": 100_000}))
    episodes = [
        {"ts_ms": 1, "vault": "0xA", "coin": "SOL", "action": "OPEN", "direction": 1, "taille_usd": 8000.0},
        {"ts_ms": 2, "vault": "0xA", "coin": "SOL", "action": "REDUCE", "direction": 1, "taille_usd": 1000.0,
         "retrait_probable": True},                                    # retrait -> exclu
    ]
    (tmp_path / "runtime" / "data" / "vault_episodes.jsonl").write_text(
        "\n".join(json.dumps(e) for e in episodes))
    entrees = MC.charger_entrees_alpha(tmp_path)
    assert len(entrees) == 1 and entrees[0]["action"] == "OPEN"
    assert entrees[0]["move_frac"] == 0.08                             # 8000 / 100000


def test_construire_need_more_data_sans_historique(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vault_episodes.jsonl").write_text("")
    rap = MC.construire(tmp_path)
    assert rap["mesure"]["statut"] == "NEED_MORE_DATA" and "gel" not in rap
