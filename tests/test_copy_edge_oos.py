"""Edge de copie OOS SANS FUITE (rectif Flo 23/07) : choix sur TRAIN, OOS purgé par période ET par
vault, IC bootstrap, statut PRÉLIMINAIRE/VALIDATION, décision SCALE/OBSERVE/KILL, ROI cumulé vs par
trade, ranking de variantes. Aucune exécution."""
from __future__ import annotations

from hl_observer.experimental.copy_edge_oos import (mesurer_oos, simuler_paper, ranger_variantes,
                                                    mae_mfe, calibrer_risque, construire_table_prelim)

H = 300_000


def _events_multi_vault(n=120, vaults=6):
    """n entrées long, coins UNIQUES (pas de dérive), réparties sur 6 vaults et dans le temps."""
    T = 10_000_000
    ev = []
    for k in range(n):
        ev.append({"ts_ms": T + k * (H // 2), "vault": "V%d" % (k % vaults), "coin": "C%04d" % k,
                   "direction": 1, "move_frac": 0.10})
    return ev


def _tape_pic(events):
    """Par coin unique : plat 100, +40 bps pile à te+H (le forward capture l'edge ; placebo ≈ 0)."""
    tape = {}
    for e in events:
        te, c = e["ts_ms"], e["coin"]
        tape[c] = [(te - H, 100.0), (te, 100.0), (te + H, 100.4), (te + 2 * H, 100.0)]
    return tape


def test_need_more_data_si_trop_peu():
    ev = [{"ts_ms": i, "vault": "V%d" % (i % 2), "coin": "C", "direction": 1, "move_frac": 0.1} for i in range(6)]
    r = mesurer_oos(ev, {"C": [(0, 100.0), (1, 101.0)]}, min_events_train=20, min_events_oos=20)
    assert r["statut"] == "NEED_MORE_DATA"


def test_oos_walk_forward_temporel_primaire_generalisation_vault_secondaire():
    ev = _events_multi_vault()
    tape = _tape_pic(ev)
    r = mesurer_oos(ev, tape, seuils=(0.05,), horizons_ms=(H,), frais_bps=12.0,
                    min_events_train=10, min_events_oos=10, seuil_validation=15, graine=1)
    assert r["statut"] in ("PRELIMINAIRE", "VALIDATION")
    # PRIMAIRE = walk-forward TEMPOREL (mêmes vaults) ; purge = horizon
    assert r["validation"] == "temporelle_walk_forward_meme_vaults" and r["purge_ms"] == H
    # SECONDAIRE = généralisation par vault held-out, présente
    assert "generalisation_par_vault" in r and "vaults_held_out" in r["generalisation_par_vault"]
    # l'edge synthétique (+40 brut, +28 net) doit ressortir en OOS et battre le placebo
    assert r["oos"]["net_bps"] > 15 and r["oos"]["edge_vs_placebo_bps"] > 10
    assert r["oos"]["ic95_bas_bps"] <= r["oos"]["net_bps"] <= r["oos"]["ic95_haut_bps"]
    assert r["decision"] in ("SCALE", "OBSERVE") and r["edge_valide_oos"] in (True, False)


def test_forward_candles_anti_lookahead():
    """Entrée à la 1re bougie APRÈS signal+délai (jamais la bougie contenant le signal)."""
    from hl_observer.experimental.copy_edge_forward import rendement_forward_candles
    serie = [(0, 100.0), (60_000, 100.0), (120_000, 101.0), (180_000, 101.0)]   # bougies 1 min
    ev = {"ts_ms": 30_000, "direction": 1}
    # signal à 30 s : entrée = 1re bougie après 30 s = t=60_000 (px 100) ; horizon 60 s -> après 90 s = t=120_000 (101)
    r = rendement_forward_candles(ev, serie, 60_000, delai_ms=0.0)
    assert round(r, 1) == 100.0                                          # +100 bps, pris APRÈS le signal
    assert rendement_forward_candles(ev, serie, 10_000_000) is None      # horizon hors tape -> None


def test_micro_derive_sous_les_couts_est_kill():
    """Dérive minuscule (~0,1 bps/pas) << coûts réalistes (12 bps) : net<0 -> KILL, jamais SCALE."""
    ev = _events_multi_vault()
    T0 = min(e["ts_ms"] for e in ev)
    tape = {}
    for e in ev:                                                     # dérive de ~0,1 bps par H : sous les coûts
        tape[e["coin"]] = [(T0 + i * H, 100.0 * (1 + 0.00001 * i)) for i in range(200)]
    r = mesurer_oos(ev, tape, seuils=(0.05,), horizons_ms=(H,), frais_bps=12.0,
                    min_events_train=10, min_events_oos=10, seuil_validation=15)
    assert r["decision"] == "KILL" and not r["edge_valide_oos"]


def test_simuler_paper_roi_cumule_vs_par_trade():
    """ROI cumulé (PnL/capital) et ROI par trade (bps) DISTINCTS (rectif Flo)."""
    ev = _events_multi_vault(n=20)
    tape = _tape_pic(ev)
    sim = simuler_paper(ev, tape, horizon_ms=H, seuil=0.05, notional_usd=150.0, cout_ar_bps=12.0, capital_usd=1000.0)
    assert sim["n_trades"] == 20 and sim["roi_par_trade_bps"] == 28.0     # 40 − 12
    # ROI cumulé = 20 trades × 28 bps × 150$ / 1000$ = +8,4 %  (≠ 28 bps par trade)
    assert round(sim["roi_cumulatif_pct"], 2) == round(20 * 28 / 1e4 * 150 / 1000 * 100, 2)
    assert len(sim["roi_par_trade_ic95_bps"]) == 2 and sim["drawdown_pct"] == 0.0


def test_mae_mfe_excursions():
    # entrée anti-lookahead = 1re bougie APRÈS le signal ; les excursions arrivent ensuite
    serie = [(-60_000, 100.0), (0, 100.0), (60_000, 100.5), (120_000, 99.7), (180_000, 100.0)]
    ev = {"ts_ms": -30_000, "direction": 1}                          # entrée à t=0 (px 100), puis +50 / -30
    mae, mfe = mae_mfe(ev, serie, 200_000, delai_ms=0.0)
    assert round(mfe) == 50 and round(mae) == -30                    # MFE +50, MAE -30 bps


def test_calibrer_risque_kill_si_risque_domine_edge():
    """Un edge minuscule avec une grosse excursion adverse APRÈS l'entrée -> KILL (risque ≫ edge)."""
    serie = [(-60_000, 100.0), (0, 100.0), (60_000, 98.0), (120_000, 100.05)]   # entrée 100, plonge -200
    ev = [{"ts_ms": -30_000, "coin": "X", "direction": 1, "move_frac": 0.1} for _ in range(30)]
    r = calibrer_risque(ev, {"X": serie}, 200_000, edge_net_bps=5.0, min_events=5)
    assert r["decision_risque"] == "KILL" and r["mae_p50_bps"] > 5.0   # adverse typique ≫ edge 5 bps


def test_table_prelim_exclut_les_coins_a_risque_domine():
    # WIN : monte doucement (edge>0, faible MAE) -> gardé ; VOLA : edge ~0 mais MAE énorme -> exclu
    ev = [{"ts_ms": i * 1000, "coin": "WIN", "direction": 1, "move_frac": 0.1} for i in range(30)] \
        + [{"ts_ms": i * 1000, "coin": "VOLA", "direction": 1, "move_frac": 0.1} for i in range(30)]
    tape = {"WIN": [(i * 1000, 100.0 + 0.02 * i) for i in range(200)],
            "VOLA": [(i * 1000, 100.0 + (5.0 if i % 2 else -5.0)) for i in range(200)]}
    t = construire_table_prelim(ev, tape, horizons_ms=(60_000.0,), frais_bps=1.0, min_events=10)
    assert "WIN" in t and t["WIN"]["stop_bps"] is not None and "VOLA" not in t


def test_ranger_variantes_par_score():
    ev = _events_multi_vault()
    tape = _tape_pic(ev)
    classement = ranger_variantes(ev, tape, variantes=[{"seuil": 0.05, "horizon_ms": H},
                                                       {"seuil": 0.30, "horizon_ms": H}])   # 0.30 filtre tout
    assert classement[0]["seuil"] == 0.05                            # la variante qui trade gagne
    assert classement[0]["score"] >= classement[1]["score"]
