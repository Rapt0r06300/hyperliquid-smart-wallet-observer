"""OI_PREMIUM_CROWDING_V1 — collecteur ctx + cœur pur prouvés sans réseau (Flo 25/07).

Prouve : (1) le parser ctx extrait OI/premium/funding/volume et écarte les coins illisibles ; (2) le
collecteur archive avec un poster mocké (0 réseau) ; (3) les 3 détecteurs émettent le bon signal
point-in-time ; (4) l'exécution est au bid/ask réel (NON_MESURABLE si figé) ; (5) décision SCALE/SHADOW/KILL.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from hl_observer.experimental import oi_premium_crowding as OP

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("cac", _ROOT / "tools" / "collecter_asset_ctx.py")
CAC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CAC)


# ── collecteur ctx ──
def _payload():
    return [{"universe": [{"name": "BTC"}, {"name": "SOL"}, {"name": "BAD"}]},
            [{"oraclePx": "100.0", "markPx": "100.5", "openInterest": "1000", "funding": "0.0001",
              "dayNtlVlm": "5000000", "impactPxs": ["99.9", "100.1"]},
             {"oraclePx": "10.0", "markPx": "9.95", "openInterest": "200", "funding": "-0.0002",
              "dayNtlVlm": "800000", "impactPxs": ["9.94", "9.96"]},
             {"markPx": "1.0"}]]      # BAD : pas d'oraclePx -> écarté


def test_parser_ctx_extrait_les_champs():
    d = CAC.parser_ctx_complet(_payload())
    assert set(d) == {"BTC", "SOL"}, "BAD (sans oracle) écarté (vérité des données)"
    assert d["BTC"]["oi"] == 1000.0 and d["BTC"]["premium_bps"] == 50.0    # (100.5-100)/100*1e4
    assert d["SOL"]["premium_bps"] == -50.0 and d["SOL"]["vol24h"] == 800000.0


def test_collecteur_archive_avec_poster_mocke(tmp_path):
    n = CAC.une_passe(tmp_path, poster=lambda charge: _payload(), now=1000.0)
    assert n == 2
    lignes = [json.loads(l) for l in (tmp_path / CAC.TAPE).read_text(encoding="utf-8").splitlines()]
    assert len(lignes) == 2 and all(l["real_execution"] is False for l in lignes)
    assert {l["coin"] for l in lignes} == {"BTC", "SOL"}
    assert (tmp_path / CAC.HEARTBEAT).exists()


def test_reseau_ko_archive_rien(tmp_path):
    def _ko(_):
        raise OSError("réseau")
    assert CAC.une_passe(tmp_path, poster=_ko, now=1.0) == 0


# ── détecteurs point-in-time ──
def _ctx(ts, oi, prem, mark):
    return {"ts_ms": ts, "oi": oi, "premium_bps": prem, "mark": mark}


def test_H1_continuation_oi_hausse_premium_extreme():
    # OI +5 % + premium +30 bps -> continuation haussière (sens +1)
    serie = [_ctx(0, 1000, 2.0, 100.0), _ctx(400_000, 1050, 30.0, 100.3)]
    sig = OP.detecter("H1", serie)
    assert len(sig) == 1 and sig[0]["sens"] == 1


def test_H2_reversal_chute_oi_premium_compresse():
    # OI −5 % + premium résiduel +3 bps (compressé) -> reversal baissier (fade le premium+, sens −1)
    serie = [_ctx(0, 1000, 20.0, 100.0), _ctx(400_000, 950, 3.0, 100.0)]
    sig = OP.detecter("H2", serie)
    assert len(sig) == 1 and sig[0]["sens"] == -1


def test_H3_squeeze_chute_oi_move_violent():
    # OI −5 % + mark +50 bps sur la fenêtre -> squeeze haussier (sens +1)
    serie = [_ctx(0, 1000, 5.0, 100.0), _ctx(400_000, 950, 5.0, 100.5)]
    sig = OP.detecter("H3", serie)
    assert len(sig) == 1 and sig[0]["sens"] == 1


def test_pas_de_signal_sans_declencheur():
    serie = [_ctx(0, 1000, 2.0, 100.0), _ctx(400_000, 1005, 2.0, 100.0)]   # OI ~plat, premium faible
    assert OP.detecter("H1", serie) == [] and OP.detecter("H3", serie) == []


# ── exécution bid/ask réelle ──
def test_execution_bid_ask_et_fraicheur():
    prix = [(400_000, 99.99, 100.01), (400_000 + 300_000, 100.49, 100.51)]   # +300s le prix monte
    tr = OP.executer([{"ts_ms": 400_000, "sens": 1}], prix, horizon_s=300, fee_ar_bps=0.0, slippage_bps=0.0)
    assert len(tr) == 1 and tr[0]["brut_bps"] > 0     # long qui gagne quand ça monte, au bid/ask
    # sortie figée (pas de cotation à l'horizon) -> aucun trade
    tr2 = OP.executer([{"ts_ms": 400_000, "sens": 1}], [prix[0]], horizon_s=300)
    assert tr2 == []


# ── décision ──
def _t(ts, net):
    return {"ts_ms": ts, "sens": 1, "net_bps": net}


def test_decision_kill_si_pf_sous_1():
    trades = [_t(i, 3.0) for i in range(10)] + [_t(10 + i, -6.0) for i in range(15)]
    assert OP.decision(trades)["decision"] == "KILL"


def test_decision_scale_si_robuste():
    trades = [_t(i, 5.0) for i in range(24)]
    r = OP.decision(trades)
    assert r["decision"] == "SCALE" and r["median_sans_meilleur_bps"] > 0


def test_decision_shadow_si_trop_peu_de_trades():
    assert OP.decision([_t(i, 5.0) for i in range(8)])["decision"] == "SHADOW"
