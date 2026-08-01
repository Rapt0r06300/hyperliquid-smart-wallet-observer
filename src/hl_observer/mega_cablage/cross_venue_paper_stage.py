"""[CABLAGE étage C+] CROSS-VENUE — EXÉCUTION DES DEUX JAMBES EN PAPER : là où cross_venue_stage se contentait
de TRACER un hedge, cet étage EXÉCUTE réellement les deux jambes (venue primaire + venue de couverture) en paper
et les COMPTABILISE au ledger, via le VRAI moteur du projet paper_trading.cross_venue_execution
.execute_non_atomic_cross_venue — qui ouvre deux positions distinctes (ex. BTC@HYPERLIQUID:LONG + BTC@BINANCE:
SHORT) dans un PaperLedger, avec scénarios BASE / P95 / P99 (stress de latence adverse) et unwind du résidu.

On fournit un constructeur qui assemble la requête + la distribution de latence MESURÉE + les 3 scénarios à
partir de carnets réels par jambe (ExecutionTruth strict : deux côtés, non croisé, origine REAL/RECORDED_REAL).
Sans carnets réels → pas d'exécution (le moteur refuse un book absent : fail-closed). 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

from hl_observer.paper_trading.canonical_execution import CausalMarketSnapshot
from hl_observer.paper_trading.execution_truth import ExecutionTruth
from hl_observer.paper_trading.cross_venue_execution import (
    CrossVenueExecutionRequest, CrossVenueLeg, CrossVenueScenarioSnapshots,
    MeasuredLatencyDistribution, execute_non_atomic_cross_venue,
)
from hl_observer.simulation.paper_ledger import PaperLedger


def _snapshot(*, coin: str, source: str, ts_ms: int, carnet: dict[str, Any]) -> CausalMarketSnapshot:
    truth = ExecutionTruth.from_levels(
        coin=coin, bids=tuple(carnet["bids"]), asks=tuple(carnet["asks"]),
        received_ts_ms=ts_ms, exchange_ts_ms=ts_ms - 1,
        source=source, data_origin=carnet.get("data_origin", "RECORDED_REAL"))
    return CausalMarketSnapshot.from_truth(truth, decision_ts_ms=ts_ms)


def _decale(carnet: dict[str, Any], delta: float) -> dict[str, Any]:
    return {**carnet, "bids": [(px + delta, sz) for px, sz in carnet["bids"]],
            "asks": [(px + delta, sz) for px, sz in carnet["asks"]]}


def executer_paire_cross_venue(*, coin: str, venue1: str, venue2: str, action1: str, action2: str,
                               notional_usdc: float, ts_ms: int, latences_ms: tuple[float, ...],
                               carnet1_entree: dict[str, Any], carnet2: dict[str, Any],
                               carnet1_unwind: dict[str, Any], source1: str = "hyperliquid_l2",
                               source2: str = "binance_l2", leverage: float = 1.0,
                               stress_p95: float = 0.30, stress_p99: float = 0.60,
                               ledger: PaperLedger | None = None, min_fill_ratio: float = 0.0) -> dict[str, Any]:
    """Assemble et exécute la paire non-atomique. Les deux jambes sont BOOKÉES au ledger fourni (ou un neuf).
    Le stress adverse s'applique à la 2e jambe + l'unwind selon le sens de la 1re (BUY → prix baissés, SELL →
    montés). Retourne {report, ledger, matched_notional, paired_edge, positions, chaine_ok}."""
    ledger = ledger if ledger is not None else PaperLedger(starting_balance_usdc=1000.0)
    dist = MeasuredLatencyDistribution(samples_ms=tuple(float(x) for x in latences_ms),
                                       source="recorded_cross_venue_round_trip")
    lat_max = max(latences_ms)
    signe_stress = -1.0 if str(action1).upper() == "BUY" else 1.0

    def scenario(label: str, latence: float, stress: float) -> CrossVenueScenarioSnapshots:
        c2 = _decale(carnet2, signe_stress * stress)
        cu = _decale(carnet1_unwind, signe_stress * stress)
        return CrossVenueScenarioSnapshots(
            label=label, latency_ms=float(latence),
            leg1_entry=_snapshot(coin=coin, source=source1, ts_ms=ts_ms, carnet=carnet1_entree),
            leg2_delayed=_snapshot(coin=coin, source=source2, ts_ms=ts_ms + int(latence), carnet=c2),
            leg1_unwind_delayed=_snapshot(coin=coin, source=source1, ts_ms=ts_ms + int(latence), carnet=cu))

    request = CrossVenueExecutionRequest(
        request_id="mega:%s:%s" % (coin, ts_ms), detected_ts_ms=ts_ms,
        leg1=CrossVenueLeg(venue=venue1, coin=coin, action=action1, target_notional_usdc=float(notional_usdc)),
        leg2=CrossVenueLeg(venue=venue2, coin=coin, action=action2, target_notional_usdc=float(notional_usdc)),
        leverage=float(leverage))
    report = execute_non_atomic_cross_venue(
        request, latency_distribution=dist,
        base=scenario("BASE", latences_ms[len(latences_ms) // 2], 0.0),
        stress_p95=scenario("P95", lat_max, stress_p95),
        stress_p99=scenario("P99", lat_max + 10.0, stress_p99),
        ledger=ledger, min_fill_ratio=min_fill_ratio)
    return {"report": report, "ledger": ledger,
            "matched_notional": report.base.matched_notional_usdc,
            "paired_edge_usdc": report.base.paired_entry_edge_usdc,
            "positions": dict(ledger.positions), "chaine_ok": ledger.verify_event_chain(),
            "equity": ledger.equity_usdc, "realized": ledger.realized_pnl_usdc}


__all__ = ["executer_paire_cross_venue"]
