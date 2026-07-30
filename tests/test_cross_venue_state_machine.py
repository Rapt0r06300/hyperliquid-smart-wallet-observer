"""P9.3 v2 — hedge cross-venue : lifecycle + UNWIND réellement simulé contre carnet causal."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import cross_venue_state_machine as M  # noqa: E402


# --- lifecycle ---------------------------------------------------------------
def test_hedge_complet():
    r = M.simuler_hedge(
        leg1={"notional_demande": 100.0, "notional_fill": 100.0, "ts_ms": 1000},
        leg2={"notional_hedge": 100.0, "ts_ms": 1250, "slippage_bps": 3.0},
    )
    assert r["issue"] == M.HEDGED and r["couvert"] is True
    assert r["hedge_latency_ms"] == 250.0 and r["unwind"] is None


def test_residu_nu_si_hedge_partiel():
    r = M.simuler_hedge(
        leg1={"notional_demande": 100.0, "notional_fill": 100.0, "ts_ms": 1000},
        leg2={"notional_hedge": 60.0, "ts_ms": 1100},
    )
    assert r["issue"] == M.RESIDUAL_UNHEDGED and r["residual_notional_usd"] == 40.0


def test_unwind_requis_si_jambe2_echoue():
    r = M.simuler_hedge(
        leg1={"notional_demande": 100.0, "notional_fill": 80.0, "ts_ms": 1000},
        leg2={"echec": True, "raison_echec": "PROFONDEUR_INSUFFISANTE"},
    )
    assert r["issue"] == M.UNWIND_REQUIRED and r["residual_notional_usd"] == 80.0


def test_no_leg1_si_rien_entre():
    r = M.simuler_hedge(leg1={"notional_demande": 100.0, "notional_fill": 0.0})
    assert r["issue"] == M.NO_LEG1 and r["residual_notional_usd"] == 0.0


def test_latence_incoherente_non_mesuree():
    r = M.simuler_hedge(
        leg1={"notional_demande": 100.0, "notional_fill": 100.0, "ts_ms": 2000},
        leg2={"notional_hedge": 100.0, "ts_ms": 1000},
    )
    assert r["hedge_latency_ms"] is None


# --- UNWIND réellement simulé ------------------------------------------------
def test_simuler_unwind_long_vend_les_bids():
    r = M.simuler_unwind(position_side="LONG", notional_usd=100.0, entry_price=100.0,
                         carnet_bids=[(99.0, 100.0)], carnet_asks=[(101.0, 100.0)], fee_bps=3.5)
    assert r["statut"] == "OK" and r["exit_price"] == 99.0
    assert r["unwind_gross_pnl_usd"] == -1.0 and r["unwind_net_pnl_usd"] < -1.0   # perte + frais


def test_simuler_unwind_short_achete_les_asks():
    r = M.simuler_unwind(position_side="SHORT", notional_usd=100.0, entry_price=100.0,
                         carnet_bids=[(99.0, 100.0)], carnet_asks=[(101.0, 100.0)], fee_bps=3.5)
    assert r["statut"] == "OK" and r["exit_price"] == 101.0 and r["unwind_gross_pnl_usd"] == -1.0


def test_simuler_unwind_carnet_insuffisant_unmeasurable():
    r = M.simuler_unwind(position_side="LONG", notional_usd=100.0, entry_price=100.0,
                         carnet_bids=[(99.0, 0.1)], carnet_asks=[])
    assert r["statut"] == "UNMEASURABLE"           # carnet trop mince pour déboucler → jamais un exit inventé


def test_hedge_echoue_simule_lunwind_contre_carnet():
    r = M.simuler_hedge(
        leg1={"notional_demande": 100.0, "notional_fill": 100.0, "ts_ms": 1000},
        leg2={"echec": True},
        carnet_unwind={"bids": [(99.0, 100.0)], "asks": [(101.0, 100.0)]},
        position_side="LONG", entry_price=100.0,
    )
    assert r["issue"] == M.UNWIND_REQUIRED
    assert r["unwind"]["statut"] == "OK" and r["unwind"]["unwind_notional_usd"] == 100.0
    assert r["unwind"]["unwind_gross_pnl_usd"] == -1.0


# --- agrégats scoreboard -----------------------------------------------------
def test_statistiques_agrege_echec_latence_residu_et_unwind():
    resumes = [
        M.simuler_hedge(leg1={"notional_demande": 100, "notional_fill": 100, "ts_ms": 0},
                        leg2={"notional_hedge": 100, "ts_ms": 200}),
        M.simuler_hedge(leg1={"notional_demande": 100, "notional_fill": 100, "ts_ms": 0},
                        leg2={"notional_hedge": 100, "ts_ms": 400}),
        M.simuler_hedge(leg1={"notional_demande": 100, "notional_fill": 100, "ts_ms": 0},
                        leg2={"echec": True},
                        carnet_unwind={"bids": [(99.0, 100.0)], "asks": [(101.0, 100.0)]},
                        position_side="LONG", entry_price=100.0),
        M.simuler_hedge(leg1={"notional_demande": 100, "notional_fill": 0}),
    ]
    stats = M.statistiques_hedge(resumes)
    assert stats["n_hedges_tentes"] == 3 and stats["failed_hedge_rate"] == round(1 / 3, 6)
    assert stats["hedge_latency_mediane_ms"] == 300.0
    assert stats["residual_exposure_total_usd"] == 100.0
    assert stats["n_unwinds_simules"] == 1 and stats["unwind_net_pnl_total_usd"] < 0
