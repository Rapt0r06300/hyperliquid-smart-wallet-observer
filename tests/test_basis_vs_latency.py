"""ALPHA P50 — basis persistant vs dislocation transiente : autocorr, demi-vie, classification, gate."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.research import basis_vs_latency as B  # noqa: E402


def _persistent(n=400):
    # marche aleatoire (niveaux tres autocorrelees ~1) = basis persistant
    s = 12345
    x = 10.0
    out = []
    for _ in range(n):
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        x += ((s % 20) - 10) / 1000.0
        out.append(x)
    return out


def _transient(n=400):
    # bruit iid autour de 10 (autocorr ~0) = dislocation transiente
    s = 999
    out = []
    for _ in range(n):
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        out.append(10.0 + ((s % 200) - 100) / 50.0)
    return out


def test_persistent_basis_detecte():
    c = B.classer_dislocation(_persistent(), dt_s=1.0)
    assert c["persistent_basis"] is True and c["autocorr1"] > 0.5


def test_transient_detecte():
    c = B.classer_dislocation(_transient(), dt_s=1.0)
    assert c["transient"] is True


def test_gate_cross_venue_bloque_basis():
    persistent = {"persistent_basis": True}
    assert B.gate_cross_venue(persistent, edge_bps=50.0, cost_bps=9.0)["trade"] is False   # basis hors scope
    transient = {"persistent_basis": False}
    assert B.gate_cross_venue(transient, edge_bps=15.0, cost_bps=9.0)["trade"] is True
    assert B.gate_cross_venue(transient, edge_bps=5.0, cost_bps=9.0)["trade"] is False       # edge<cout


def test_demi_vie():
    assert B.demi_vie_pas(0.5) is not None and B.demi_vie_pas(1.5) is None


# ── FIX-10 : épisode cross-venue de bout en bout ──
_ASKS = [(100.0, 10.0), (100.1, 10.0)]   # carnet A (on achète les asks)
_BIDS = [(99.9, 10.0), (99.8, 10.0)]     # carnet B (on vend les bids pour se couvrir)


def test_fix10_episode_transient_couvert_est_candidat_net_positif():
    r = B.episode_cross_venue(serie_gap_bps=_transient(), gross_edge_bps=30.0, notional_usd=500.0,
                              carnet_A=_ASKS, carnet_B=_BIDS, ts_signal_ms=0.0, ts_hedge_ms=50.0,
                              fee_bps=4.5, roundtrip_costs_bps=[8.0] * 30)
    assert r["verdict"] == "CANDIDAT" and r["issue"] == "HEDGED"
    assert r["net_pnl_usd"] > 0 and r["hedge_latency_ms"] == 50.0          # PnL net APRÈS tous les coûts
    assert r["fees_usd"] > 0 and r["couvert"] is True


def test_fix10_basis_persistant_est_elimine_pas_un_arb():
    r = B.episode_cross_venue(serie_gap_bps=_persistent(), gross_edge_bps=50.0, notional_usd=500.0,
                              carnet_A=_ASKS, carnet_B=_BIDS, roundtrip_costs_bps=[8.0] * 30)
    assert r["verdict"] == "NO_ARB_PERSISTENT_BASIS" and r["net_pnl_usd"] == 0.0   # basis != arb


def test_fix10_gross_sous_p95_roundtrip_est_kill():
    r = B.episode_cross_venue(serie_gap_bps=_transient(), gross_edge_bps=5.0, notional_usd=500.0,
                              carnet_A=_ASKS, carnet_B=_BIDS, roundtrip_costs_bps=[7.0, 8.0, 9.0, 10.0, 11.0] * 6)
    assert r["verdict"] == "KILL" and "P95 roundtrip" in r["raison"]      # gross 5 <= P95 ~11


def test_fix10_hedge_echoue_unwind_reel_pnl_honnete():
    # jambe B vide -> hedge impossible -> la jambe 1 nue est DÉBOUCLÉE contre un carnet causal (coût réel).
    r = B.episode_cross_venue(serie_gap_bps=_transient(), gross_edge_bps=30.0, notional_usd=500.0,
                              carnet_A=_ASKS, carnet_B=(), carnet_unwind={"bids": _BIDS, "asks": _ASKS},
                              ts_signal_ms=0.0, ts_hedge_ms=50.0, roundtrip_costs_bps=[8.0] * 30)
    assert r["issue"] == "UNWIND_REQUIRED" and r["verdict"] == "KILL"     # hedge raté = pas d'arb propre
    assert r["net_pnl_usd"] <= 0                                          # on paie le débouclage, jamais de gain fabriqué


def test_fix10_top_of_book_seul_reste_more_data():
    # transient tradable mais AUCUNE profondeur L2 -> jambes non exécutables -> MORE_DATA (jamais un fill inventé)
    r = B.episode_cross_venue(serie_gap_bps=_transient(), gross_edge_bps=30.0, notional_usd=500.0,
                              carnet_A=(), carnet_B=(), roundtrip_costs_bps=[8.0] * 30)
    assert r["verdict"] == "MORE_DATA" and r["net_pnl_usd"] == "UNMEASURABLE"
