"""P1B — latence autoritaire par exécution causale différée ; scalaire = STRESS uniquement."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.paper_trading import latency_truth as L  # noqa: E402


def _books():
    return [
        {"observed_at_ms": 1000, "mid": 100.0},
        {"observed_at_ms": 1200, "mid": 100.02},
        {"observed_at_ms": 1300, "mid": 100.05},
        {"observed_at_ms": 1500, "mid": 100.10},
    ]


# --- sélection du premier carnet causal --------------------------------------
def test_selection_premier_carnet_a_ou_apres_cible():
    sel = L.selectionner_carnet_causal(_books(), decision_ts_ms=1000, delay_ms=250)  # cible 1250
    assert sel["statut"] == "OK" and sel["observed_at_ms"] == 1300      # premier >= 1250
    assert sel["latency_ms_realise"] == 300.0


def test_no_fill_si_aucun_carnet_causal():
    sel = L.selectionner_carnet_causal(_books(), decision_ts_ms=1000, delay_ms=1000)  # cible 2000
    assert sel["statut"] == L.NO_FILL


def test_stale_book_si_premier_trop_tardif():
    sel = L.selectionner_carnet_causal(_books(), decision_ts_ms=1000, delay_ms=250, tol_ms=20)  # cible 1250, 1300 = +50>20
    assert sel["statut"] == L.STALE_BOOK and sel["retard_ms"] == 50.0


# --- vérité de latence : autoritaire = déplacement mid causal ----------------
def test_latence_autoritaire_mesuree_depuis_le_deplacement_mid():
    # décision mid 100.0, exécution contre carnet à 1300 (mid 100.05), BUY → +5 bps adverses.
    r = L.verite_latence(_books(), decision_ts_ms=1000, mid_decision=100.0, side="BUY",
                         delay_ms=250, delay_source=L.ASSUMED)
    assert r["statut"] == L.MEASURED
    assert r["latency_bps_authoritative"] == 5.0 and r["execution_mid"] == 100.05
    assert r["latency_ms_realise"] == 300.0


def test_le_scalaire_est_toujours_stress_only():
    r = L.verite_latence(_books(), decision_ts_ms=1000, mid_decision=100.0, side="BUY", delay_ms=250)
    assert r["stress_scalaire"]["usage"] == L.STRESS_ONLY
    assert r["stress_scalaire"]["statut"] == L.STRESS_ONLY
    # jamais confondu avec l'autoritaire
    assert r["latency_bps_authoritative"] != r["stress_scalaire"]["latency_stress_bps"]


def test_no_fill_remonte_et_pas_de_latence_autoritaire():
    r = L.verite_latence(_books(), decision_ts_ms=1000, mid_decision=100.0, side="BUY", delay_ms=5000)
    assert r["statut"] == L.NO_FILL and r["latency_bps_authoritative"] is None


def test_delay_source_mesure_vs_assumed():
    mes = L.verite_latence(_books(), decision_ts_ms=1000, mid_decision=100.0, side="BUY",
                           delay_ms=250, delay_source=L.MEASURED)
    ass = L.verite_latence(_books(), decision_ts_ms=1000, mid_decision=100.0, side="BUY", delay_ms=250)
    assert mes["delay_source"] == L.MEASURED and ass["delay_source"] == L.ASSUMED


def test_scalaire_stress_borne_au_cap():
    s = L.latence_scalaire_stress_bps(1000.0, coeff_bps_per_sec=0.20, cap_bps=15.0)   # 1000s × 0.2 = 200 → cap 15
    assert s["latency_stress_bps"] == 15.0 and s["usage"] == L.STRESS_ONLY


def test_replay_egale_forward_selection_deterministe():
    # Même carnets + mêmes paramètres → même sélection (déterminisme = replay/forward identiques).
    a = L.selectionner_carnet_causal(_books(), decision_ts_ms=1000, delay_ms=250)
    b = L.selectionner_carnet_causal(list(reversed(_books())), decision_ts_ms=1000, delay_ms=250)
    assert a["observed_at_ms"] == b["observed_at_ms"] == 1300      # ordre d'entrée indifférent
