"""LOT 6 — exécution honnête prouvée sans réseau (Flo 25/07)."""
from __future__ import annotations

from hl_observer.research_parallel import execution_honnete as EH


# ── VWAP taker ──
def test_vwap_consomme_la_profondeur():
    niveaux = [(100.0, 6.0), (100.1, 6.0)]      # 12 $ dispo
    r = EH.vwap_taker(niveaux, 10.0)
    assert r["statut"] == "OK" and 100.0 <= r["vwap"] <= 100.1


def test_vwap_non_mesurable_si_profondeur_insuffisante():
    r = EH.vwap_taker([(100.0, 3.0)], 10.0)     # 3 $ < 10 $
    assert r["statut"] == "NON_MESURABLE" and r["motif"] == "PROFONDEUR_INSUFFISANTE"
    assert EH.vwap_taker([], 10.0)["motif"] == "AUCUNE_PROFONDEUR"


# ── queue model conservateur ──
def test_queue_model_rempli_seulement_si_file_traversee():
    ok = EH.queue_model_maker(file_devant_usd=100.0, taille_usd=10.0, volume_traverse_usd=120.0)
    assert ok["statut"] == "REMPLI"
    non = EH.queue_model_maker(file_devant_usd=100.0, taille_usd=10.0, volume_traverse_usd=90.0)
    assert non["statut"] == "NON_REMPLI" and non["manque_usd"] == 20.0


# ── markouts séparés + lag réel ──
def _prix(t0=1_000_000.0, dt=1000.0, base=100.0, pas=0.0, n=80):
    return [(t0 + i * dt, base + i * pas, base + i * pas + 0.01) for i in range(n)]


def test_markouts_separes_par_horizon_et_lag_reel():
    prix = _prix(base=100.0, pas=0.02)          # monte régulièrement
    r = EH.markouts_causaux({"ts_ms": 1_000_000.0, "coin": "X", "sens": 1}, prix,
                            horizons_s=(1, 5, 30), fee_ar_bps=0.0, slippage_bps=0.0)
    assert r["statut"] == "OK"
    assert "entree_lag_ms" in r and r["entree_lag_ms"] >= 0                 # lag réel d'entrée explicite
    for h in ("1", "5", "30"):
        assert r["par_horizon"][h]["statut"] == "OK"
        assert "sortie_lag_ms" in r["par_horizon"][h]                       # lag réel de sortie par horizon
    # horizons distincts -> nets distincts (pas de tolérance 60 s cachée qui les uniformise)
    n1 = r["par_horizon"]["1"]["net_bps"]; n30 = r["par_horizon"]["30"]["net_bps"]
    assert n30 > n1, "un horizon plus long capture plus de hausse -> net distinct par horizon"


def test_markout_non_mesurable_sans_entree_causale():
    prix = [(1_000_000.0, 100.0, 100.01)]       # rien après le seuil
    r = EH.markouts_causaux({"ts_ms": 1_000_000.0, "coin": "X", "sens": 1}, prix)
    assert r["statut"] == "NON_MESURABLE"


def test_horizon_non_mesurable_isole_les_autres():
    # série qui s'arrête tôt : horizon 1 s OK, horizon 30 s NON_MESURABLE, sans casser le 1 s
    prix = _prix(n=5)                            # ~4 s de données
    r = EH.markouts_causaux({"ts_ms": 1_000_000.0, "coin": "X", "sens": 1}, prix, horizons_s=(1, 30))
    assert r["par_horizon"]["1"]["statut"] == "OK" and r["par_horizon"]["30"]["statut"] == "NON_MESURABLE"
