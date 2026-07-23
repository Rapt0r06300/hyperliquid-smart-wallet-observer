"""COLLECTEUR D'ÉVÉNEMENTS DE LIQUIDATION (overshoot mark/oracle) — l'infra n°1 (23/07).

Le fade de liquidations était bloqué faute d'events. Ces tests prouvent qu'on CAPTURE l'overshoot
(mid vs oracle) + sa réversion, qu'on n'invente RIEN, qu'on exclut BTC (mort), et qu'une coupure
réseau ne tue pas la boucle. Aucun appel réseau réel : tout est bouchonné.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod():
    chemin = RACINE / "tools" / "collecter_overshoots.py"
    spec = importlib.util.spec_from_file_location("collecter_overshoots", chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ------------------------------------------------------------------ cœur PUR

def test_overshoot_bps_signe_et_garde():
    m = _mod()
    assert round(m.overshoot_bps(99.6, 100.0), 1) == -40.0     # mid SOUS l'oracle -> négatif (forced sell)
    assert round(m.overshoot_bps(100.4, 100.0), 1) == 40.0
    assert m.overshoot_bps(100.0, 0.0) is None                 # oracle absurde -> rien d'inventé


def test_parser_ctxs_apparie_universe_et_contextes_tolerant():
    m = _mod()
    payload = [{"universe": [{"name": "ETH"}, {"name": "SOL"}]},
               [{"oraclePx": "100.0", "markPx": "99.9"}, {"oraclePx": "5.0"}]]
    out = m.parser_ctxs(payload)
    assert out["ETH"] == {"oracle": 100.0, "mark": 99.9}
    assert out["SOL"]["oracle"] == 5.0 and out["SOL"]["mark"] == 5.0   # markPx absent -> = oracle
    assert m.parser_ctxs("nawak") == {}                        # illisible -> vide, pas d'exception


def test_detecter_flague_au_dessus_du_seuil_exclut_BTC():
    m = _mod()
    mids = {"ETH": 99.6, "SOL": 20.0, "BTC": 59000.0}
    ctxs = {"ETH": {"oracle": 100.0, "mark": 99.8},           # -40 bps -> retenu
            "SOL": {"oracle": 20.01, "mark": 20.0},           # -5 bps -> sous le seuil
            "BTC": {"oracle": 59300.0, "mark": 59100.0}}      # -50 bps MAIS BTC exclu (mort)
    ev = m.detecter(mids, ctxs)
    assert [e["coin"] for e in ev] == ["ETH"]
    assert ev[0]["sens"] == "SELL_OVERSHOOT"


def test_avancer_remplit_les_forward_et_calcule_la_reversion():
    m = _mod()
    ouverts = {"ETH": {"coin": "ETH", "ts0": 1000.0, "mid_at_event": 100.0, "oracle_px": 100.4,
                       "mark_px": 100.2, "overshoot_bps": -40.0, "sens": "SELL_OVERSHOOT"}}
    finis = m.avancer(ouverts, {"ETH": 100.2}, 1000.0 + max(m.HORIZONS_S))  # mid remonté vers l'oracle
    assert len(finis) == 1 and not ouverts                    # arrivé à terme -> retiré
    # fade d'un SELL_OVERSHOOT : le mid remonte (100.0 -> 100.2) = réversion POSITIVE
    assert finis[0]["reversion_bps"] > 0
    assert "mid_fwd_60s" in finis[0]


# ------------------------------------------------------------------ une passe (bouchonnée)

def test_une_passe_ouvre_puis_ecrit_a_terme(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "lire_ctxs", lambda **k: {"ETH": {"oracle": 100.0, "mark": 99.8}})
    monkeypatch.setattr(m, "lire_all_mids", lambda **k: {"ETH": 99.6})   # -40 bps -> événement
    ouverts: dict = {}
    assert m.une_passe(tmp_path, ouverts, now=1000.0) == 0     # ouvre, rien à terme encore
    assert "ETH" in ouverts
    # plus tard, le mid est revenu : l'événement arrive à terme et s'écrit
    monkeypatch.setattr(m, "lire_all_mids", lambda **k: {"ETH": 99.95})
    n = m.une_passe(tmp_path, ouverts, now=1000.0 + max(m.HORIZONS_S))
    assert n == 1 and not ouverts
    lignes = (tmp_path / m.SORTIE).read_text(encoding="utf-8").splitlines()
    ev = json.loads(lignes[0])
    assert ev["coin"] == "ETH" and ev["reversion_bps"] > 0 and ev["real_execution"] is False


def test_une_coupure_reseau_ne_tue_pas_la_passe(tmp_path, monkeypatch):
    m = _mod()

    def boom(**_k):
        raise OSError("reseau coupe")

    monkeypatch.setattr(m, "lire_ctxs", boom)
    assert m.une_passe(tmp_path, {}, now=1000.0) == 0          # 0 écrit, aucune exception


def test_resume_est_honnete_quand_vide(tmp_path):
    m = _mod()
    assert m.resume(tmp_path)["verdict"] == "AUCUN_OVERSHOOT_ENCORE_COLLECTE"
