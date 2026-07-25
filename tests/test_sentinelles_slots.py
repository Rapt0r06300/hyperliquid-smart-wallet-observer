"""LIQUIDATION_SENTINELS_V2 — pinning des slots userFills (Flo 25/07), prouvé sans réseau.

Prouve : (1) charger_sentinelles lit le journal confirmé et rend le top liquidateur ; (2) vaults_et_roles
ÉPINGLE ≤3 sentinelles APRÈS les 2 CORE, sans jamais dépasser 10 slots ni voler un slot CORE ; (3) le reste
des slots va au runtime existant (candidats par rotation) ; (4) deny-by-default sans journal.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("collecter_userfills_vaults", _ROOT / "tools" / "collecter_userfills_vaults.py")
U = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(U)


def _ecrire(root: Path, *, sentinelles=True, n_cands=12):
    d = root / "runtime" / "data"
    d.mkdir(parents=True)
    classement = [{"vault": "0xCORE1", "retenu": True, "facteurs": {}},
                  {"vault": "0xCORE2", "retenu": True, "facteurs": {}}]
    classement += [{"vault": "0xCAND%02d" % i, "retenu": False,
                    "facteurs": {"copyabilite": 0.9, "anciennete_j": 60, "drawdown_pct": 10}} for i in range(n_cands)]
    (d / "vaults_scores.json").write_text(json.dumps({"classement": classement}), encoding="utf-8")
    if sentinelles:
        recs = ([{"coin": "ETH", "hash": "a%d" % i, "vault": "0xLIQ1", "liquidatedUser": "0xVIC"} for i in range(47)]
                + [{"coin": "SOL", "hash": "b%d" % i, "vault": "0xLIQ2", "liquidatedUser": "0xVIC"} for i in range(19)]
                + [{"coin": "BTC", "hash": "c%d" % i, "vault": "0xLIQ3", "liquidatedUser": "0xVIC"} for i in range(3)])
        (d / "liquidations_confirmees.jsonl").write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
    return root


def test_charger_sentinelles_top_liquidateur(tmp_path):
    _ecrire(tmp_path)
    assert U.charger_sentinelles(tmp_path) == ["0xLIQ1", "0xLIQ2", "0xLIQ3"]


def test_sans_journal_aucune_sentinelle(tmp_path):
    _ecrire(tmp_path, sentinelles=False)
    assert U.charger_sentinelles(tmp_path) == []


def test_pinning_reserve_les_slots_sans_depasser_10(tmp_path):
    _ecrire(tmp_path)
    roles = U.vaults_et_roles(tmp_path)
    assert len(roles) <= U.MAX_SLOTS, "jamais plus de 10 slots"
    noms = [v for v, _r, _w in roles]
    # 2 CORE d'abord, puis les 3 sentinelles épinglées
    assert noms[:2] == ["0xCORE1", "0xCORE2"]
    sent = [v for v, r, _w in roles if r == "LIQUIDATOR_SENTINEL"]
    assert sent == ["0xLIQ1", "0xLIQ2", "0xLIQ3"], "les 3 top liquidateurs sont épinglés"
    # le reste = candidats runtime, total EXACTEMENT plafonné à 10
    assert len(roles) == U.MAX_SLOTS
    assert sum(1 for _v, r, _w in roles if r.startswith("CANDIDAT")) == U.MAX_SLOTS - 2 - 3


def test_sentinelle_ne_vole_pas_un_slot_core(tmp_path):
    # un CORE qui est AUSSI top liquidateur ne doit pas être compté deux fois
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    (d / "vaults_scores.json").write_text(json.dumps({"classement": [
        {"vault": "0xLIQ1", "retenu": True, "facteurs": {}},          # CORE ET top liquidateur
        {"vault": "0xCORE2", "retenu": True, "facteurs": {}}]}), encoding="utf-8")
    (d / "liquidations_confirmees.jsonl").write_text(
        "\n".join(json.dumps({"coin": "ETH", "hash": "a%d" % i, "vault": "0xLIQ1", "liquidatedUser": "0xVIC"})
                  for i in range(5)), encoding="utf-8")
    roles = U.vaults_et_roles(tmp_path)
    noms = [v for v, _r, _w in roles]
    assert noms.count("0xLIQ1") == 1, "pas de doublon CORE/sentinelle"
