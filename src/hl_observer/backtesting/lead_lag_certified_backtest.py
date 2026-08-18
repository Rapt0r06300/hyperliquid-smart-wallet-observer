"""Strict, restart-safe Lead-Lag loader and backtest.

Only cross-process wall clocks can certify chronology. ``recu_ns`` remains useful
inside one process for diagnostics, but it is never accepted by this module as
economic ordering evidence.
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting import lead_lag_shadow as base
from hl_observer.backtesting.anti_overfit_gate import evaluer as evaluer_dsr
from hl_observer.backtesting.anti_overfit_gate import sharpe
from hl_observer.backtesting.lead_lag_shadow_economics import (
    _metriques,
    episodes_par_horizon,
    executable_campaign_evidence,
)
from hl_observer.backtesting.robustesse_selection import pbo_cscv

CERTIFIED_TIMESTAMP_POLICY = "ts_wall_ms_or_recv_wall_ts_ms_required"


def certified_event_time_ns(row: Mapping[str, Any]) -> int | None:
    """Return a restart-durable wall timestamp, never a monotonic fallback."""

    wall_ms = row.get("ts_wall_ms", row.get("recv_wall_ts_ms"))
    if wall_ms is None:
        return None
    try:
        value = int(float(wall_ms) * 1_000_000.0)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value > 0 else None


def _flt(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive(value: Any) -> float | None:
    parsed = _flt(value)
    return parsed if parsed is not None and parsed > 0 else None


def _dedupe_key(row: Mapping[str, Any], timestamp_ns: int) -> tuple[Any, ...]:
    event_id = row.get("event_id")
    if event_id:
        return ("event_id", str(event_id))
    venue = str(row.get("venue") or "")
    coin = str(row.get("coin") or "").upper()
    if venue == "BIN_TRADE":
        return (
            venue,
            coin,
            int(timestamp_ns),
            row.get("px"),
            row.get("side"),
            row.get("sz"),
        )
    return (
        venue,
        coin,
        int(timestamp_ns),
        row.get("bid"),
        row.get("ask"),
        row.get("mid"),
        row.get("bid_sz", row.get("bid_size")),
        row.get("ask_sz", row.get("ask_size")),
    )


def load_certified_tape(
    root: str | Path,
    *,
    include_history: bool = False,
    max_history_sources: int = base.DEFAULT_HISTORY_SOURCES,
    sources: list[Path] | None = None,
    return_meta: bool = False,
) -> dict[str, dict[str, list]] | tuple[dict[str, dict[str, list]], dict[str, Any]]:
    """Load only rows whose chronology survives process restarts.

    Monotonic-only rows are preserved in the source files but explicitly
    rejected from this certified view.
    """

    root_path = Path(root).resolve()
    selected = list(sources) if sources is not None else base.selectionner_sources(
        root_path,
        include_history=include_history,
        max_history_sources=max_history_sources,
    )
    per_coin: dict[str, dict[str, list]] = defaultdict(
        lambda: {"HL": [], "BIN": [], "TRADE": []}
    )
    seen: set[tuple[Any, ...]] = set()
    lines_read = 0
    duplicates = 0
    invalid_rows = 0
    uncertifiable_clock_rows = 0
    unsupported_rows = 0
    consumed: list[str] = []

    for path_value in selected:
        path = Path(path_value)
        if not path.is_absolute():
            path = root_path / path
        if not path.is_file():
            continue
        try:
            consumed.append(path.relative_to(root_path).as_posix())
        except ValueError:
            consumed.append(str(path))
        for line in base._iter_lines(path):
            lines_read += 1
            try:
                row = json.loads(line)
                coin = str(row["coin"]).upper()
            except (KeyError, TypeError, ValueError):
                invalid_rows += 1
                continue
            venue = str(row.get("venue") or "")
            if venue not in {"HL", "BIN_TRADE"}:
                unsupported_rows += 1
                continue
            timestamp_ns = certified_event_time_ns(row)
            if timestamp_ns is None:
                uncertifiable_clock_rows += 1
                continue
            key = _dedupe_key(row, timestamp_ns)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            if venue == "HL":
                mid = _flt(row.get("mid"))
                if mid is None or mid <= 0:
                    invalid_rows += 1
                    continue
                bid = _flt(row.get("bid"))
                ask = _flt(row.get("ask"))
                per_coin[coin]["HL"].append(
                    (
                        timestamp_ns,
                        mid,
                        bid if bid is not None and bid > 0 else mid,
                        ask if ask is not None and ask > 0 else mid,
                        _positive(row.get("bid_sz", row.get("bid_size"))),
                        _positive(row.get("ask_sz", row.get("ask_size"))),
                    )
                )
            else:
                price = _flt(row.get("px"))
                if price is None or price <= 0:
                    invalid_rows += 1
                    continue
                side = str(row.get("side") or "").upper()
                if side not in {"BUY", "SELL"}:
                    invalid_rows += 1
                    continue
                per_coin[coin]["TRADE"].append(
                    (timestamp_ns, price, 1.0 if side == "BUY" else -1.0)
                )

    for coin in per_coin:
        for kind in per_coin[coin]:
            per_coin[coin][kind].sort()

    result = dict(per_coin)
    meta = {
        "timestamp_clock": CERTIFIED_TIMESTAMP_POLICY,
        "wall_clock_required": True,
        "monotonic_only_rows_eligible_for_economic_proof": False,
        "archive_rows_preserved": True,
        "sources": consumed,
        "sources_count": len(consumed),
        "lines_read": lines_read,
        "relevant_unique_events": len(seen),
        "duplicates_rejected": duplicates,
        "invalid_rows": invalid_rows,
        "uncertifiable_clock_rows": uncertifiable_clock_rows,
        "unsupported_rows": unsupported_rows,
        "complete_sources": True,
    }
    return (result, meta) if return_meta else result


def partition_universe(
    tape: Mapping[str, Mapping[str, list]],
    control_coins: tuple[str, ...] | list[str] = (),
) -> dict[str, list[str]]:
    controls = {str(coin).upper() for coin in control_coins if coin}
    available = {str(coin).upper() for coin in tape}
    return {
        "test": sorted(available - controls),
        "control": sorted(available & controls),
        "ignored_controls_missing_from_tape": sorted(controls - available),
    }


def _certification(meta: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "policy": CERTIFIED_TIMESTAMP_POLICY,
        "wall_clock_required": True,
        "monotonic_only_rows_eligible_for_economic_proof": False,
        "monotonic_only_rows_rejected": int(meta.get("uncertifiable_clock_rows") or 0),
        "archive_rows_preserved": True,
    }


def backtest_certified(
    root: str | Path = ".",
    *,
    seuil_choc_bps: float = base.SEUIL_CHOC_BPS,
    frais_slippage_bps: float = base.FRAIS_SLIPPAGE_BPS,
    horizons_ms=base.HORIZONS_MS,
    coins_controle: tuple = (),
    min_chocs: int = base.MIN_CHOCS,
    include_history: bool = False,
    max_history_sources: int = base.DEFAULT_HISTORY_SOURCES,
    sources: list[Path] | None = None,
    economic_frozen_at_ms: int | None = None,
    economic_horizon_ms: float = base.CAMPAIGN_HORIZON_MS,
    economic_notional_usd: float = base.CAMPAIGN_NOTIONAL_USD,
) -> dict[str, Any]:
    """Backtest Lead-Lag from a strictly certified tape.

    Economic metrics use only closed episodes with measured executable top
    capacity and fresh pre-signal/exit observations.
    """

    requested_horizons = tuple(float(value) for value in horizons_ms)
    tape, source_meta = load_certified_tape(
        root,
        include_history=include_history,
        max_history_sources=max_history_sources,
        sources=sources,
        return_meta=True,
    )
    certification = _certification(source_meta)
    if not tape:
        return {
            "strategie": "lead_lag_shadow",
            "statut": "NEED_MORE_DATA",
            "detail": "tape certifiee vide",
            "source_meta": source_meta,
            "timestamp_certification": certification,
        }

    p50s = [
        distribution["p50_ms"]
        for events in tape.values()
        if len(events["HL"]) >= 5
        and (distribution := base.distribution_intervalles(events["HL"]))["p50_ms"]
    ]
    med_p50 = st.median(p50s) if p50s else None
    interval_meta = {
        "p50_ms_par_coin_median": round(med_p50, 2) if med_p50 else None,
        "n_coins_mesures": len(p50s),
    }
    horizons = [
        float(horizon)
        for horizon in requested_horizons
        if med_p50 and float(horizon) >= 2.0 * med_p50
    ]
    if not horizons:
        return {
            "strategie": "lead_lag_shadow",
            "statut": "NEED_MORE_DATA",
            "intervalles_hl": interval_meta,
            "detail": "aucun horizon observable (HL trop lent / peu de data)",
            "source_meta": source_meta,
            "timestamp_certification": certification,
        }

    universe = partition_universe(tape, coins_controle)
    controls = set(universe["control"])
    test: dict[float, list[float]] = {h: [] for h in horizons}
    ctrl: dict[float, list[float]] = {h: [] for h in horizons}
    placebo: dict[float, list[float]] = {h: [] for h in horizons}
    capacities: list[float] = []
    test_event_times: list[int] = []
    non_liquidatable = 0

    for coin, events in sorted(tape.items()):
        shocks = base.detecter_chocs(
            list(events.get("TRADE") or []),
            seuil_bps=float(seuil_choc_bps),
        )
        hl = list(events.get("HL") or [])
        if not shocks or len(hl) < 3:
            continue
        episodes = episodes_par_horizon(
            hl,
            shocks,
            frais_slippage_bps=float(frais_slippage_bps),
            horizons_ms=horizons,
            coin=coin,
            notional_usd=float(economic_notional_usd),
        )
        target = ctrl if coin in controls else test
        for horizon in horizons:
            rows = episodes[horizon]
            eligible = [row for row in rows if row.get("liquidatable_net") is True]
            non_liquidatable += len(rows) - len(eligible)
            target[horizon].extend(float(row["net_bps"]) for row in eligible)
            if coin not in controls:
                capacities.extend(
                    float(row["top_capacity_usd"])
                    for row in eligible
                    if row.get("top_capacity_usd") is not None
                )

        if coin not in controls:
            test_event_times.extend(int(t0) for t0, _direction in shocks)
            rng = random.Random(20260723)
            fake_shocks = [
                (int(t0), 1.0 if rng.random() > 0.5 else -1.0)
                for t0, _direction in shocks
            ]
            placebo_episodes = episodes_par_horizon(
                hl,
                fake_shocks,
                frais_slippage_bps=float(frais_slippage_bps),
                horizons_ms=horizons,
                coin=coin,
                notional_usd=float(economic_notional_usd),
            )
            for horizon in horizons:
                placebo[horizon].extend(
                    float(row["net_bps"])
                    for row in placebo_episodes[horizon]
                    if row.get("liquidatable_net") is True
                )

    n_test = max((len(values) for values in test.values()), default=0)
    if n_test < int(min_chocs):
        return {
            "strategie": "lead_lag_shadow",
            "statut": "NEED_MORE_DATA",
            "chocs_test": n_test,
            "cible": int(min_chocs),
            "intervalles_hl": interval_meta,
            "horizons_observables": horizons,
            "source_meta": source_meta,
            "timestamp_certification": certification,
            "universe": universe,
            "non_liquidatable_observations_rejected": non_liquidatable,
        }

    per_horizon = {
        horizon: _metriques(values, n_periodes=base.N_PERIODES)
        for horizon, values in test.items()
        if values
    }
    controls_per_horizon = {
        horizon: round(st.mean(values), 3)
        for horizon, values in ctrl.items()
        if values
    }
    placebo_per_horizon = {
        horizon: round(st.mean(values), 3)
        for horizon, values in placebo.items()
        if values
    }
    trial_sharpes = [sharpe(values) for values in test.values() if len(values) >= 2]
    dsr_per_horizon = {
        horizon: evaluer_dsr(
            values,
            n_essais=max(1, len(requested_horizons)),
            trial_sharpes=trial_sharpes,
        ).as_dict()
        for horizon, values in test.items()
        if values
    }
    pbo_rows = [
        metrics["moyennes_par_periode_bps"]
        for metrics in per_horizon.values()
        if len(metrics.get("moyennes_par_periode_bps") or ()) >= 4
    ]
    pbo = pbo_cscv(pbo_rows) if len(pbo_rows) >= 2 else pbo_cscv([])

    event_frequency = None
    if len(test_event_times) >= 2:
        duration_days = (
            (max(test_event_times) - min(test_event_times)) / 1e9 / 86400.0
        )
        if duration_days > 0:
            event_frequency = round(len(test_event_times) / duration_days, 6)

    winners = {
        horizon: row
        for horizon, row in per_horizon.items()
        if row["esperance_nette_bps"] > 0
        and row["stable"]
        and row["esperance_nette_bps"] > placebo_per_horizon.get(horizon, 0.0)
    }
    result: dict[str, Any] = {
        "strategie": "lead_lag_shadow",
        "statut": "PROMETTEUR" if winners else "PAS_D_EDGE",
        "chocs_test": n_test,
        "intervalles_hl": interval_meta,
        "horizons_observables": horizons,
        "capacite_mediane_usd": (
            round(st.median(capacities), 2) if capacities else None
        ),
        "capacity_status": (
            "MEASURED_TOP_OF_BOOK"
            if capacities
            else "UNMEASURABLE_NO_EXECUTABLE_TOP_CAPACITY"
        ),
        "net_par_horizon": per_horizon,
        "controle_par_horizon": controls_per_horizon,
        "placebo_par_horizon": placebo_per_horizon,
        "dsr_par_horizon": dsr_per_horizon,
        "pbo": pbo,
        "frequence_evenements_par_jour": event_frequency,
        "information_coefficient": {
            "value": None,
            "status": "UNMEASURABLE_WITH_DIRECTION_ONLY_SHOCKS",
        },
        "regimes": {
            "period_count": base.N_PERIODES,
            "stable_horizons_ms": [
                horizon
                for horizon, row in per_horizon.items()
                if row.get("stable")
            ],
        },
        "source_meta": source_meta,
        "timestamp_certification": certification,
        "universe": universe,
        "non_liquidatable_observations_rejected": non_liquidatable,
        "avertissement": (
            "Certified wall clock only; monotonic-only rows rejected; "
            "economic metrics require measured executable top capacity."
        ),
    }
    if economic_frozen_at_ms is not None:
        result["executable_campaign"] = executable_campaign_evidence(
            tape,
            frozen_at_ms=int(economic_frozen_at_ms),
            horizon_ms=float(economic_horizon_ms),
            frais_slippage_bps=float(frais_slippage_bps),
            seuil_choc_bps=float(seuil_choc_bps),
            notional_usd=float(economic_notional_usd),
        )
    return result


__all__ = [
    "CERTIFIED_TIMESTAMP_POLICY",
    "backtest_certified",
    "certified_event_time_ns",
    "load_certified_tape",
    "partition_universe",
]
