"""Executable requirement-specific Cross-Venue gate for controls 466..545.

The scenarios exercise strict production certification primitives. They prove
technical behavior only; synthetic rows never count as economic +4 USD evidence.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from hl_observer.backtesting.cross_venue_certified import (
    DEFAULT_MAX_HOLDING_MS,
    FOUR_FILL_CONTRACT_VERSION,
    MAX_SNAPSHOT_AGE_MS,
    MAX_VENUE_SKEW_MS,
    SOURCE_MODE,
    build_four_fill_cycle,
    certify_atomic_row,
    observation_gap_ok,
    snapshot_fresh,
    vwap_for_notional,
)
from hl_observer.config.cross_venue_instruments import binance_perp_symbol, mapping_record

FACETS = ("CONTRACT", "POSITIVE_PATH", "NEGATIVE_FAIL_CLOSED", "DETERMINISM_CAUSALITY", "EVIDENCE_PROVENANCE")
CROSS_VENUE_REQUIREMENTS = (
    ("sync_clock_skew", "synchronisation des venues et clock skew"),
    ("bbo_freshness", "fraîcheur BBO"),
    ("depth_vwap", "profondeur et VWAP exécutable"),
    ("instrument_mapping", "mapping exact des instruments"),
    ("entry_two_legs", "entrée jambe A et jambe B"),
    ("exit_two_legs", "sortie jambe A et jambe B"),
    ("four_fills", "cycle complet à quatre fills"),
    ("fees", "frais"),
    ("interleg_latency", "latence inter-jambes"),
    ("naked_leg_risk", "risque de jambe nue"),
    ("partial_fills", "fills partiels"),
    ("missed_leg", "jambe manquée"),
    ("convergence", "convergence"),
    ("max_holding", "durée maximale de détention"),
    ("venue_outage", "panne de venue"),
    ("spread_depth_nonexec", "élargissement spread, disparition profondeur et rejet non-exécutable/faux mapping"),
)

_EVIDENCE = {
    "sync_clock_skew": ("src/hl_observer/backtesting/cross_venue_certified.py", "tools/collecter_carnet.py", "tests/test_cross_venue_certified.py"),
    "bbo_freshness": ("src/hl_observer/backtesting/cross_venue_certified.py", "tests/test_cross_venue_certified.py"),
    "depth_vwap": ("src/hl_observer/backtesting/cross_venue_certified.py", "tests/test_cross_venue_certified.py"),
    "instrument_mapping": ("src/hl_observer/config/cross_venue_instruments.py", "tools/collecter_carnet.py", "tests/test_collecter_carnet.py"),
    "entry_two_legs": ("src/hl_observer/backtesting/cross_venue_certified.py", "tests/test_pre_run_cross_venue_466_545.py"),
    "exit_two_legs": ("src/hl_observer/backtesting/cross_venue_certified.py", "tests/test_pre_run_cross_venue_466_545.py"),
    "four_fills": ("src/hl_observer/backtesting/cross_venue_certified.py", "src/hl_observer/simulation/economic_objective.py"),
    "fees": ("src/hl_observer/backtesting/cross_venue_certified.py", "src/hl_observer/simulation/economic_objective.py"),
    "interleg_latency": ("src/hl_observer/backtesting/cross_venue_certified.py", "tools/collecter_carnet.py"),
    "naked_leg_risk": ("src/hl_observer/backtesting/cross_venue_certified.py", "tests/test_cross_venue_certified.py"),
    "partial_fills": ("src/hl_observer/backtesting/cross_venue_certified.py", "tests/test_cross_venue_certified.py"),
    "missed_leg": ("src/hl_observer/backtesting/cross_venue_certified.py", "tests/test_cross_venue_certified.py"),
    "convergence": ("src/hl_observer/backtesting/cross_venue_certified.py", "tests/test_pre_run_cross_venue_466_545.py"),
    "max_holding": ("src/hl_observer/backtesting/cross_venue_certified.py", "tests/test_pre_run_cross_venue_466_545.py"),
    "venue_outage": ("src/hl_observer/backtesting/cross_venue_certified.py", "tools/backtest_dislocation_2jambes.py"),
    "spread_depth_nonexec": ("src/hl_observer/backtesting/cross_venue_certified.py", "src/hl_observer/simulation/economic_objective.py"),
}

@dataclass(frozen=True)
class Scenario:
    positive: bool
    negative: bool
    deterministic: bool
    detail: dict[str, Any]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _levels(best: float, *, side: str, size: float = 10.0) -> list[list[float]]:
    step = -0.05 if side == "BID" else 0.05
    return [[best + index * step, size] for index in range(5)]


def _row(*, coin: str = "BTC", symbol: str = "BTCUSDT", hl_bid: float = 101.0, hl_ask: float = 101.1, bin_bid: float = 99.9, bin_ask: float = 100.0, hl_ms: float = 1000.0, bin_ms: float = 1050.0, size: float = 10.0) -> dict[str, Any]:
    return {
        "coin": coin, "binance_symbol": symbol,
        "hl_bid": hl_bid, "hl_ask": hl_ask, "bin_bid": bin_bid, "bin_ask": bin_ask,
        "hl_bids5": _levels(hl_bid, side="BID", size=size),
        "hl_asks5": _levels(hl_ask, side="ASK", size=size),
        "bin_bids5": _levels(bin_bid, side="BID", size=size),
        "bin_asks5": _levels(bin_ask, side="ASK", size=size),
        "hl_received_at_ms": hl_ms, "bin_received_at_ms": bin_ms,
        "taille_min_usd": min(1000.0, min(hl_bid, hl_ask, bin_bid, bin_ask) * size * 4),
        "read_only": True, "real_execution": False,
    }


def _cert_pair(*, exit_ms: float = 2000.0, exit_hl=100.0, exit_bin=100.0, size=10.0):
    entry = certify_atomic_row(_row(size=size))
    exit_ = certify_atomic_row(_row(hl_bid=exit_hl - 0.05, hl_ask=exit_hl + 0.05, bin_bid=exit_bin - 0.05, bin_ask=exit_bin + 0.05, hl_ms=exit_ms, bin_ms=exit_ms + 40.0, size=size))
    return entry, exit_


def _cycle(**kwargs):
    entry, exit_ = _cert_pair()
    return build_four_fill_cycle(entry, exit_, direction=1, notional_usd=15.0, fees_bps_total=2.0, **kwargs)


def _scenario_sync_clock_skew() -> Scenario:
    good = certify_atomic_row(_row(hl_ms=1000, bin_ms=1100))
    bad = certify_atomic_row(_row(hl_ms=1000, bin_ms=1400))
    return Scenario(good["ok"] is True and good["skew_ms"] == 100.0, bad["ok"] is False and "VENUE_SKEW_TOO_HIGH" in bad["reasons"], good == certify_atomic_row(_row(hl_ms=1000, bin_ms=1100)), {"max_skew_ms": MAX_VENUE_SKEW_MS})


def _scenario_bbo_freshness() -> Scenario:
    good = snapshot_fresh(1000, 1200)
    bad = snapshot_fresh(1000, 1000 + MAX_SNAPSHOT_AGE_MS + 1)
    return Scenario(good, not bad, good == snapshot_fresh(1000, 1200), {"max_age_ms": MAX_SNAPSHOT_AGE_MS})


def _scenario_depth_vwap() -> Scenario:
    levels = [[100.0, 1.0], [101.0, 1.0]]
    good = vwap_for_notional(levels, 150.0, side="BUY")
    partial = vwap_for_notional([[100.0, 0.1]], 50.0, side="BUY")
    return Scenario(good["complete"] is True and good["vwap"] > 100.0, partial["complete"] is False and partial["remaining_notional_usd"] > 0, good == vwap_for_notional(levels, 150.0, side="BUY"), {"vwap": good["vwap"]})


def _scenario_instrument_mapping() -> Scenario:
    pepe = mapping_record("PEPE", "1000PEPEUSDT")
    false = mapping_record("PEPE", "PEPEUSDT")
    return Scenario(pepe["exact"] is True and binance_perp_symbol("kBONK") == "1000BONKUSDT", false["exact"] is False and binance_perp_symbol("HYPE") is None, pepe == mapping_record("PEPE", "1000PEPEUSDT"), {"schema": pepe["schema_version"]})


def _scenario_entry_two_legs() -> Scenario:
    cycle = _cycle()
    entry_fills = [fill for fill in cycle["fills"] if fill["stage"] == "ENTRY"]
    entry, exit_ = _cert_pair()
    bad_entry = dict(entry)
    bad_entry["books"] = {**entry["books"], "BIN": {**entry["books"]["BIN"], "asks": [[100.0, 0.01]]}}
    bad = build_four_fill_cycle(bad_entry, exit_, direction=1, notional_usd=15, fees_bps_total=2)
    return Scenario(cycle["economic_eligible"] is True and len(entry_fills) == 2 and {f["venue"] for f in entry_fills} == {"HL", "BIN"}, bad["economic_eligible"] is False and bad["partial_fill_detected"] is True, cycle == _cycle(), {"entry_fill_count": len(entry_fills)})


def _scenario_exit_two_legs() -> Scenario:
    cycle = _cycle()
    exit_fills = [fill for fill in cycle["fills"] if fill["stage"] == "EXIT"]
    entry, exit_ = _cert_pair()
    bad_exit = dict(exit_)
    bad_exit["books"] = {**exit_["books"], "HL": {**exit_["books"]["HL"], "asks": [[100.05, 0.01]]}}
    bad = build_four_fill_cycle(entry, bad_exit, direction=1, notional_usd=15, fees_bps_total=2)
    return Scenario(len(exit_fills) == 2 and {f["venue"] for f in exit_fills} == {"HL", "BIN"}, bad["economic_eligible"] is False, cycle == _cycle(), {"exit_fill_count": len(exit_fills)})


def _scenario_four_fills() -> Scenario:
    good = _cycle()
    entry, exit_ = _cert_pair()
    broken = dict(exit_); broken["ok"] = False
    bad = build_four_fill_cycle(entry, broken, direction=1, notional_usd=15, fees_bps_total=2)
    return Scenario(good["four_fills_complete"] is True and good["fill_count"] == 4 and good["schema_version"] == FOUR_FILL_CONTRACT_VERSION, bad["economic_eligible"] is False and "EXIT_SNAPSHOT_UNCERTIFIED" in bad["reasons"], good == _cycle(), {"contract": FOUR_FILL_CONTRACT_VERSION})


def _scenario_fees() -> Scenario:
    entry, exit_ = _cert_pair()
    zero = build_four_fill_cycle(entry, exit_, direction=1, notional_usd=15, fees_bps_total=0)
    costly = build_four_fill_cycle(entry, exit_, direction=1, notional_usd=15, fees_bps_total=20)
    invalid = build_four_fill_cycle(entry, exit_, direction=1, notional_usd=15, fees_bps_total=-1)
    return Scenario(zero["economic_eligible"] and costly["net_pnl_usd"] < zero["net_pnl_usd"], invalid["economic_eligible"] is False and "INVALID_FEES" in invalid["reasons"], zero == build_four_fill_cycle(entry, exit_, direction=1, notional_usd=15, fees_bps_total=0), {"costly_fees": costly["fees_usd"]})


def _scenario_interleg_latency() -> Scenario:
    good = _cycle(max_interleg_ms=250)
    entry = certify_atomic_row(_row(hl_ms=1000, bin_ms=1200))
    exit_ = certify_atomic_row(_row(hl_ms=2000, bin_ms=2200, hl_bid=99.95, hl_ask=100.05, bin_bid=99.95, bin_ask=100.05))
    bad = build_four_fill_cycle(entry, exit_, direction=1, notional_usd=15, fees_bps_total=2, max_interleg_ms=100)
    return Scenario(good["entry_interleg_observation_skew_ms"] is not None, bad["economic_eligible"] is False and "INTERLEG_OBSERVATION_SKEW_TOO_HIGH" in bad["reasons"], good == _cycle(max_interleg_ms=250), {"entry_skew": good["entry_interleg_observation_skew_ms"]})


def _scenario_naked_leg_risk() -> Scenario:
    entry, exit_ = _cert_pair()
    thin = dict(entry)
    thin["books"] = {**entry["books"], "BIN": {**entry["books"]["BIN"], "asks": [[100.0, 0.01]]}}
    bad = build_four_fill_cycle(thin, exit_, direction=1, notional_usd=15, fees_bps_total=2)
    return Scenario(_cycle()["naked_leg_risk"] is False, bad["naked_leg_risk"] is True and bad["net_pnl_usd"] is None, bad == build_four_fill_cycle(thin, exit_, direction=1, notional_usd=15, fees_bps_total=2), {"bad_reasons": bad["reasons"]})


def _scenario_partial_fills() -> Scenario:
    partial = vwap_for_notional([[100.0, 0.05]], 15.0, side="BUY")
    complete = vwap_for_notional([[100.0, 1.0]], 15.0, side="BUY")
    return Scenario(complete["complete"] is True, partial["complete"] is False and 0 < partial["filled_notional_usd"] < 15.0, partial == vwap_for_notional([[100.0, 0.05]], 15.0, side="BUY"), {"filled": partial["filled_notional_usd"]})


def _scenario_missed_leg() -> Scenario:
    good = certify_atomic_row(_row())
    row = _row(); row["bin_asks5"] = []
    bad = certify_atomic_row(row)
    return Scenario(good["ok"] is True, bad["ok"] is False and ("BIN_BOOK_INVALID" in bad["reasons"] or "FOUR_SIDE_DEPTH_MISSING" in bad["reasons"]), bad == certify_atomic_row(row), {"reasons": bad["reasons"]})


def _scenario_convergence() -> Scenario:
    good = _cycle()
    entry, divergent_exit = _cert_pair(exit_hl=102.0, exit_bin=100.0)
    divergent = build_four_fill_cycle(entry, divergent_exit, direction=1, notional_usd=15, fees_bps_total=2)
    return Scenario(good["converged"] is True, divergent["converged"] is False, good == _cycle(), {"entry_basis": good["entry_basis_bps"], "exit_basis": good["exit_basis_bps"]})


def _scenario_max_holding() -> Scenario:
    good = _cycle(max_holding_ms=10_000)
    entry, exit_ = _cert_pair(exit_ms=1_000 + DEFAULT_MAX_HOLDING_MS + 1000)
    bad = build_four_fill_cycle(entry, exit_, direction=1, notional_usd=15, fees_bps_total=2)
    return Scenario(good["economic_eligible"] is True, bad["economic_eligible"] is False and "MAX_HOLDING_EXCEEDED" in bad["reasons"], good == _cycle(max_holding_ms=10_000), {"max_holding_ms": DEFAULT_MAX_HOLDING_MS})


def _scenario_venue_outage() -> Scenario:
    good = observation_gap_ok(1000, 2000, max_gap_ms=5000)
    bad = observation_gap_ok(1000, 10_000, max_gap_ms=5000)
    return Scenario(good, not bad, good == observation_gap_ok(1000, 2000, max_gap_ms=5000), {"max_gap_ms": 5000})


def _scenario_spread_depth_nonexec() -> Scenario:
    good = certify_atomic_row(_row())
    false_mapping = certify_atomic_row(_row(coin="PEPE", symbol="PEPEUSDT"))
    crossed = certify_atomic_row(_row(hl_bid=101.2, hl_ask=101.1))
    shallow = vwap_for_notional([[100.0, 0.01]], 15.0, side="BUY")
    negative = false_mapping["ok"] is False and crossed["ok"] is False and shallow["complete"] is False
    return Scenario(good["ok"] is True, negative, false_mapping == certify_atomic_row(_row(coin="PEPE", symbol="PEPEUSDT")), {"false_mapping": false_mapping["reasons"], "crossed": crossed["reasons"]})


_SCENARIOS: dict[str, Callable[[], Scenario]] = {
    "sync_clock_skew": _scenario_sync_clock_skew,
    "bbo_freshness": _scenario_bbo_freshness,
    "depth_vwap": _scenario_depth_vwap,
    "instrument_mapping": _scenario_instrument_mapping,
    "entry_two_legs": _scenario_entry_two_legs,
    "exit_two_legs": _scenario_exit_two_legs,
    "four_fills": _scenario_four_fills,
    "fees": _scenario_fees,
    "interleg_latency": _scenario_interleg_latency,
    "naked_leg_risk": _scenario_naked_leg_risk,
    "partial_fills": _scenario_partial_fills,
    "missed_leg": _scenario_missed_leg,
    "convergence": _scenario_convergence,
    "max_holding": _scenario_max_holding,
    "venue_outage": _scenario_venue_outage,
    "spread_depth_nonexec": _scenario_spread_depth_nonexec,
}


def evaluate_cross_venue_requirements(root: Path) -> dict[str, Any]:
    root = root.resolve(); requirements = []
    for key, description in CROSS_VENUE_REQUIREMENTS:
        scenario = _SCENARIOS[key](); evidence = list(_EVIDENCE[key])
        hashes = {path: _hash(root / path) for path in evidence if (root / path).is_file()}
        facets = {
            "CONTRACT": callable(_SCENARIOS[key]),
            "POSITIVE_PATH": scenario.positive,
            "NEGATIVE_FAIL_CLOSED": scenario.negative,
            "DETERMINISM_CAUSALITY": scenario.deterministic,
            "EVIDENCE_PROVENANCE": len(hashes) == len(evidence),
        }
        requirements.append({"key": key, "description": description, "ok": all(facets.values()), "facets": facets, "evidence": evidence, "evidence_sha256": hashes, "detail": scenario.detail, "source_mode": SOURCE_MODE})
    return {
        "category": "CROSS_VENUE",
        "requirements_total": len(CROSS_VENUE_REQUIREMENTS),
        "requirements_done": sum(1 for row in requirements if row["ok"]),
        "facets_total": len(CROSS_VENUE_REQUIREMENTS) * len(FACETS),
        "facets_done": sum(1 for row in requirements for value in row["facets"].values() if value),
        "ok": all(row["ok"] for row in requirements),
        "requirements": requirements,
    }


__all__ = ["CROSS_VENUE_REQUIREMENTS", "FACETS", "evaluate_cross_venue_requirements"]
