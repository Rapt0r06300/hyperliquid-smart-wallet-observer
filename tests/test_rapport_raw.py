"""Watcher léger (rectif Flo 23/07) : rapport du 1er OPEN/CLOSE RAW_PROBE depuis le ledger. On prouve :
rien tant qu'aucun OPEN ; OPEN seul -> position ouverte ; OPEN+CLOSE de la MÊME paire -> ROI. PUR."""
from __future__ import annotations

import json

from hl_observer.experimental import rapport_raw as RR


def _ledger(root, events):
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / RR.LEDGER_RELPATH).write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")


def test_rien_tant_qu_aucun_open(tmp_path):
    assert RR.construire_rapport(tmp_path) is None                  # jamais inventé
    _ledger(tmp_path, [{"evt": "REDUCE", "coin": "WLD"}])
    assert RR.construire_rapport(tmp_path) is None                  # pas d'OPEN -> rien


def test_open_seul_position_ouverte(tmp_path):
    _ledger(tmp_path, [{"evt": "OPEN", "paire": "0xV|WLD", "coin": "WLD", "vault": "0xV", "sens": -1,
                        "notional_usd": 10.0, "prix_entree": 0.38, "src_l2": "on_demand", "statut": "NON_VALIDEE",
                        "edge_net_bps": None, "run_id": "run-x",
                        "latences_mono": {"ws_open_ms": 240.0, "age_event_ms": -900}}])
    txt = RR.construire_rapport(tmp_path)
    assert txt and "0xV|WLD" in txt and "SHORT" in txt and "encore OUVERTE" in txt
    p = RR.ecrire_rapport(tmp_path)
    assert p and p.exists()


def test_open_puis_close_donne_roi(tmp_path):
    _ledger(tmp_path, [
        {"evt": "OPEN", "paire": "0xV|WLD", "coin": "WLD", "vault": "0xV", "sens": 1, "notional_usd": 10.0,
         "prix_entree": 0.38, "src_l2": "on_demand", "statut": "NON_VALIDEE", "run_id": "run-x",
         "latences_mono": {"ws_open_ms": 210.0}},
        {"evt": "CLOSE", "coin": "WLD", "vault": "0xV", "prix_sortie": 0.40, "realized_usd": 0.50,
         "raison": "LEADER_A_CLOS", "mae_bps": -4.0, "mfe_bps": 15.0}])
    op, cl = RR.premier_open_close(tmp_path)
    assert op and cl and cl["coin"] == "WLD"
    txt = RR.construire_rapport(tmp_path)
    assert "CLÔTURE" in txt and "ROI" in txt and "5.0" in txt        # 0.50 / 10 * 100 = 5.0 %
