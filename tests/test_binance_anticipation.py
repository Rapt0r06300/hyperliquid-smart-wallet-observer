"""P5.1 — score d'anticipation Wallet×Binance : leader vs suiveur, orientation, deny-by-default."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.following import binance_anticipation as A  # noqa: E402

H = (1000,)


def test_leader_a_une_anticipation_positive():
    # Prix plat AVANT l'achat, monte APRÈS → move_before 0, move_after +50 → anticipation +50.
    path = [(8000, 100.0), (9000, 100.0), (10000, 100.0), (11000, 100.5), (12000, 101.0)]
    s = A.score_anticipation(t_event_ms=10000, action="BUY", path=path, horizons_ms=H)
    cell = s["par_horizon"][1000]
    assert cell["statut"] == "MEASURED"
    assert cell["move_before_bps"] == 0.0 and cell["move_after_bps"] == 50.0
    assert cell["anticipation_bps"] == 50.0


def test_suiveur_a_une_anticipation_negative():
    # Prix a DÉJÀ monté avant l'achat, plat après → move_before +50, move_after 0 → anticipation −50.
    path = [(9000, 100.0), (10000, 100.5), (11000, 100.5), (12000, 100.5)]
    s = A.score_anticipation(t_event_ms=10000, action="BUY", path=path, horizons_ms=H)
    assert s["par_horizon"][1000]["anticipation_bps"] == -50.0


def test_orientation_short_baisse_apres_est_favorable():
    # Vente à T, prix plat avant, BAISSE après → favorable pour un short → anticipation positive.
    path = [(9000, 100.0), (10000, 100.0), (11000, 99.5), (12000, 99.0)]
    s = A.score_anticipation(t_event_ms=10000, action="SELL", path=path, horizons_ms=H)
    cell = s["par_horizon"][1000]
    assert cell["move_after_bps"] == 50.0 and cell["anticipation_bps"] == 50.0
    assert s["sens"] == -1


def test_unmeasurable_si_chemin_ne_couvre_pas_apres():
    path = [(9000, 100.0), (10000, 100.0)]                 # s'arrête à T, pas de T+1000
    s = A.score_anticipation(t_event_ms=10000, action="BUY", path=path, horizons_ms=H)
    assert s["par_horizon"][1000]["statut"] == "UNMEASURABLE"


def test_unmeasurable_si_chemin_ne_couvre_pas_avant():
    path = [(10000, 100.0), (11000, 100.5)]                # commence à T, pas de T−1000
    s = A.score_anticipation(t_event_ms=10000, action="BUY", path=path, horizons_ms=H)
    assert s["par_horizon"][1000]["statut"] == "UNMEASURABLE"


def test_action_inconnue_tout_unmeasurable():
    path = [(9000, 100.0), (10000, 100.0), (11000, 100.5)]
    s = A.score_anticipation(t_event_ms=10000, action="???", path=path, horizons_ms=H)
    assert s["sens"] is None and s["par_horizon"][1000]["statut"] == "UNMEASURABLE"
    assert s["anticipation_moy_bps"] is None


def test_plusieurs_horizons_moyenne_les_mesures():
    path = [(t, 100.0 + max(0.0, (t - 10000)) / 2000.0) for t in range(7000, 13001, 250)]
    s = A.score_anticipation(t_event_ms=10000, action="BUY", path=path,
                             horizons_ms=(250, 500, 1000))
    assert s["n_horizons_mesures"] == 3 and s["anticipation_moy_bps"] is not None


def test_anticipation_moyenne_par_wallet():
    path = {"BTC": [(9000, 100.0), (10000, 100.0), (11000, 100.5), (12000, 101.0)]}
    evs = [
        {"wallet": "wA", "coin": "BTC", "action": "BUY", "ts_ms": 10000},
        {"wallet": "wA", "coin": "BTC", "action": "BUY", "ts_ms": 10000},
        {"wallet": "wB", "coin": "SOL", "action": "BUY", "ts_ms": 10000},   # pas de chemin SOL → ignoré
    ]
    r = A.anticipation_moyenne_par_wallet(evs, path, horizon_ms=1000)
    assert "wA" in r["wallets"] and r["wallets"]["wA"]["n"] == 2
    assert r["wallets"]["wA"]["anticipation_mediane_bps"] == 50.0
    assert "wB" not in r["wallets"]
