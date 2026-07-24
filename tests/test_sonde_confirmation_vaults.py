"""Sonde de confirmation WS (diagnostic transport, lecture seule — rectif Flo 24/07).

On teste le CŒUR PUR sans réseau : classement d'un message (ACK / SNAPSHOT / FILL / rien), normalisation
REST via le parser WS, détection « REST voit un fill que le WS a raté » (curseur), et le verdict global.
Aucun abonnement réel, aucun ordre : diagnostic de transport seulement.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = _mod("sonde_confirmation_vaults")

V = "0xAbCdEf0123456789000000000000000000000000"
VLC = V.lower()


def test_classer_ack_subscription_response():
    m = {"channel": "subscriptionResponse", "data": {"subscription": {"type": "userFills", "user": V.upper()}}}
    assert S.classer_message(m, VLC) == "ACK"                     # ACK insensible à la casse du user


def test_classer_snapshot_exige_is_snapshot_true():
    m = {"channel": "userFills", "data": {"user": V, "isSnapshot": True, "fills": []}}
    assert S.classer_message(m, VLC) == "SNAPSHOT"               # 1er userFills snapshot = confirmé


def test_classer_fill_live_est_preuve_forte():
    m = {"channel": "userFills", "data": {"user": V, "isSnapshot": False, "fills": [{"coin": "SOL"}]}}
    assert S.classer_message(m, VLC) == "FILL"                    # un vrai fill live confirme aussi (plus fort)


def test_classer_ignore_autre_user_et_autre_canal():
    assert S.classer_message({"channel": "userFills", "data": {"user": "0xZZZ", "isSnapshot": True}}, VLC) is None
    assert S.classer_message({"channel": "l2Book", "data": {"coin": "SOL"}}, VLC) is None
    assert S.classer_message({"channel": "subscriptionResponse",
                              "data": {"subscription": {"type": "l2Book", "coin": "SOL"}}}, VLC) is None
    assert S.classer_message("pas un dict", VLC) is None          # tolérant


def test_fills_rest_normalises_via_parser_ws():
    rep = [{"coin": "sol", "px": "150.0", "sz": "2", "time": 1000, "side": "B", "hash": "h1"}]
    fr = S.fills_rest_normalises(V, rep)
    assert len(fr) == 1 and fr[0]["coin"] == "SOL" and fr[0]["ts_ms"] == 1000 and fr[0]["hash"] == "h1"
    assert S.fills_rest_normalises(V, "pas une liste") == []      # illisible -> [] (jamais inventé)


def test_retard_detecte_fill_plus_recent_que_curseur_et_assez_vieux():
    now = 10_000_000.0
    fills = S.fills_rest_normalises(V, [{"coin": "SOL", "px": "1", "sz": "1", "time": int(now - 60_000), "hash": "hx"}])
    # curseur = now-120s : le fill (now-60s) est plus récent que le curseur ET vieux de 60s (≥ 45s) -> RETARD
    retard = S.fills_rest_en_retard(fills, now - 120_000, maintenant_ms=now)
    assert len(retard) == 1                                       # le WS a raté un fill que REST voit -> défaillant


def test_retard_ignore_fill_trop_frais_anticourse():
    now = 10_000_000.0
    fills = S.fills_rest_normalises(V, [{"coin": "SOL", "px": "1", "sz": "1", "time": int(now - 5_000), "hash": "hy"}])
    # fill de 5s : le WS n'a pas forcément eu le temps -> PAS d'accusation (anti-course)
    assert S.fills_rest_en_retard(fills, now - 120_000, maintenant_ms=now) == []


def test_retard_sans_curseur_n_accuse_pas_sur_historique():
    now = 10_000_000.0
    fills = S.fills_rest_normalises(V, [{"coin": "SOL", "px": "1", "sz": "1", "time": int(now - 200_000), "hash": "hz"}])
    assert S.fills_rest_en_retard(fills, None, maintenant_ms=now) == []   # curseur absent -> [] (pas de faux défaut)
    assert S.fills_rest_en_retard(fills, 0, maintenant_ms=now) == []


def test_verdict_global_compte_confirmes_pending_et_defauts():
    res = [{"vault": "0x1", "verdict": "ACK"}, {"vault": "0x2", "verdict": "SNAPSHOT"},
           {"vault": "0x3", "verdict": "TIMEOUT"}, {"vault": "0x4", "verdict": "TIMEOUT", "shard_defaillant": True}]
    vg = S.verdict_global(res)
    assert vg["n_total"] == 4 and vg["n_confirmes"] == 2 and vg["n_pending"] == 2
    assert vg["confirmes"] == ["0x1", "0x2"] and vg["pending"] == ["0x3", "0x4"]
    assert vg["shards_defaillants"] == ["0x4"]                    # PENDING + REST voit un fill raté = défaut


def test_intervalle_debit_reste_sous_le_plafond():
    # avec marge ×2, 30/min -> 4 s entre connexions -> effectif 15/min << 30 (largement sous le plafond)
    assert S.intervalle_debit_s(30, marge=2.0) == 4.0
    assert 60.0 / S.intervalle_debit_s(30, marge=2.0) <= 30
