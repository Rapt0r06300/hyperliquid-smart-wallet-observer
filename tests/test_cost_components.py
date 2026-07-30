"""Jalon 1 — décomposition des coûts en 4 composantes bps disjointes, UNMEASURABLE strict."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.simulation import cost_components as C  # noqa: E402
from hl_observer.paper_trading.exec_model import simulate_depth_execution  # noqa: E402


# --- composantes unitaires ---------------------------------------------------
def test_spread_bps_positif_des_deux_cotes():
    assert C.spread_bps(100.0, 100.1, "BUY") == 10.0        # franchir vers l'ask
    assert C.spread_bps(100.0, 99.9, "SELL") == 10.0        # franchir vers le bid


def test_slippage_bps_denominateur_mid_commun():
    # touch 100.1 → avg 100.2, dénominateur mid=100 → 10 bps.
    assert C.slippage_bps(100.1, 100.2, "BUY", mid=100.0) == 10.0


def test_spread_plus_slippage_egale_exactement_le_cout_mid_vers_avg():
    mid, touch, avg = 100.0, 100.1, 100.2
    s = C.spread_bps(mid, touch, "BUY")
    sl = C.slippage_bps(touch, avg, "BUY", mid=mid)
    cout_direct = (avg / mid - 1.0) * 10_000.0
    assert abs((s + sl) - cout_direct) < 1e-6          # aucune redondance, aucun terme croisé


def test_latency_bps_adverse_positif_favorable_negatif():
    assert C.latency_bps(100.0, 100.05, "BUY") == 5.0      # le mid monte avant d'acheter = surcoût
    assert C.latency_bps(100.0, 99.95, "BUY") == -5.0      # le mid baisse avant d'acheter = crédit
    assert C.latency_bps(100.0, 99.95, "SELL") == 5.0      # le mid baisse avant de vendre = surcoût


def test_latency_absente_est_unmeasurable_jamais_zero():
    assert C.latency_bps(100.0, None, "BUY") is None        # latence non mesurée ≠ latence nulle


def test_sens_illisible_rend_none():
    assert C.spread_bps(100.0, 100.1, "XYZ") is None
    assert C.latency_bps(100.0, 100.1, "") is None


def test_mid_non_positif_rend_none():
    assert C.spread_bps(0.0, 100.1, "BUY") is None
    assert C.slippage_bps(100.1, 100.2, "BUY", mid=-1.0) is None


# --- decompose_execution : total seulement si les 4 mesurées ----------------
def test_decompose_total_present_si_les_quatre_sont_mesurees():
    cc = C.decompose_execution(side="BUY", mid_decision=100.0, best_touch=100.1,
                               avg_fill_price=100.2, mid_at_fill=100.05, fee_bps=4.5)
    assert cc.spread_bps == 10.0 and cc.slippage_bps == 10.0
    assert cc.latency_bps == 5.0 and cc.fees_bps == 4.5
    assert cc.total_bps == 29.5 and cc.unmeasured == ()


def test_decompose_total_unmeasurable_si_latence_absente():
    cc = C.decompose_execution(side="BUY", mid_decision=100.0, best_touch=100.1,
                               avg_fill_price=100.2, mid_at_fill=None, fee_bps=4.5)
    assert cc.latency_bps is None and cc.total_bps is None
    assert "latency_bps" in cc.unmeasured and "total_bps" in cc.unmeasured


def test_decompose_total_unmeasurable_si_frais_absents():
    cc = C.decompose_execution(side="BUY", mid_decision=100.0, best_touch=100.1,
                               avg_fill_price=100.2, mid_at_fill=100.05, fee_bps=None)
    assert cc.fees_bps is None and cc.total_bps is None


def test_decompose_latence_nulle_mesuree_reste_zero_et_total_calculable():
    # mid inchangé → latence 0 MESURÉE (pas absente) → total calculable.
    cc = C.decompose_execution(side="BUY", mid_decision=100.0, best_touch=100.1,
                               avg_fill_price=100.1, mid_at_fill=100.0, fee_bps=4.5)
    assert cc.latency_bps == 0.0 and cc.slippage_bps == 0.0
    assert cc.total_bps == 14.5 and "total_bps" not in cc.unmeasured


# --- câblage L2 causal : réutilise le book-walker ---------------------------
def test_depuis_carnet_causal_reconcilie_avec_le_modele_de_profondeur():
    asks = [(100.1, 1.0), (100.3, 100.0)]     # 1ʳᵉ tranche fine, puis profonde → walk du carnet
    cc = C.depuis_carnet_causal(side="BUY", notional_usdc=200.0, mid_decision=100.0,
                                asks=asks, bids=[], fee_bps=4.5)
    modele = simulate_depth_execution(side="BUY", notional_usdc=200.0, mid_price=100.0,
                                      asks=asks, bids=[])
    # spread + slippage (mine) == slippage-vs-mid (modèle), par construction (même dénominateur mid).
    assert cc.spread_bps is not None and cc.slippage_bps is not None
    assert abs((cc.spread_bps + cc.slippage_bps) - modele.slippage_bps) < 1e-3
    assert cc.spread_bps > 0 and cc.slippage_bps > 0


def test_depuis_carnet_causal_fill_manquant_slippage_unmeasurable():
    # Carnet vide côté ask → rien ne se remplit → avg None → slippage UNMEASURABLE (pas de faux coût).
    cc = C.depuis_carnet_causal(side="BUY", notional_usdc=100.0, mid_decision=100.0,
                                asks=[], bids=[], fee_bps=4.5)
    assert cc.slippage_bps is None and cc.total_bps is None


def test_to_dict_marque_paper_only():
    d = C.decompose_execution(side="BUY", mid_decision=100.0, best_touch=100.1,
                              avg_fill_price=100.2, mid_at_fill=100.05, fee_bps=4.5).to_dict()
    assert d["paper_only"] is True and d["real_execution"] is False
    assert d["schema_version"] == C.SCHEMA_VERSION and d["total_bps"] == 29.5
