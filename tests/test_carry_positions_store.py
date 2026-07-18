"""Tests de la persistance disque de l'ETAPE 2 : positions ouvertes + ledger PnL realise."""
from __future__ import annotations

import json

from hl_observer.funding.carry_positions_store import (
    charger_gestionnaire, tick_sur_disque, resume_depuis_ledger,
    POSITIONS_RELPATH, LEDGER_RELPATH,
)

H = 3_600_000


def _decision(viable=True, **kw):
    d = {"coin": "HYPE", "funding_bps_h": 0.125, "base_bps": -0.68, "liquidite_spot_usd": 200_000.0,
         "cout_entree_bps": 9.0, "viable": viable, "motif": "CARRY_NEUTRE_VIABLE"}
    d.update(kw)
    return d


def _inputs(**kw):
    d = {"ts_ms": 1, "coin": "HYPE", "funding_bps_h": 0.125, "base_bps": -0.68,
         "liquidite_spot_usd": 200_000.0, "maker": True, "levier_max": 10.0,
         "marge_ratio": 0.5, "pire_hausse_observee": 0.29, "levier_utilise": 2.0}
    d.update(kw)
    return d


def test_ouverture_persiste_puis_recharge(tmp_path):
    e = tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    assert e["ouvert"] is True
    assert (tmp_path / POSITIONS_RELPATH).exists()
    # un NOUVEAU processus recharge la meme position
    g = charger_gestionnaire(tmp_path)
    assert "HYPE" in g.ouvertes
    assert g.ouvertes["HYPE"]["notional_usdt"] == 100.0


def test_cycle_complet_ouvre_accrue_ferme_et_ledger(tmp_path):
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    # accrue 200h (dans la fenetre d'age 336h, mais au-dela du break-even ~160h), puis funding->0
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=200 * H, funding_bps_h_courant=0.125)
    e = tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=201 * H, funding_bps_h_courant=0.0)
    assert e["ferme"] == "FUNDING_NON_RENTABLE"
    assert e["pnl_realise_usdt"] > 0.0                     # 200h de funding > frais
    # plus aucune position ouverte, et le ledger contient OPEN + CLOSE
    assert charger_gestionnaire(tmp_path).ouvertes == {}
    r = resume_depuis_ledger(tmp_path)
    assert r["opens"] == 1 and r["closes"] == 1
    assert r["realized_net_pnl_usdc"] == e["pnl_realise_usdt"]


def test_ledger_est_append_only(tmp_path):
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=5001 * H, funding_bps_h_courant=0.0)
    lignes = (tmp_path / LEDGER_RELPATH).read_text(encoding="utf-8").strip().splitlines()
    kinds = [json.loads(l)["kind"] for l in lignes]
    assert kinds == ["OPEN", "CLOSE"]


def test_un_coin_une_position_pas_de_doublon(tmp_path):
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=H, funding_bps_h_courant=0.125)
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=2 * H, funding_bps_h_courant=0.125)
    assert len(charger_gestionnaire(tmp_path).ouvertes) == 1
    assert resume_depuis_ledger(tmp_path)["opens"] == 1     # une seule ouverture

def test_mode_different_repart_vide_jamais_de_melange(tmp_path):
    # on ouvre en LIVE...
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125, mode="LIVE")
    # ...un chargement TEST_FIXTURE ne doit PAS voir la position LIVE
    g = charger_gestionnaire(tmp_path, mode="TEST_FIXTURE")
    assert g.ouvertes == {}
    # et le resume par mode ne melange pas
    assert resume_depuis_ledger(tmp_path, mode="TEST_FIXTURE")["opens"] == 0
    assert resume_depuis_ledger(tmp_path, mode="LIVE")["opens"] == 1
