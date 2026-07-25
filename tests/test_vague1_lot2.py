"""LOT 2 — 6 plugins de signal + REGIME_ROUTER prouvés sans réseau (Flo 25/07).

Détecteurs testés en direct (indépendants du registre global). Prouve : chaque détecteur émet le bon signal
sur données synthétiques, s'abstient sans data, respecte le régime ; total = 12 variantes (plafond).
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.research_parallel.plugins import vague1 as V


def _ctx(tmp_path, **extra):
    return {"root": str(tmp_path), **extra}


def test_douze_variantes_au_total():
    total = sum(len(p.variantes) for p in V._PLUGINS)
    assert total == 12, "6 plugins de signal × 2 variantes = 12 (le routeur a 0 variante)"


def test_residual_momentum_long_le_meilleur_short_le_pire(tmp_path):
    # BTC/ETH plats (marché nul) ; SOL monte fort (résidu +), DASH chute (résidu −)
    def s(v0, v1):
        return [(0.0, v0, v0 * 1.0001), (2_000_000.0, v1, v1 * 1.0001)]
    prix = {"BTC": s(100, 100), "ETH": s(100, 100), "SOL": s(10, 11), "DASH": s(50, 48),
            "INJ": s(20, 20.1), "NEO": s(9, 9)}
    sigs = V.residual_momentum(_ctx(tmp_path, _prix=prix))
    court = [x for x in sigs if x["variante"] == "RESMOM_COURT"]
    longs = {x["coin"]: x["sens"] for x in court}
    assert longs.get("SOL") == 1 and longs.get("DASH") == -1, "long le meilleur résidu, short le pire"


def test_absorption_emet_fade_et_follow(tmp_path):
    trades = {"SOL": [(i * 100.0, +3.0) for i in range(30)]}      # flux agressif ACHETEUR massif
    prix = {"SOL": [(2900.0, 10.0, 10.001), (3000.0, 10.0, 10.001)]}   # prix immobile -> absorption
    sigs = V.absorption(_ctx(tmp_path, _trades=trades, _prix=prix))
    vars_ = {x["variante"]: x["sens"] for x in sigs}
    assert "ABSORB_FADE" in vars_ and "ABSORB_FOLLOW" in vars_
    assert vars_["ABSORB_FADE"] == -1 and vars_["ABSORB_FOLLOW"] == 1, "fade contre l'acheteur, follow avec"


def test_absorption_s_abstient_sans_trades(tmp_path):
    assert V.absorption(_ctx(tmp_path)) == []


def test_oi_crowding_continuation(tmp_path):
    ctx = [{"coin": "SOL", "oi": 1000, "premium_bps": 5, "ts_wall_ms": 0},
           {"coin": "SOL", "oi": 1010, "premium_bps": 20, "ts_wall_ms": 60000},
           {"coin": "SOL", "oi": 1060, "premium_bps": 40, "ts_wall_ms": 120000}]   # OI accélère + premium 40
    sigs = V.oi_crowding(_ctx(tmp_path, _asset_ctx=ctx))
    assert len(sigs) == 2 and all(s["sens"] == 1 for s in sigs), "premium+ extrême + OI accélère -> continuation long"


def test_funding_clock_sur_changement_de_signe(tmp_path):
    ctx = [{"coin": "ETH", "funding": 0.0002, "ts_wall_ms": 0},
           {"coin": "ETH", "funding": -0.0001, "ts_wall_ms": 3600_000}]            # signe flip + -> −
    sigs = V.funding_clock(_ctx(tmp_path, _asset_ctx=ctx))
    assert len(sigs) == 2 and all(s["sens"] == 1 for s in sigs)                    # funding devient négatif -> biais long


def test_oi_cap_event_enter_et_exit(tmp_path):
    recs = [{"coins_au_cap": ["BTC", "SOL"], "ts_wall_ms": 0},
            {"coins_au_cap": ["BTC", "AVAX"], "ts_wall_ms": 60000}]                # SOL sort, AVAX entre
    sigs = {s["coin"]: (s["variante"], s["sens"]) for s in V.oi_cap_event(_ctx(tmp_path, _oi_cap=recs))}
    assert sigs["AVAX"] == ("OICAP_ENTER", 1) and sigs["SOL"] == ("OICAP_EXIT", -1)


def test_hlp_pressure_sur_variation_inventaire(tmp_path):
    recs = [{"coin": "BTC", "szi": 5.0, "ts_wall_ms": 0}, {"coin": "BTC", "szi": 9.0, "ts_wall_ms": 60000}]
    sigs = V.hlp_pressure(_ctx(tmp_path, _hlp=recs))
    assert len(sigs) == 2 and all(s["sens"] == 1 for s in sigs), "HLP accumule long -> flux forcé vendeur -> fade long"


def test_regime_router_coupe_absorption_si_spread_large(tmp_path):
    V.ISO.preparer(tmp_path)
    # spread large (~30 bps) sur les majors -> ABSORPTION retiré des autorisés
    large = {c: [(i * 5000.0, 100.0, 100.30) for i in range(60)] for c in ("BTC", "ETH", "SOL")}
    V.router_regime(_ctx(tmp_path, _prix=large))
    reg = json.loads((tmp_path / "runtime" / "research_lab" / "data" / "regime.json").read_text())
    assert "ABSORPTION_FRAGILITY" not in reg["autorises"], "carnet large -> pas d'absorption fine"
    # un plugin gate par le régime s'abstient alors
    assert V.absorption(_ctx(tmp_path, _trades={"SOL": [(i, 3.0) for i in range(30)]},
                             _prix={"SOL": [(0, 10, 10.001), (1, 10, 10.001)]})) == []


def test_regime_permissif_par_defaut(tmp_path):
    # sans regime.json, autorise() rend True -> les détecteurs à data disponible peuvent émettre
    assert V.K.autorise(V.K.regime_courant(tmp_path), "RESIDUAL_MOMENTUM") is True
