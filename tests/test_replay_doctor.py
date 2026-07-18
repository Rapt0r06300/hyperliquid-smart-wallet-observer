"""Cluster W — le DOCTEUR REPLAY rend le « 1 sur 1M » IMPOSSIBLE en silence.

E2E (W11) : deux shards PAR-PID (le vrai bug) → `charger_replay_depuis_base` AGRÈGE les deux
(W1/W2) → diagnostic SUFFISANT (W6) → `run_ab_replay` produit de VRAIS trades sur les données
chargées. Direction inverse : base vide → diagnostic INSUFFISANT → `exiger_suffisant` LÈVE (W3).
Aucune donnée réseau. REPLAY only."""
from __future__ import annotations

import json

import pytest

from hl_observer.backtesting.ab_flag_replay import run_ab_replay
from hl_observer.backtesting.replay_doctor import (
    DonneesReplayInsuffisantes, charger_replay_depuis_base, cout_total_bps, diagnostiquer,
    diagnostiquer_base, exiger_suffisant, gagnant_robuste, trier_deterministe,
)

COINS = ("BTC", "ETH", "SOL")
BASE_TS = 1_700_000_000.0


def _ecrire_shard(base, filename, rows):
    p = base / filename
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _fixture_deux_shards(base):
    """240 candidats (2 shards) + 600 marks (2 shards), marks POSTÉRIEURS aux candidats (mesurables)."""
    cand_a, cand_b, mark_a, mark_b = [], [], [], []
    for i in range(120):
        for shard, cands in ((0, cand_a), (1, cand_b)):
            coin = COINS[(i + shard) % len(COINS)]
            ts = BASE_TS + (i * 10) + shard
            cands.append({"coin": coin, "direction": "LONG" if i % 2 == 0 else "SHORT",
                          "current_mid": 100.0 + (i % 7), "recorded_at": ts,
                          "edge_remaining_bps": 45.0})
    for coin in COINS:
        for k in range(200):                        # 200 × 3 coins = 600 marks (> seuil 500)
            t = BASE_TS + k * 60.0
            mid = 100.0 + (k % 11) * 0.3            # variation -> TP/SL peuvent se déclencher
            (mark_a if k % 2 == 0 else mark_b).append({"coin": coin, "ts": t, "mid": mid})
    _ecrire_shard(base, "candidates.1001.jsonl", cand_a)
    _ecrire_shard(base, "candidates.2002.jsonl", cand_b)
    _ecrire_shard(base, "marks.1001.jsonl", mark_a)
    _ecrire_shard(base, "marks.2002.jsonl", mark_b)


# ============================ W1/W2 — agrégation des shards par-PID ============================

def test_w2_charge_agrege_les_deux_shards(tmp_path):
    _fixture_deux_shards(tmp_path)
    cands, marks = charger_replay_depuis_base(str(tmp_path))
    assert len(cands) == 240, "les DEUX shards de candidats doivent être agrégés"
    assert len(marks) == 600, "les DEUX shards de marks doivent être agrégés"


# ============================ W6 — diagnostic de santé ============================

def test_w6_diagnostic_suffisant_sur_donnees_reelles(tmp_path):
    _fixture_deux_shards(tmp_path)
    rapport = diagnostiquer_base(str(tmp_path))
    assert rapport.suffisant is True and not rapport.raisons
    assert rapport.n_candidats == 240 and rapport.n_marks == 600
    assert rapport.couverture_marks == 1.0        # tous les coins candidats ont des marks


# ============================ W3 — échec BRUYANT sur données absentes ============================

def test_w3_base_vide_leve_bruyamment(tmp_path):
    rapport = diagnostiquer_base(str(tmp_path))      # base vide
    assert rapport.suffisant is False
    with pytest.raises(DonneesReplayInsuffisantes):
        exiger_suffisant(rapport)


def test_w3_marks_absents_leve_meme_avec_candidats(tmp_path):
    # candidats présents mais AUCUN mark -> couverture 0 -> le "1 sur 1M" : on LÈVE, pas de résultat.
    _ecrire_shard(tmp_path, "candidates.1.jsonl",
                  [{"coin": "BTC", "direction": "LONG", "current_mid": 100.0,
                    "recorded_at": BASE_TS + i, "edge_remaining_bps": 40.0} for i in range(300)])
    rapport = diagnostiquer_base(str(tmp_path))
    assert rapport.suffisant is False
    assert any("MARKS" in r or "COUVERTURE" in r for r in rapport.raisons)
    with pytest.raises(DonneesReplayInsuffisantes):
        exiger_suffisant(rapport)


# ============================ W11 — E2E : données chargées -> VRAIS trades ============================

def test_w11_e2e_donnees_chargees_produisent_de_vrais_trades(tmp_path):
    _fixture_deux_shards(tmp_path)
    cands, marks = charger_replay_depuis_base(str(tmp_path))
    exiger_suffisant(diagnostiquer(cands, marks))       # ne lève pas : données suffisantes
    res = run_ab_replay(cands, marks)
    # le bras baseline (V26 OFF) DOIT produire des trades mesurables sur les marks réels
    assert res["arm_a"]["trades"] > 0, "données chargées mais 0 trade = le bug du '1 sur 1M'"


# ============================ W7 — les flags sont réellement injectés dans le bras B ============================

def test_w7_flags_threades_dans_le_bras_b(tmp_path):
    _fixture_deux_shards(tmp_path)
    cands, marks = charger_replay_depuis_base(str(tmp_path))
    res = run_ab_replay(cands, marks, arm_b_env={"HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE": "0"})
    # le flag passé se retrouve dans l'env du bras B rejoué -> les flags ne sont pas ignorés
    assert res["arm_b_env"]["HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE"] == "0"
    assert res["recommendation"] in ("ACTIVATE_B", "KEEP_A")


# ============================ W8 — gagnant robuste (pas 1 trade chanceux) ============================

def test_w8_gagnant_a_trop_peu_de_trades_rejete():
    assert gagnant_robuste(1) is False        # 1 trade = chance
    assert gagnant_robuste(29) is False
    assert gagnant_robuste(30) is True        # seuil de crédibilité


# ============================ W9 — déterminisme ============================

def test_w9_tri_deterministe_reproductible():
    cands = [{"coin": "ETH", "recorded_at": 3, "ts": 0}, {"coin": "BTC", "recorded_at": 1, "ts": 0},
             {"coin": "BTC", "recorded_at": 2, "ts": 0}]
    ordre1 = [c["coin"] + str(c["recorded_at"]) for c in trier_deterministe(cands)]
    ordre2 = [c["coin"] + str(c["recorded_at"]) for c in trier_deterministe(list(reversed(cands)))]
    assert ordre1 == ordre2 == ["BTC1", "BTC2", "ETH3"]


# ============================ W10 — fidélité des coûts ============================

def test_w10_cout_total_somme_des_composantes():
    c = cout_total_bps(fees_bps=3.0, spread_bps=2.0, slippage_bps=1.5, copy_degradation_bps=4.0)
    assert abs(c - 10.5) < 1e-9
    assert cout_total_bps() == 0.0
    assert cout_total_bps(fees_bps=-5.0) == 0.0     # jamais négatif
