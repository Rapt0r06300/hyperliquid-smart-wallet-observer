"""Voie EXPERIMENTAL_PAPER (décision Flo 23/07). On prouve : admission SANS prouve_oos mais AVEC
fraîcheur + exécutable + edge > 0 + limites ; ledger/budget ISOLÉS du live ; entrées/sorties aux
bid/ask avec coûts ; PnL directionnel ET funding_carry ; aucune exécution réelle."""
from __future__ import annotations

import json

from hl_observer.experimental import moteur_paper as MP
from hl_observer.experimental.runner import tick, STATUS_RELPATH


def _sig(**kw):
    d = dict(moteur="lead_lag", coin="ETH", sens=1, type_pnl="directional", notional_usd=100.0,
             prix_entree=3000.0, cout_entree_bps=4.0, edge_estime_bps=18.0, ts_signal_ms=10_000.0,
             roi_annuel_pct=40.0, pnl_attendu_usd=1.0)
    d.update(kw)
    return MP.Signal(**d)


def test_admission_sans_oos_mais_barème_exigeant(tmp_path):
    store = MP.charger_store(tmp_path)
    now = 20_000.0
    assert MP.admettre(_sig(), store, now_ms=now) == (True, None)                 # frais + exécutable + gros edge
    assert MP.admettre(_sig(ts_signal_ms=0.0), store, now_ms=now)[1] == "SIGNAL_PERIME"
    assert MP.admettre(_sig(prix_entree=0.0), store, now_ms=now)[1] == "PRIX_NON_EXECUTABLE"
    assert MP.admettre(_sig(edge_estime_bps=-1.0), store, now_ms=now)[1] == "EDGE_NEGATIF_APRES_COUTS"
    # 🔴 barème v2 : refuse micro-edges + PnL pour des centimes (la porte ROI_vs_HLP a été RETIRÉE, carry mort)
    assert MP.admettre(_sig(edge_estime_bps=5.0), store, now_ms=now)[1] == "MICRO_EDGE"
    assert MP.admettre(_sig(pnl_attendu_usd=0.05), store, now_ms=now)[1] == "PNL_POUR_DES_CENTIMES"


def test_limites_par_moteur_et_un_marche_une_position(tmp_path):
    store = MP.charger_store(tmp_path)
    MP.ouvrir(_sig(coin="ETH"), store, tmp_path, now_ms=20_000)
    assert MP.admettre(_sig(coin="ETH"), store, now_ms=20_000)[1] == "DEJA_OUVERT"
    # remplir la limite de positions du moteur lead_lag (max 4)
    for c in ("SOL", "BTC", "AVAX"):
        MP.ouvrir(_sig(coin=c), store, tmp_path, now_ms=20_000)
    assert MP.admettre(_sig(coin="LINK"), store, now_ms=20_000)[1] == "LIMITE_POSITIONS_MOTEUR"


def test_pnl_directionnel_et_funding_carry(tmp_path):
    store = MP.charger_store(tmp_path)
    pos = MP.ouvrir(_sig(coin="ETH", sens=1, prix_entree=3000.0, cout_entree_bps=4.0), store, tmp_path, now_ms=0)
    # +1 % de prix sur 100$ notional − coût d'entrée 4 bps = 1.0 − 0.04
    assert MP.pnl_courant_usd(pos, mark=3030.0) == 0.96
    carry = MP.ouvrir(_sig(moteur="cross_venue", coin="DOT", type_pnl="funding_carry", d_bps_h=0.5,
                           cout_entree_bps=6.0), store, tmp_path, now_ms=0)
    # 0.5 bps/h × 10 h = 5 bps de funding sur 100$ = 0.05 − coût 6 bps = 0.06 -> -0.01
    assert MP.pnl_courant_usd(carry, now_ms=10 * 3_600_000) == -0.01


