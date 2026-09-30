"""P1B/P2 — agrégateur de mesures runtime → scoreboard (coûts/latence p50-99/capacity/fill/hedge)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.simulation import scoreboard_runtime_metrics as RM      # noqa: E402
from hl_observer.simulation import scoreboard_feeder as F                # noqa: E402
from hl_observer.simulation import ledger_integrity as LI               # noqa: E402
from hl_observer.simulation.paper_event import PaperEventType as ET      # noqa: E402
from hl_observer.arbitrage.cross_venue_state_machine import simuler_hedge  # noqa: E402


def test_percentiles_p50_p95_p99():
    p = RM.percentiles(list(range(1, 101)))
    assert p[0.5] == 50.0 and p[0.95] == 95.0 and p[0.99] == 99.0


def test_percentiles_vide_est_none():
    p = RM.percentiles([])
    assert p[0.5] is None and p[0.95] is None and p[0.99] is None


def test_couts_moyens_par_composante():
    couts = [{"fees_bps": 1.0, "spread_bps": 2.0, "slippage_bps": 1.0, "latency_bps": 0.5},
             {"fees_bps": 1.0, "spread_bps": 2.0, "slippage_bps": 3.0, "latency_bps": 0.5}]
    m = RM.agreger_mesures_strategie(couts_par_fill=couts, gross_edge_bps=25.0)["mesures"]
    assert m["fees_bps"] == 1.0 and m["slippage_bps"] == 2.0 and m["latency_bps"] == 0.5
    assert m["gross_edge_bps"] == 25.0


def test_latence_dans_mesures_et_p99_dans_extras():
    r = RM.agreger_mesures_strategie(latences_ms=list(range(1, 101)))
    assert r["mesures"]["latency_p50_ms"] == 50.0 and r["mesures"]["latency_p95_ms"] == 95.0
    assert r["metriques_runtime"]["latency_p99_ms"] == 99.0


def test_metrique_absente_est_unmeasurable_jamais_zero():
    r = RM.agreger_mesures_strategie(gross_edge_bps=25.0)   # aucun coût/latence/capacité/hedge
    assert "capacity_usd" in r["unmeasured"] and "fees_bps" in r["unmeasured"]
    assert r["metriques_runtime"]["latency_p99_ms"] is None
    assert r["metriques_runtime"]["failed_hedge_rate"] is None
    assert "fees_bps" not in r["mesures"]                   # les None ne polluent pas le feeder


def test_hedge_metriques_depuis_resumes_p93():
    resumes = [
        simuler_hedge(leg1={"notional_demande": 100, "notional_fill": 100, "ts_ms": 0},
                      leg2={"notional_hedge": 100, "ts_ms": 200}),
        simuler_hedge(leg1={"notional_demande": 100, "notional_fill": 100, "ts_ms": 0},
                      leg2={"echec": True},
                      carnet_unwind={"bids": [(99.0, 100.0)], "asks": [(101.0, 100.0)]},
                      position_side="LONG", entry_price=100.0),
    ]
    mr = RM.agreger_mesures_strategie(hedge_resumes=resumes)["metriques_runtime"]
    assert mr["failed_hedge_rate"] == 0.5 and mr["residual_exposure_total_usd"] == 100.0
    assert mr["hedge_latency_mediane_ms"] == 200.0 and mr["unwind_net_pnl_total_usd"] < 0


def test_bout_en_bout_les_observations_runtime_alimentent_le_scoreboard():
    obs = {"cross_venue_dislocation": {
        "couts_par_fill": [{"fees_bps": 1.0, "spread_bps": 2.0, "slippage_bps": 1.0, "latency_bps": 1.0}],
        "gross_edge_bps": 25.0, "capacity_usd": 5000.0, "fill_ratios": [1.0],
        "latences_ms": [100, 150, 200], "oos_net_bps": 6.0, "forward_net_bps": 4.0,
    }}
    paquet = RM.mesures_par_strategie(obs)

    def _ev(eid, et, **kw):
        b = {"event_id": eid, "event_type": et, "timestamp_ms": 0}
        b.update(kw)
        return b
    raw = [
        _ev("o1", ET.POSITION_OPENED.value, coin="BTC", side="LONG", quantity=1.0,
            refs={"strategy": "cross_venue_dislocation", "position_id": "p1"}),
        _ev("c1", ET.POSITION_CLOSED.value, coin="BTC", side="LONG", quantity=1.0, realized_pnl_usdc=5.0,
            refs={"strategy": "cross_venue_dislocation", "position_id": "p1"}),
    ]
    sealed = list(LI.seal_chain(raw, session_id="S"))
    res = F.lignes_depuis_ledger(sealed, mesures_par_strategie=paquet["mesures_par_strategie"])
    row = {r.strategy: r for r in res.rows}["cross_venue_dislocation"]
    assert row.net_bps == 20.0          # gross 25 − coûts (1+2+1+1)=5 → net 20, alimenté par le runtime
    assert row.capacity_usd == 5000.0 and row.latency_p95_ms is not None
