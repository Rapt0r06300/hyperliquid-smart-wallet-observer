"""Câblage-2 — le producteur runtime accumule les observations → scoreboard réconcilié depuis le ledger."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.simulation.scoreboard_producer import ScoreboardProducer   # noqa: E402
from hl_observer.simulation import ledger_integrity as LI                    # noqa: E402
from hl_observer.simulation.paper_event import PaperEventType as ET          # noqa: E402
from hl_observer.arbitrage.cross_venue_state_machine import simuler_hedge    # noqa: E402


def _ev(eid, et, **kw):
    b = {"event_id": eid, "event_type": et, "timestamp_ms": 0}
    b.update(kw)
    return b


def _ledger(strat, n, pnl=2.0):
    raw = []
    for i in range(n):
        pid = f"{strat}-p{i}"
        raw += [
            _ev(f"o{i}", ET.POSITION_OPENED.value, coin="BTC", side="LONG", quantity=1.0,
                refs={"strategy": strat, "position_id": pid}),
            _ev(f"c{i}", ET.POSITION_CLOSED.value, coin="BTC", side="LONG", quantity=1.0,
                realized_pnl_usdc=pnl, refs={"strategy": strat, "position_id": pid}),
        ]
    return list(LI.seal_chain(raw, session_id="S"))


def test_producteur_accumule_et_produit_le_scoreboard():
    p = ScoreboardProducer()
    for _ in range(3):
        p.observer_fill("cross_venue_dislocation",
                        cost_components={"fees_bps": 1.0, "spread_bps": 2.0, "slippage_bps": 1.0, "latency_bps": 1.0},
                        latency_ms=120.0, fill_ratio=1.0)
    p.fixer_mesures("cross_venue_dislocation", gross_edge_bps=25.0, capacity_usd=5000.0,
                    oos_net_bps=6.0, forward_net_bps=4.0, roi_denominator_usd=1000.0)

    d = p.produire(_ledger("cross_venue_dislocation", 3))
    row = {r["strategy"]: r for r in d["rows"]}["cross_venue_dislocation"]
    assert row["net_bps"] == 20.0                     # gross 25 − coûts 5, alimenté par le runtime
    assert row["capacity_usd"] == 5000.0 and row["latency_p95_ms"] is not None
    extras = d["metriques_runtime_par_strategie"]["cross_venue_dislocation"]
    assert extras["latency_p99_ms"] is not None


def test_producteur_agrege_les_hedges_dans_les_extras():
    p = ScoreboardProducer()
    p.observer_hedge("cross_venue_dislocation",
                     simuler_hedge(leg1={"notional_demande": 100, "notional_fill": 100, "ts_ms": 0},
                                   leg2={"echec": True},
                                   carnet_unwind={"bids": [(99.0, 100.0)], "asks": [(101.0, 100.0)]},
                                   position_side="LONG", entry_price=100.0))
    d = p.produire(_ledger("cross_venue_dislocation", 1))
    extras = d["metriques_runtime_par_strategie"]["cross_venue_dislocation"]
    assert extras["failed_hedge_rate"] == 1.0 and extras["residual_exposure_total_usd"] == 100.0


def test_sans_observations_les_couts_restent_unmeasurable():
    p = ScoreboardProducer()
    d = p.produire(_ledger("copy_vault", 2))
    row = {r["strategy"]: r for r in d["rows"]}["copy_vault"]
    assert row["pnl_usd"] == 4.0 and row["net_bps"] is None      # PnL du ledger, coûts UNMEASURABLE


def test_promotion_evaluee_si_evidence_fournie():
    from hl_observer.simulation.scoreboard_promotion import ScoreboardPromotionEvidence
    p = ScoreboardProducer()
    for _ in range(3):
        p.observer_fill("copy_vault",
                        cost_components={"fees_bps": 1.0, "spread_bps": 2.0, "slippage_bps": 1.0, "latency_bps": 1.0},
                        latency_ms=120.0, fill_ratio=1.0)
    p.fixer_mesures("copy_vault", gross_edge_bps=25.0, capacity_usd=5000.0, oos_net_bps=6.0, forward_net_bps=4.0)
    ev = {"copy_vault": ScoreboardPromotionEvidence(
        ledger_trusted=True, placebo_beaten=True, pbo_robuste=True, dsr_ok=True,
        lower_confidence_bound_bps=3.0, concentration=0.1, n_days=10, n_regimes=3, n_coins=2, min_coins=1)}
    d = p.produire(_ledger("copy_vault", 25), evidence_par_strategie=ev)
    assert d["promotions"]["copy_vault"]["verdict"] == "PROMOTE"     # plomberie (ledger synthétique)