def test_sortie_au_bidask_avec_cout_et_ledger_ISOLE(tmp_path):
    store = MP.charger_store(tmp_path)
    pos = MP.ouvrir(_sig(coin="ETH", sens=1, prix_entree=3000.0, cout_entree_bps=4.0), store, tmp_path, now_ms=0)
    r = MP.sortir(pos, store, tmp_path, prix_sortie=3030.0, cout_sortie_bps=4.0, raison="TEST", now_ms=1000)
    assert r["realized_usd"] == 0.92                                             # 0.96 − 0.04 de sortie
    assert MP.charger_store(tmp_path)["ouvertes"] == {}
    # le ledger est SÉPARÉ (experimental) et JAMAIS le ledger carry live
    lignes = [json.loads(l) for l in (tmp_path / MP.LEDGER_RELPATH).read_text().splitlines()]
    assert all(x["mode"] == "EXPERIMENTAL_PAPER" and x["real_execution"] is False for x in lignes)
    assert not (tmp_path / "runtime" / "data" / "carry_paper_ledger.jsonl").exists()


def test_runner_ouvre_une_position_sur_signal_admis(tmp_path, monkeypatch):
    """Le runner collecte -> admet -> OUVRE réellement, et écrit un statut lisible."""
    from hl_observer.experimental import runner as R
    monkeypatch.setattr(R, "COLLECTEURS", {"lead_lag": lambda root, now_ms=None: ([_sig(coin="ETH", ts_signal_ms=now_ms)], [])})
    st = tick(tmp_path, now_ms=50_000.0, moteurs=("lead_lag",))
    assert len(st["ouvertures"]) == 1 and st["premier_signal"]["coin"] == "ETH"
    assert st["resume"]["positions_ouvertes"] == 1 and st["resume"]["real_execution"] is False
    assert (tmp_path / STATUS_RELPATH).exists()


def test_pnl_dislocation_capture_la_convergence(tmp_path):
    """Cross-venue COURT TERME : le PnL = convergence de l'écart capturée − coût d'entrée (zéro funding)."""
    store = MP.charger_store(tmp_path)
    pos = MP.ouvrir(_sig(moteur="cross_venue", coin="JTO", type_pnl="dislocation", cout_entree_bps=8.0,
                         meta={"gap_entree_bps": 30.0}), store, tmp_path, now_ms=0)
    # écart entré 30 bps, courant 5 bps -> 25 bps convergés sur 100$ = 0,25$ − coût 0,08$ = 0,17$
    assert MP.pnl_courant_usd(pos, base_courant_bps=5.0) == round(25.0 / 1e4 * 100 - 8.0 / 1e4 * 100, 6)


def test_sorties_dislocation_convergence_et_stop(tmp_path):
    from hl_observer.experimental.runner import _raison_sortie_dislocation
    pos = {"coin": "X", "sens": 1, "notional_usd": 50.0, "ts_ouverture_ms": 0, "hold_h": 0.5,
           "meta": {"gap_entree_bps": 30.0}}
    now = 1_000_000.0
    conv = {"hl_bid": 100.0, "hl_ask": 100.1, "bin_bid": 100.05, "bin_ask": 100.15,
            "taille_min_usd": 1000.0, "collecte_ts": now / 1000.0}          # écart refermé
    assert _raison_sortie_dislocation(pos, conv, now_ms=now)[0] == "CONVERGENCE_CAPTUREE"
    illiq = {**conv, "taille_min_usd": 10.0}
    assert _raison_sortie_dislocation(pos, illiq, now_ms=now)[0] == "LIQUIDITE_INSUFFISANTE"
    vieux = {**conv, "collecte_ts": now / 1000.0 - 9999}
    assert _raison_sortie_dislocation(pos, vieux, now_ms=now)[0] == "QUOTE_PERIMEE"


def test_runner_refuse_et_motive(tmp_path, monkeypatch):
    from hl_observer.experimental import runner as R
    monkeypatch.setattr(R, "COLLECTEURS",
                        {"lead_lag": lambda root, now_ms=None: ([_sig(edge_estime_bps=-5.0, ts_signal_ms=now_ms)], [])})
    st = tick(tmp_path, now_ms=50_000.0, moteurs=("lead_lag",))
    assert st["ouvertures"] == [] and st["refus_par_motif_ce_tick"].get("EDGE_NEGATIF_APRES_COUTS") == 1
