"""Executable requirement-specific gate for Lead-Lag controls 396..465.

Each preserved Lead-Lag requirement is exercised against production primitives.
The scenarios are synthetic, deterministic and paper/read-only: they prove
technical behavior, never strategy profitability on real data.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from hl_observer.backtesting import lead_lag_shadow as base
from hl_observer.backtesting.lead_lag_certified_backtest import (
    backtest_certified,
    certified_event_time_ns,
    load_certified_tape,
    partition_universe,
)
from hl_observer.backtesting.lead_lag_shadow_economics import (
    _metriques,
    _placebo_direction,
    episodes_par_horizon,
    executable_campaign_evidence,
)
from hl_observer.experimental.metaorder_l2_tape import (
    add_cancel_imbalance,
    depth_shape,
    latence_pipeline_ms,
    microprice,
    ofi_multi_niveaux,
    profondeur_top5,
    queue_depletion,
    resume_book,
)

FACETS = (
    "CONTRACT",
    "POSITIVE_PATH",
    "NEGATIVE_FAIL_CLOSED",
    "DETERMINISM_CAUSALITY",
    "EVIDENCE_PROVENANCE",
)

LEAD_LAG_REQUIREMENTS = (
    ("certified_timestamps", "timestamps certifiables et rejet des horloges non certifiables"),
    ("causality_real_lag", "causalité et lag réel"),
    ("multi_horizon", "multi-horizon"),
    ("regimes", "régimes"),
    ("clock_second_minute", "début de seconde et horizon minute"),
    ("clock_5m_15m", "horizons 5 minutes et 15 minutes"),
    ("ofi_microprice", "OFI et microprice"),
    ("queue_depletion", "queue depletion"),
    ("adds_cancels", "ajouts et annulations"),
    ("depth", "profondeur"),
    ("latency", "latence"),
    ("universe", "univers"),
    ("cost_stress", "stress de coûts"),
    ("placebos", "placebos"),
)

_EVIDENCE = {
    "certified_timestamps": (
        "src/hl_observer/backtesting/lead_lag_certified_backtest.py",
        "src/hl_observer/backtesting/lead_lag_certified_clock.py",
        "tests/test_lead_lag_certified_clock.py",
    ),
    "causality_real_lag": (
        "src/hl_observer/backtesting/lead_lag_shadow_economics.py",
        "tests/test_lead_lag_shadow.py",
    ),
    "multi_horizon": (
        "src/hl_observer/backtesting/lead_lag_shadow.py",
        "src/hl_observer/backtesting/lead_lag_shadow_economics.py",
        "tests/test_pre_run_lead_lag_396_465.py",
    ),
    "regimes": (
        "src/hl_observer/backtesting/lead_lag_shadow_economics.py",
        "tests/test_lead_lag_shadow.py",
    ),
    "clock_second_minute": (
        "src/hl_observer/backtesting/lead_lag_shadow_economics.py",
        "tests/test_pre_run_lead_lag_396_465.py",
    ),
    "clock_5m_15m": (
        "src/hl_observer/backtesting/lead_lag_shadow_economics.py",
        "tests/test_pre_run_lead_lag_396_465.py",
    ),
    "ofi_microprice": (
        "src/hl_observer/experimental/metaorder_l2_tape.py",
        "tests/test_metaorder_l2_tape.py",
    ),
    "queue_depletion": (
        "src/hl_observer/experimental/metaorder_l2_tape.py",
        "tests/test_metaorder_l2_tape.py",
    ),
    "adds_cancels": (
        "src/hl_observer/experimental/metaorder_l2_tape.py",
        "tests/test_metaorder_l2_tape.py",
    ),
    "depth": (
        "src/hl_observer/experimental/metaorder_l2_tape.py",
        "src/hl_observer/backtesting/lead_lag_shadow_economics.py",
    ),
    "latency": (
        "src/hl_observer/experimental/metaorder_l2_tape.py",
        "src/hl_observer/backtesting/lead_lag_shadow_economics.py",
    ),
    "universe": (
        "src/hl_observer/backtesting/lead_lag_certified_backtest.py",
        "tests/test_pre_run_lead_lag_396_465.py",
    ),
    "cost_stress": (
        "src/hl_observer/backtesting/lead_lag_shadow_economics.py",
        "tests/test_pre_run_lead_lag_396_465.py",
    ),
    "placebos": (
        "src/hl_observer/backtesting/lead_lag_shadow_economics.py",
        "src/hl_observer/backtesting/lead_lag_certified_backtest.py",
    ),
}


@dataclass(frozen=True)
class Scenario:
    positive: bool
    negative: bool
    deterministic: bool
    detail: dict[str, Any]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hl_quotes(signal_ns: int, horizons_ms: tuple[float, ...], *, with_sizes: bool = True) -> list:
    size = 20.0 if with_sizes else None
    rows = [
        (signal_ns - 5_000_000, 100.0, 99.99, 100.01, size, size),
        (signal_ns + 5_000_000, 100.1, 100.09, 100.11, size, size),
    ]
    for index, horizon in enumerate(sorted(set(float(value) for value in horizons_ms)), start=1):
        target = signal_ns + int(horizon * 1_000_000.0)
        mid = 100.1 + index * 0.5
        rows.append((target, mid, mid - 0.01, mid + 0.01, size, size))
    return sorted(rows)


def _episode(
    horizon: float,
    *,
    signal_ns: int = 10_000_000,
    fees_bps: float = 9.0,
    with_sizes: bool = True,
):
    rows = episodes_par_horizon(
        _hl_quotes(signal_ns, (horizon,), with_sizes=with_sizes),
        [(signal_ns, 1.0)],
        frais_slippage_bps=fees_bps,
        horizons_ms=(float(horizon),),
        coin="ETH",
        notional_usd=25.0,
    )[float(horizon)]
    return rows[0] if rows else None


def _raw_book(*, bid=100.0, ask=100.2, bid_sizes=(10, 8, 6, 4, 2), ask_sizes=(5, 6, 7, 8, 9)):
    bids = [
        {"px": str(bid - index * 0.1), "sz": str(size), "n": index + 1}
        for index, size in enumerate(bid_sizes)
    ]
    asks = [
        {"px": str(ask + index * 0.1), "sz": str(size), "n": index + 1}
        for index, size in enumerate(ask_sizes)
    ]
    return {"time": 123, "levels": [bids, asks]}


def _scenario_certified_timestamps() -> Scenario:
    good = certified_event_time_ns({"ts_wall_ms": 1234.5, "recu_ns": 99})
    monotonic_only = certified_event_time_ns({"recu_ns": 123})
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        tape = root / "runtime/data/bbo_tape.jsonl"
        tape.parent.mkdir(parents=True)
        rows = [
            {
                "event_id": "wall",
                "venue": "HL",
                "coin": "ETH",
                "ts_wall_ms": 1000,
                "recu_ns": 9_999_999_999,
                "mid": 100,
                "bid": 99.9,
                "ask": 100.1,
                "bid_sz": 2,
                "ask_sz": 2,
            },
            {
                "event_id": "mono",
                "venue": "BIN_TRADE",
                "coin": "ETH",
                "recu_ns": 1,
                "px": 101,
                "side": "BUY",
            },
        ]
        tape.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        first, meta = load_certified_tape(root, return_meta=True)
        second, meta2 = load_certified_tape(root, return_meta=True)
    positive = good == 1_234_500_000 and len(first["ETH"]["HL"]) == 1
    negative = monotonic_only is None and meta["uncertifiable_clock_rows"] == 1 and not first["ETH"]["TRADE"]
    return Scenario(positive, negative, (first, meta) == (second, meta2), {"rejected": meta["uncertifiable_clock_rows"]})


def _scenario_causality_real_lag() -> Scenario:
    row = _episode(100.0)
    no_reference = episodes_par_horizon(
        [
            (15_000_000, 100.1, 100.09, 100.11, 20.0, 20.0),
            (110_000_000, 100.6, 100.59, 100.61, 20.0, 20.0),
        ],
        [(10_000_000, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=(100.0,),
        coin="ETH",
    )[100.0][0]
    positive = bool(
        row
        and row["entry_ts_ns"] >= row["signal_ts_ns"]
        and row["exit_ts_ns"] >= row["signal_ts_ns"] + 100_000_000
        and row["entry_latency_ms"] >= 0
        and row["reference_status"] == "OBSERVED_AT_OR_BEFORE_SIGNAL"
    )
    negative = no_reference["liquidatable_net"] is False and no_reference["reference_status"] == "MISSING_PRE_SIGNAL_QUOTE"
    return Scenario(positive, negative, row == _episode(100.0), {"entry_latency_ms": row["entry_latency_ms"] if row else None})


def _scenario_multi_horizon() -> Scenario:
    signal = 10_000_000
    horizons = (100.0, 1000.0, 60_000.0)
    rows = episodes_par_horizon(
        _hl_quotes(signal, horizons),
        [(signal, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=horizons,
        coin="ETH",
    )
    positive = all(len(rows[horizon]) == 1 and rows[horizon][0]["horizon_ms"] == horizon for horizon in horizons)
    rejected = base.horizons_observables({"p50_ms": 600.0}, (100.0, 1000.0))
    negative = rejected == []
    again = episodes_par_horizon(
        _hl_quotes(signal, horizons),
        [(signal, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=horizons,
        coin="ETH",
    )
    return Scenario(positive, negative, rows == again, {"horizons": list(horizons)})


def _scenario_regimes() -> Scenario:
    stable = _metriques([1.0] * 8, n_periodes=4)
    unstable = _metriques([1.0, 1.0, -5.0, -5.0, 1.0, 1.0, 1.0, 1.0], n_periodes=4)
    return Scenario(stable["stable"] is True, unstable["stable"] is False, stable == _metriques([1.0] * 8, n_periodes=4), {"periods": stable["moyennes_par_periode_bps"]})


def _scenario_clock_second_minute() -> Scenario:
    signal = 999_900_000
    horizons = (1000.0, 60_000.0)
    rows = episodes_par_horizon(
        _hl_quotes(signal, horizons),
        [(signal, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=horizons,
        coin="ETH",
    )
    expected = {h: signal + int(h * 1_000_000.0) for h in horizons}
    positive = all(rows[h] and rows[h][0]["exit_ts_ns"] == expected[h] for h in horizons)
    incomplete_quotes = _hl_quotes(signal, (1000.0,))
    missing_minute = episodes_par_horizon(
        incomplete_quotes,
        [(signal, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=(60_000.0,),
        coin="ETH",
    )[60_000.0]
    return Scenario(positive, missing_minute == [], rows == episodes_par_horizon(_hl_quotes(signal, horizons), [(signal, 1.0)], frais_slippage_bps=9.0, horizons_ms=horizons, coin="ETH"), {"targets": expected})


def _scenario_clock_5m_15m() -> Scenario:
    signal = 2_000_000_000
    horizons = (300_000.0, 900_000.0)
    rows = episodes_par_horizon(
        _hl_quotes(signal, horizons),
        [(signal, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=horizons,
        coin="ETH",
    )
    positive = all(rows[h] and rows[h][0]["exit_ts_ns"] == signal + int(h * 1_000_000.0) for h in horizons)
    missing = episodes_par_horizon(
        _hl_quotes(signal, (300_000.0,)),
        [(signal, 1.0)],
        frais_slippage_bps=9.0,
        horizons_ms=(900_000.0,),
        coin="ETH",
    )[900_000.0]
    return Scenario(positive, missing == [], rows == episodes_par_horizon(_hl_quotes(signal, horizons), [(signal, 1.0)], frais_slippage_bps=9.0, horizons_ms=horizons, coin="ETH"), {"horizons": list(horizons)})


def _scenario_ofi_microprice() -> Scenario:
    prev = resume_book(_raw_book())
    cur = resume_book(_raw_book(bid_sizes=(12, 9, 7, 4, 2), ask_sizes=(4, 5, 6, 7, 8)))
    multi = ofi_multi_niveaux(prev, cur)
    price = microprice(cur)
    crossed = {
        "bid": 101.0,
        "ask": 100.0,
        "mid": 100.5,
        "bids5": [[101.0, 1.0, 1]],
        "asks5": [[100.0, 1.0, 1]],
    }
    positive = multi is not None and multi["ofi_l5"] is not None and price is not None
    negative = ofi_multi_niveaux(None, cur) is None and microprice(crossed) is None
    return Scenario(positive, negative, (multi, price) == (ofi_multi_niveaux(prev, cur), microprice(cur)), {"microprice": price})


def _scenario_queue_depletion() -> Scenario:
    prev = resume_book(_raw_book())
    cur = resume_book(_raw_book(bid_sizes=(5, 8, 6, 4, 2), ask_sizes=(2, 6, 7, 8, 9)))
    measured = queue_depletion(prev, cur)
    moved = resume_book(_raw_book(bid=100.1, ask=100.3))
    rejected = queue_depletion(prev, moved)
    return Scenario(measured["status"] == "MEASURED_SAME_PRICE_LEVEL", rejected["status"] == "PRICE_LEVEL_CHANGED", measured == queue_depletion(prev, cur), {"queue_pressure": measured["queue_pressure"]})


def _scenario_adds_cancels() -> Scenario:
    events = [
        {"action": "ADD", "side": "BID", "size": 5},
        {"action": "CANCEL", "side": "ASK", "size": 3},
        {"action": "ADD", "side": "ASK", "size": 1},
    ]
    measured = add_cancel_imbalance(events)
    empty = add_cancel_imbalance([])
    return Scenario(measured["status"] == "MEASURED_EVENTS" and measured["event_count"] == 3, empty["status"] == "ADD_CANCEL_UNMEASURABLE_FROM_SNAPSHOTS" and empty["value"] is None, measured == add_cancel_imbalance(events), {"value": measured["value"]})


def _scenario_depth() -> Scenario:
    book = resume_book(_raw_book())
    shape = depth_shape(book)
    depth = profondeur_top5(book)
    good = _episode(100.0, with_sizes=True)
    no_sizes = _episode(100.0, with_sizes=False)
    positive = depth is not None and depth > 0 and shape is not None and good is not None and good["top_capacity_usd"] is not None
    negative = no_sizes is not None and no_sizes["top_capacity_usd"] is None and no_sizes["liquidatable_net"] is False
    return Scenario(positive, negative, (depth, shape) == (profondeur_top5(book), depth_shape(book)), {"depth_top5": depth})


def _scenario_latency() -> Scenario:
    local = latence_pipeline_ms(100.0, 150.0)
    reversed_latency = latence_pipeline_ms(150.0, 100.0)
    row = _episode(100.0)
    positive = local == 50.0 and row is not None and row["entry_latency_ms"] >= 0 and row["latency_cost_usd"] >= 0
    negative = reversed_latency is None
    return Scenario(positive, negative, local == latence_pipeline_ms(100.0, 150.0), {"pipeline_ms": local})


def _scenario_universe() -> Scenario:
    tape = {"ETH": {}, "BTC": {}, "DOGE": {}}
    partition = partition_universe(tape, ("DOGE", "XRP"))
    only_control = partition_universe({"DOGE": {}}, ("DOGE",))
    positive = partition["test"] == ["BTC", "ETH"] and partition["control"] == ["DOGE"] and partition["ignored_controls_missing_from_tape"] == ["XRP"]
    negative = only_control["test"] == [] and only_control["control"] == ["DOGE"]
    return Scenario(positive, negative, partition == partition_universe(tape, ("DOGE", "XRP")), partition)


def _scenario_cost_stress() -> Scenario:
    low = _episode(100.0, fees_bps=0.0)
    normal = _episode(100.0, fees_bps=9.0)
    stressed = _episode(100.0, fees_bps=500.0)
    positive = bool(low and normal and stressed and low["net_pnl_usd"] > normal["net_pnl_usd"] > stressed["net_pnl_usd"])
    negative = bool(stressed and stressed["net_pnl_usd"] < 0)
    return Scenario(positive, negative, (low, normal, stressed) == (_episode(100.0, fees_bps=0.0), _episode(100.0, fees_bps=9.0), _episode(100.0, fees_bps=500.0)), {"stressed_net": stressed["net_pnl_usd"] if stressed else None})


def _campaign_tape(count: int = 10) -> dict[str, dict[str, list]]:
    hl = []
    trades = []
    price = 100.0
    for index in range(count):
        base_ns = index * 1_000_000_000
        high = price * 1.005
        follow = price * 1.004
        trades.extend([
            (base_ns, price, 1.0),
            (base_ns + 10_000_000, high, 1.0),
        ])
        hl.extend([
            (base_ns + 5_000_000, price, price * 0.9999, price * 1.0001, 20.0, 20.0),
            (base_ns + 20_000_000, price, price * 0.9999, price * 1.0001, 20.0, 20.0),
            (base_ns + 110_000_000, follow, follow * 0.9999, follow * 1.0001, 20.0, 20.0),
        ])
        price = high
    return {"ETH": {"HL": sorted(hl), "BIN": [], "TRADE": sorted(trades)}}


def _scenario_placebos() -> Scenario:
    tape = _campaign_tape()
    first = executable_campaign_evidence(
        tape,
        frozen_at_ms=6_500,
        horizon_ms=100.0,
        frais_slippage_bps=9.0,
        seuil_choc_bps=8.0,
        notional_usd=25.0,
    )
    second = executable_campaign_evidence(
        tape,
        frozen_at_ms=6_500,
        horizon_ms=100.0,
        frais_slippage_bps=9.0,
        seuil_choc_bps=8.0,
        notional_usd=25.0,
    )
    empty = executable_campaign_evidence(
        {},
        frozen_at_ms=1,
        horizon_ms=100.0,
        frais_slippage_bps=9.0,
        seuil_choc_bps=8.0,
        notional_usd=25.0,
    )
    placebo = first["temporal_evidence"]["placebos"]
    direction_repeatable = _placebo_direction("ETH", 123) == _placebo_direction("ETH", 123)
    positive = direction_repeatable and "candidate_oos_net_usd" in placebo and "placebo_oos_net_usd" in placebo
    negative = empty["temporal_evidence"]["placebos"]["beaten"] is False
    return Scenario(positive, negative, first == second, {"placebo": placebo})


_SCENARIOS: dict[str, Callable[[], Scenario]] = {
    "certified_timestamps": _scenario_certified_timestamps,
    "causality_real_lag": _scenario_causality_real_lag,
    "multi_horizon": _scenario_multi_horizon,
    "regimes": _scenario_regimes,
    "clock_second_minute": _scenario_clock_second_minute,
    "clock_5m_15m": _scenario_clock_5m_15m,
    "ofi_microprice": _scenario_ofi_microprice,
    "queue_depletion": _scenario_queue_depletion,
    "adds_cancels": _scenario_adds_cancels,
    "depth": _scenario_depth,
    "latency": _scenario_latency,
    "universe": _scenario_universe,
    "cost_stress": _scenario_cost_stress,
    "placebos": _scenario_placebos,
}


def evaluate_lead_lag_requirements(root: Path) -> dict[str, Any]:
    root = root.resolve()
    requirements = []
    for key, description in LEAD_LAG_REQUIREMENTS:
        scenario = _SCENARIOS[key]()
        evidence = list(_EVIDENCE[key])
        hashes = {
            path: _hash(root / path)
            for path in evidence
            if (root / path).is_file()
        }
        facets = {
            "CONTRACT": callable(_SCENARIOS[key]),
            "POSITIVE_PATH": scenario.positive,
            "NEGATIVE_FAIL_CLOSED": scenario.negative,
            "DETERMINISM_CAUSALITY": scenario.deterministic,
            "EVIDENCE_PROVENANCE": len(hashes) == len(evidence),
        }
        requirements.append(
            {
                "key": key,
                "description": description,
                "ok": all(facets.values()),
                "facets": facets,
                "evidence": evidence,
                "evidence_sha256": hashes,
                "detail": scenario.detail,
            }
        )
    return {
        "category": "LEAD_LAG",
        "requirements_total": len(LEAD_LAG_REQUIREMENTS),
        "requirements_done": sum(1 for row in requirements if row["ok"]),
        "facets_total": len(LEAD_LAG_REQUIREMENTS) * len(FACETS),
        "facets_done": sum(
            1
            for row in requirements
            for value in row["facets"].values()
            if value
        ),
        "ok": all(row["ok"] for row in requirements),
        "requirements": requirements,
    }


__all__ = [
    "FACETS",
    "LEAD_LAG_REQUIREMENTS",
    "evaluate_lead_lag_requirements",
]
