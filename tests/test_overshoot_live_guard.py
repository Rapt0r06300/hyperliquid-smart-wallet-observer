"""Garde overshoot live : relie le champion déployé au flux asset_ctx réel.

Garde-fous vérifiés : OFF sans opt-in (ne lit même pas la tape), bloque le coin en
débordement quand opt-in, causal, fail-open.
"""
from __future__ import annotations

import json

from hl_observer.backtesting.copy_vault_local_lab import (
    CHEMIN_CHAMPION_DEPLOYE,
    _ecrire_champion_deploye,
)
from hl_observer.copy_mode import overshoot_live_guard as G


def _deploie_champion(root, seuil):
    best = {
        "candidate_id": "c1",
        "candidate": {"overshoot_seuil_bps": seuil},
        "score_usd_per_active_day": "1",
        "train": {"daily_mean_net_pnl_usd": 1.0},
        "trial_number": 1,
    }
    _ecrire_champion_deploye(root, best)


def _ecrire_tape(root, lignes):
    tape = root.joinpath(*G.TAPE_REL)
    tape.parent.mkdir(parents=True, exist_ok=True)
    tape.write_text("\n".join(json.dumps(x) for x in lignes) + "\n", encoding="utf-8")


def test_inerte_sans_opt_in_ne_lit_pas_la_tape(tmp_path, monkeypatch):
    G.vider_cache()
    monkeypatch.delenv("HL_APPLY_CHAMPION", raising=False)
    _deploie_champion(tmp_path, 100.0)
    # tape présente avec gros overshoot, mais sans opt-in -> garde inerte
    _ecrire_tape(tmp_path, [{"ts_ms": 1000, "coin": "BTC", "mark": 110.0, "oracle": 100.0}])
    garde = G.charger_garde(tmp_path)
    assert garde.actif() is False
    assert garde.bloque("BTC", 2000) == (False, None)


def test_bloque_le_coin_en_debordement_avec_opt_in(tmp_path, monkeypatch):
    G.vider_cache()
    monkeypatch.setenv("HL_APPLY_CHAMPION", "1")
    _deploie_champion(tmp_path, 100.0)  # seuil 100 bps
    _ecrire_tape(tmp_path, [
        {"ts_ms": 1000, "coin": "BTC", "mark": 103.0, "oracle": 100.0},  # +300 bps
        {"ts_ms": 1000, "coin": "ETH", "mark": 50.0, "oracle": 50.0},    # 0 bps
    ])
    garde = G.charger_garde(tmp_path)
    assert garde.actif() is True
    bloque_btc, ov_btc = garde.bloque("BTC", 2000)
    assert bloque_btc is True and round(ov_btc) == 300
    assert garde.bloque("ETH", 2000) == (False, 0.0)
    # coin inconnu -> fail-open
    assert garde.bloque("DOGE", 2000) == (False, None)


def test_causal_pas_de_futur(tmp_path, monkeypatch):
    G.vider_cache()
    monkeypatch.setenv("HL_APPLY_CHAMPION", "1")
    _deploie_champion(tmp_path, 100.0)
    _ecrire_tape(tmp_path, [
        {"ts_ms": 1000, "coin": "BTC", "mark": 100.0, "oracle": 100.0},  # 0
        {"ts_ms": 3000, "coin": "BTC", "mark": 110.0, "oracle": 100.0},  # +1000 (futur)
    ])
    garde = G.charger_garde(tmp_path)
    # à t=2000 l'overshoot causal est 0 -> pas bloqué malgré le pic futur
    assert garde.bloque("BTC", 2000)[0] is False


def test_seuil_off_grand_rend_inerte(tmp_path, monkeypatch):
    G.vider_cache()
    monkeypatch.setenv("HL_APPLY_CHAMPION", "1")
    _deploie_champion(tmp_path, 1_000_000.0)  # valeur « off »
    _ecrire_tape(tmp_path, [{"ts_ms": 1000, "coin": "BTC", "mark": 200.0, "oracle": 100.0}])
    garde = G.charger_garde(tmp_path)
    assert garde.actif() is False


def test_fail_open_si_tape_absente(tmp_path, monkeypatch):
    G.vider_cache()
    monkeypatch.setenv("HL_APPLY_CHAMPION", "1")
    _deploie_champion(tmp_path, 100.0)
    # pas de tape écrite -> index vide, garde actif mais ne bloque rien
    garde = G.charger_garde(tmp_path)
    assert garde.actif() is True
    assert garde.bloque("BTC", 2000) == (False, None)


def test_cache_ttl_reutilise(tmp_path, monkeypatch):
    G.vider_cache()
    monkeypatch.setenv("HL_APPLY_CHAMPION", "1")
    _deploie_champion(tmp_path, 100.0)
    _ecrire_tape(tmp_path, [{"ts_ms": 1000, "coin": "BTC", "mark": 103.0, "oracle": 100.0}])
    g1 = G.charger_garde(tmp_path, maintenant_s=0.0)
    # même fenêtre TTL -> même objet (pas de relecture)
    g2 = G.charger_garde(tmp_path, maintenant_s=1.0)
    assert g1 is g2
    # au-delà du TTL -> reconstruit
    g3 = G.charger_garde(tmp_path, maintenant_s=G.TTL_S + 1.0)
    assert g3 is not g1
