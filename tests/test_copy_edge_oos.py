"""Edge de copie OOS SANS FUITE (rectif Flo 23/07) : choix sur TRAIN, OOS purgé par période ET par
vault, IC bootstrap, statut PRÉLIMINAIRE/VALIDATION, décision SCALE/OBSERVE/KILL, ROI cumulé vs par
trade, ranking de variantes. Aucune exécution."""
from __future__ import annotations

from hl_observer.experimental.copy_edge_oos import mesurer_oos, simuler_paper, ranger_variantes

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


def test_oos_sans_fuite_par_periode_et_par_vault():
    ev = _events_multi_vault()
    tape = _tape_pic(ev)
    r = mesurer_oos(ev, tape, seuils=(0.05,), horizons_ms=(H,), frais_bps=12.0,
                    min_events_train=10, min_events_oos=10, seuil_validation=15, graine=1)
    assert r["statut"] in ("PRELIMINAIRE", "VALIDATION")
    # séparation stricte : vaults de train et d'OOS DISJOINTS
    assert set(r["vaults_train"]).isdisjoint(set(r["vaults_oos"]))
    assert r["purge_ms"] == H and r["separe_par_vault"] is True
    # l'edge synthétique (+40 brut, +28 net) doit ressortir en OOS et battre le placebo
    assert r["oos"]["net_bps"] > 15 and r["oos"]["edge_vs_placebo_bps"] > 10
    assert r["oos"]["ic95_bas_bps"] <= r["oos"]["net_bps"] <= r["oos"]["ic95_haut_bps"]
    assert r["decision"] in ("SCALE", "OBSERVE") and r["edge_valide_oos"] in (True, False)


def test_placebo_tue_le_faux_edge():
    """Tape en DÉRIVE pure (monte partout) : l'OOS ne doit PAS battre le placebo -> pas de SCALE."""
    ev = _events_multi_vault()
    T0 = min(e["ts_ms"] for e in ev)
    tape = {}
    for e in ev:                                                     # même série montante pour tous : dérive, pas edge
        tape[e["coin"]] = [(T0 + i * H, 100.0 * (1 + 0.00001 * i)) for i in range(200)]
    r = mesurer_oos(ev, tape, seuils=(0.05,), horizons_ms=(H,), frais_bps=0.0,
                    min_events_train=10, min_events_oos=10, seuil_validation=15)
    assert r["decision"] in ("KILL", "OBSERVE") and not r["edge_valide_oos"]


def test_simuler_paper_roi_cumule_vs_par_trade():
    """ROI cumulé (PnL/capital) et ROI par trade (bps) DISTINCTS (rectif Flo)."""
    ev = _events_multi_vault(n=20)
    tape = _tape_pic(ev)
    sim = simuler_paper(ev, tape, horizon_ms=H, seuil=0.05, notional_usd=150.0, cout_ar_bps=12.0, capital_usd=1000.0)
    assert sim["n_trades"] == 20 and sim["roi_par_trade_bps"] == 28.0     # 40 − 12
    # ROI cumulé = 20 trades × 28 bps × 150$ / 1000$ = +8,4 %  (≠ 28 bps par trade)
    assert round(sim["roi_cumulatif_pct"], 2) == round(20 * 28 / 1e4 * 150 / 1000 * 100, 2)
    assert len(sim["roi_par_trade_ic95_bps"]) == 2 and sim["drawdown_pct"] == 0.0


def test_ranger_variantes_par_score():
    ev = _events_multi_vault()
    tape = _tape_pic(ev)
    classement = ranger_variantes(ev, tape, variantes=[{"seuil": 0.05, "horizon_ms": H},
                                                       {"seuil": 0.30, "horizon_ms": H}])   # 0.30 filtre tout
    assert classement[0]["seuil"] == 0.05                            # la variante qui trade gagne
    assert classement[0]["score"] >= classement[1]["score"]
