"""CARRY CROSS-VENUE paper (23/07, Flo : « go » puis « fais en sorte qu'on gagne de l'argent »).

Ces tests prouvent : le mécanisme delta-neutre encaisse le premium de funding tant qu'il tient, paie
les coûts RÉELS du carnet (jamais un forfait), refuse ce qu'on ne peut pas coster, écrit dans le PnL
unifié, et n'invente RIEN. Aucun ordre réel : tout est simulé sur données bouchonnées.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.funding.cross_venue_carry_paper import (
    HOLD_MAX_H, MARGE_BREAK_EVEN, NOTIONAL_USD, backtest, couts_carnet, dernier_funding, tick)


def _dispersion(root: Path, rows: list[dict]) -> None:
    p = root / "runtime" / "data" / "dispersion_venues.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _carnet(root: Path, rows: list[dict]) -> None:
    p = root / "runtime" / "data" / "carnet_venues.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _ledger(root: Path) -> list[dict]:
    p = root / "runtime" / "data" / "carry_paper_ledger.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def _spread(coin: str, hl: float, bn: float) -> dict:
    return {"coin": coin, "hl_demi_spread_bps": hl, "bin_demi_spread_bps": bn}


# ------------------------------------------------------------------ le COÛT vient du carnet RÉEL

def test_le_cout_est_l_aller_retour_des_DEUX_jambes_pas_un_forfait(tmp_path):
    _carnet(tmp_path, [_spread("BTC", 2.0, 1.5)])
    # 2 × (demi_spread_HL + demi_spread_Binance) = 2 × (2.0 + 1.5) = 7.0
    assert couts_carnet(tmp_path)["BTC"] == 7.0


def test_funding_perime_n_est_pas_lu(tmp_path):
    _dispersion(tmp_path, [{"ts": 1000.0, "coin": "BTC", "hl_bps_h": 0.2, "bin_bps_h": 0.0}])
    assert dernier_funding(tmp_path, now=1000.0 + 1000.0) == {}      # > 15 min -> écarté


# ------------------------------------------------------------------ OUVERTURE : portes dures

def test_ouvre_un_premium_qui_amortit_le_cout(tmp_path):
    _carnet(tmp_path, [_spread("BTC", 2.0, 2.0)])                    # cout_ar = 8
    _dispersion(tmp_path, [{"ts": 1000.0, "coin": "BTC", "hl_bps_h": 0.20, "bin_bps_h": 0.0}])
    evts = tick(tmp_path, now=1010.0, session_id="S")
    assert any(e["type"] == "OPEN" and e["coin"] == "BTC" for e in evts)  # 0.20×168=33.6 ≥ 1.5×8
    row = next(r for r in _ledger(tmp_path) if r["kind"] == "OPEN")
    assert row["strategie"] == "cross_venue_carry" and row["real_execution"] is False


def test_refuse_sans_carnet_on_ne_simule_pas_une_jambe_qu_on_ne_coste_pas(tmp_path):
    _dispersion(tmp_path, [{"ts": 1000.0, "coin": "ZZZ", "hl_bps_h": 0.5, "bin_bps_h": 0.0}])
    assert tick(tmp_path, now=1010.0) == []                          # pas de carnet -> aucune ouverture


def test_refuse_un_premium_trop_faible_pour_amortir(tmp_path):
    _carnet(tmp_path, [_spread("BTC", 2.0, 2.0)])                    # cout_ar = 8
    _dispersion(tmp_path, [{"ts": 1000.0, "coin": "BTC", "hl_bps_h": 0.02, "bin_bps_h": 0.0}])
    # 0.02 × 168 = 3.36 < 1.5 × 8 = 12 -> REFUS (le funding ne rembourse pas la sortie)
    assert tick(tmp_path, now=1010.0) == []


def test_refuse_un_coin_illiquide_spread_enorme(tmp_path):
    _carnet(tmp_path, [_spread("THIN", 40.0, 40.0)])                 # spread total 80 > plafond 30
    _dispersion(tmp_path, [{"ts": 1000.0, "coin": "THIN", "hl_bps_h": 2.0, "bin_bps_h": 0.0}])
    assert tick(tmp_path, now=1010.0) == []


# ------------------------------------------------------------------ ACCRUE + FERMETURE honnête

def test_accrue_le_funding_puis_ferme_quand_le_premium_meurt_PnL_unifie(tmp_path):
    _carnet(tmp_path, [_spread("BTC", 1.0, 1.0)])                    # cout_ar = 4
    _dispersion(tmp_path, [{"ts": 1000.0, "coin": "BTC", "hl_bps_h": 0.30, "bin_bps_h": 0.0}])
    tick(tmp_path, now=1010.0, session_id="S")                       # OPEN
    # 40 h plus tard, premium encore vivant -> accrue 0.30 × 40 = 12 bps
    t2 = 1010.0 + 40 * 3600.0
    _dispersion(tmp_path, [{"ts": t2 - 5, "coin": "BTC", "hl_bps_h": 0.30, "bin_bps_h": 0.0}])
    tick(tmp_path, now=t2, session_id="S")
    # premium meurt -> fermeture ; realized = (accru − cout)/1e4 × notional
    t3 = t2 + 3600.0
    _dispersion(tmp_path, [{"ts": t3 - 5, "coin": "BTC", "hl_bps_h": 0.0, "bin_bps_h": 0.05}])
    evts = tick(tmp_path, now=t3, session_id="S")
    close = next(e for e in evts if e["type"] == "CLOSE")
    assert close["funding_accru_bps"] > 11.0                         # ~12 bps encaissés
    ferm = next(r for r in _ledger(tmp_path) if r["kind"] == "CLOSE")
    assert ferm["reason"] == "CV_PREMIUM_MORT" and ferm["mode"] == "LIVE"
    assert ferm["realized_net_pnl_usdc"] > 0                         # 12 − 4 = +8 bps -> positif
    # LE PnL UNIFIÉ : le résumé carry compte le réalisé cross-venue
    from hl_observer.funding.carry_positions_store import resume_depuis_ledger
    r = resume_depuis_ledger(tmp_path, session_id="S")
    assert abs(r["realized_net_pnl_usdc_session"] - close["realized"]) < 1e-9


def test_une_fermeture_sans_assez_de_funding_paie_ses_couts_honnetement(tmp_path):
    _carnet(tmp_path, [_spread("BTC", 3.0, 3.0)])                    # cout_ar = 12
    _dispersion(tmp_path, [{"ts": 1000.0, "coin": "BTC", "hl_bps_h": 0.30, "bin_bps_h": 0.0}])
    tick(tmp_path, now=1010.0, session_id="S")
    # ferme vite (2 h) : accrue ~0.6 bps << cout 12 -> perte assumée, jamais cachée
    t2 = 1010.0 + 2 * 3600.0
    _dispersion(tmp_path, [{"ts": t2 - 5, "coin": "BTC", "hl_bps_h": 0.0, "bin_bps_h": 0.10}])
    evts = tick(tmp_path, now=t2, session_id="S")
    close = next(e for e in evts if e["type"] == "CLOSE")
    assert close["realized"] < 0                                     # coûts payés, PnL négatif ASSUMÉ


# ------------------------------------------------------------------ le BACKTEST mesure, n'invente rien

def test_backtest_mesure_le_net_par_coin_couts_reels_deduits(tmp_path):
    # premium ~0.30 bps/h persistant sur 60 h ; cout_ar 4 -> net ~ (0.30×60 − 4) = +14 bps.
    # bin_bps_h VARIE (jambe Binance réelle, pas figée) ; hl constant au plancher est normal.
    rows = [{"ts": 1000.0 + i * 3600.0, "coin": "BTC", "hl_bps_h": 0.30, "bin_bps_h": (i % 2) * 0.001}
            for i in range(61)]
    _dispersion(tmp_path, rows)
    _carnet(tmp_path, [_spread("BTC", 1.0, 1.0)])
    r = backtest(tmp_path)
    assert r["n_coins_positifs"] == 1 and r["total_net_usd"] > 0
    assert r["par_coin"][0]["coin"] == "BTC"


def test_backtest_EXCLUT_une_jambe_binance_figee_artefact(tmp_path):
    # VINE : bin_bps_h à une seule valeur (coin hors Binance) -> artefact, jamais joué
    rows = [{"ts": 1000.0 + i * 3600.0, "coin": "VINE", "hl_bps_h": 0.5, "bin_bps_h": 0.0}
            for i in range(61)]
    _dispersion(tmp_path, rows)
    _carnet(tmp_path, [_spread("VINE", 1.0, 1.0)])
    r = backtest(tmp_path)
    assert all(d["coin"] != "VINE" for d in r["par_coin"])          # jambe figée exclue
