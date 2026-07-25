"""LIQUIDATION_LIVE_COVERAGE_V1 — la couverture BBO couvre les coins où les liquidations arrivent.

Prouve : coins_couverture = majors + les K coins les plus fréquents du journal de liquidations confirmées,
dédupliqué, borné, relu à chaque appel (nouveau coin de liquidation -> entre dans la couverture).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("collecter_bbo", _ROOT / "tools" / "collecter_bbo.py")
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)


def test_majors_seuls_si_pas_de_journal(tmp_path):
    coins = B.coins_couverture(tmp_path)
    assert coins == list(B.MAJORS_BBO), "sans journal : uniquement les majors (deny-by-default)"


def test_ajoute_les_coins_frequents_des_liquidations(tmp_path):
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    recs = [{"coin": "ONDO"}] * 5 + [{"coin": "AAVE"}] * 3 + [{"coin": "HYPE"}] * 2 + [{"coin": "BTC"}] * 4
    (d / "liquidations_confirmees.jsonl").write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
    coins = B.coins_couverture(tmp_path, k=16)
    assert set(B.MAJORS_BBO) <= set(coins), "les majors restent couverts"
    for c in ("ONDO", "AAVE", "HYPE"):
        assert c in coins, "%s (coin de liquidation frequent) doit etre couvert" % c
    assert coins.count("BTC") == 1, "pas de doublon (BTC est deja un major)"


def test_borne_a_majors_plus_k(tmp_path):
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    recs = [{"coin": "C%02d" % i} for i in range(40)]        # 40 coins distincts
    (d / "liquidations_confirmees.jsonl").write_text("\n".join(json.dumps(r) for r in recs), encoding="utf-8")
    coins = B.coins_couverture(tmp_path, k=5)
    assert len(coins) <= len(B.MAJORS_BBO) + 5, "borne majors + K (jamais illimite)"
