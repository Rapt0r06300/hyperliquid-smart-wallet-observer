"""LEAD-LAG SHADOW — Binance mène, HL suit ? Mesure NETTE, méthodo gelée (23/07, chantier ARB).

Corrections méthodo de Flo, AVANT la collecte :
  1. HL n'émet le BBO que quand il change sur un bloc -> on MESURE d'abord la distribution réelle des
     intervalles entre messages (`distribution_intervalles`) et on ne GARDE un horizon que si la
     donnée permet de l'observer (`horizons_observables` : un horizon < ~2× l'intervalle médian HL
     est illusoire, on le jette).
  2. Le CHOC se détecte sur les TRADES Binance (aggTrade), pas sur le mid BBO ; l'ENTRÉE se simule au
     bid/ask HL réellement dispo (demi-spread réel), avec la profondeur au top ; horloge MONOTONE.
  3. Coins, horizons, seuils, critère de réussite GELÉS avant le live-forward (`geler_config`) — on ne
     les réajuste pas après avoir vu le PnL.
  4. On mesure l'espérance nette, la CAPACITÉ, le DRAWDOWN et la STABILITÉ PAR PÉRIODE — pas le winrate.

Coins de CONTRÔLE gardés : si le contrôle gagne autant, c'est un artefact d'horloge, pas un edge.
PAPER/shadow only : mesurer n'est pas trader.
"""
from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import math
import statistics as st
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.backtesting.anti_overfit_gate import evaluer as evaluer_dsr
from hl_observer.backtesting.anti_overfit_gate import sharpe
from hl_observer.backtesting.lead_lag_evidence import (
    REQUIRED_CRITERIA,
    SCHEMA_VERSION,
    SUPPORTED_HORIZONS_MS,
    estimate_alpha_half_life_ms,
)
from hl_observer.backtesting.quant_methods import block_bootstrap
from hl_observer.backtesting.robustesse_selection import pbo_cscv
from hl_observer.config.frais_venues import frais_taker_bps

TAPE = Path("runtime") / "data" / "bbo_tape.jsonl"
CONFIG_GELE = Path("runtime") / "data" / "lead_lag_config_gele.json"
GLOBAL_TRIAL_LEDGER = Path("runtime") / "research_lab" / "ledgers" / "global_trials.jsonl"
SEUIL_CHOC_BPS = 8.0
FRAIS_SLIPPAGE_BPS = 2.0 * frais_taker_bps("HYPERLIQUID")
HORIZONS_MS = (50.0, 100.0, 250.0, 500.0, 1000.0)
MIN_CHOCS = 30
N_PERIODES = 4                     # pour juger la stabilité dans le temps
DEFAULT_HISTORY_SOURCES = 8
CAMPAIGN_HORIZON_MS = 1000.0
CAMPAIGN_NOTIONAL_USD = 25.0
CAMPAIGN_MAX_REFERENCE_LAG_MS = 30_000.0
CAMPAIGN_MAX_EXIT_LAG_MS = 30_000.0
CAMPAIGN_EXECUTION_MODEL = "causal_marketable_top_v4_horizon_bounded_freshness"


def walk_forward_protocol_signature() -> dict[str, Any]:
    """Return immutable strategy fields, excluding append-only dataset shape."""

    return {
        "seuil_choc_bps": SEUIL_CHOC_BPS,
        "frais_slippage_bps": FRAIS_SLIPPAGE_BPS,
        "horizons_ms": list(HORIZONS_MS),
        "economic_horizon_ms": CAMPAIGN_HORIZON_MS,
        "economic_notional_usd": CAMPAIGN_NOTIONAL_USD,
        "max_reference_lag_ms": CAMPAIGN_MAX_REFERENCE_LAG_MS,
        "max_exit_lag_ms": CAMPAIGN_MAX_EXIT_LAG_MS,
        "freshness_cap_policy": "min(configured_lag_ms,economic_horizon_ms)",
        "freeze_readiness_policy": "static_params;structural_segments_only;no_pnl_selection",
        "execution_model": CAMPAIGN_EXECUTION_MODEL,
        "minimum_shocks": MIN_CHOCS,
        "timestamp_clock": "ts_wall_ms_or_recv_wall_ts_ms;recu_ns_fallback",
    }


def selectionner_sources(
    root: str | Path,
    *,
    include_history: bool = False,
    max_history_sources: int = DEFAULT_HISTORY_SOURCES,
) -> list[Path]:
    """Return a deterministic set of local tapes used by the replay.

    The live tape is always first.  Historical gzip shards are selected by
    their stable filename timestamp, newest first.  ``bbo_tape.jsonl.prev``
    is used only after shards because older versions generally did not record
    Binance trades, which are mandatory for this strategy.
    """

    data = Path(root) / "runtime" / "data"
    selected = [data / "bbo_tape.jsonl"]
    if not include_history:
        return [path for path in selected if path.is_file()]
    historical = sorted(
        [
            *list((data / "bbo_shards").glob("*.jsonl.gz")),
            *list((data / "bbo_shards_archive").glob("*.jsonl.gz")),
        ],
        key=lambda path: path.name,
        reverse=True,
    )
    limit = max(0, int(max_history_sources))
    selected.extend(historical[:limit])
    previous = data / "bbo_tape.jsonl.prev"
    if previous.is_file() and len(historical) < limit:
        selected.append(previous)
    return [path for path in selected if path.is_file()]


def _iter_lines(path: Path):
    opener = gzip.open if path.name.endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8", errors="ignore") as handle:
            yield from handle
    except OSError:
        return


def _event_time_ns(row: dict[str, Any]) -> int | None:
    """Use a cross-process wall clock; monotonic ``recu_ns`` is only fallback."""

    wall_ms = row.get("ts_wall_ms", row.get("recv_wall_ts_ms"))
    try:
        if wall_ms is not None:
            return int(float(wall_ms) * 1_000_000.0)
        return int(row["recu_ns"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _dedupe_key(row: dict[str, Any], timestamp_ns: int) -> tuple[Any, ...]:
    event_id = row.get("event_id")
    if event_id:
        return ("event_id", str(event_id))
    venue = str(row.get("venue") or "")
    coin = str(row.get("coin") or "").upper()
    if venue == "BIN_TRADE":
        return (venue, coin, timestamp_ns, row.get("px"), row.get("side"), row.get("sz"))
    return (
        venue,
        coin,
        timestamp_ns,
        row.get("bid"),
        row.get("ask"),
        row.get("mid"),
        row.get("bid_sz", row.get("bid_size")),
        row.get("ask_sz", row.get("ask_size")),
    )


def charger_tape(
    root: str | Path,
    *,
    include_history: bool = False,
    max_history_sources: int = DEFAULT_HISTORY_SOURCES,
    sources: list[Path] | None = None,
    return_meta: bool = False,
) -> dict[str, dict[str, list]] | tuple[dict[str, dict[str, list]], dict[str, Any]]:
    """Load causal HL quotes and Binance trades from exact local sources.

    Modern tapes are compared with wall timestamps because ``recu_ns`` is a
    process-local monotonic clock and cannot be ordered across restarts.
    """

    from collections import defaultdict
    root_path = Path(root).resolve()
    selected = list(sources) if sources is not None else selectionner_sources(
        root_path,
        include_history=include_history,
        max_history_sources=max_history_sources,
    )
    par: dict[str, dict[str, list]] = defaultdict(lambda: {"HL": [], "BIN": [], "TRADE": []})
    seen: set[tuple[Any, ...]] = set()
    lines_read = duplicates = invalid = 0
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
        for line in _iter_lines(path):
            lines_read += 1
            try:
                d = json.loads(line)
                coin = str(d["coin"]).upper()
            except (KeyError, TypeError, ValueError):
                invalid += 1
                continue
            venue = d.get("venue")
            if venue not in {"HL", "BIN_TRADE"}:
                continue
            timestamp_ns = _event_time_ns(d)
            if timestamp_ns is None:
                invalid += 1
                continue
            key = _dedupe_key(d, timestamp_ns)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            if venue == "HL":
                mid = _flt(d.get("mid"))
                if mid:
                    par[coin]["HL"].append(
                        (
                            timestamp_ns,
                            mid,
                            _flt(d.get("bid")) or mid,
                            _flt(d.get("ask")) or mid,
                            _positive_or_none(d.get("bid_sz", d.get("bid_size"))),
                            _positive_or_none(d.get("ask_sz", d.get("ask_size"))),
                        )
                    )
            else:
                price = _flt(d.get("px"))
                if price:
                    par[coin]["TRADE"].append(
                        (timestamp_ns, price, 1.0 if d.get("side") == "BUY" else -1.0)
                    )
    for c in par:
        for k in par[c]:
            par[c][k].sort()
    result = dict(par)
    meta = {
        "timestamp_clock": "ts_wall_ms_or_recv_wall_ts_ms;recu_ns_fallback",
        "sources": consumed,
        "sources_count": len(consumed),
        "lines_read": lines_read,
        "relevant_unique_events": len(seen),
        "duplicates_rejected": duplicates,
        "invalid_rows": invalid,
        "complete_sources": True,
    }
    return (result, meta) if return_meta else result


def _flt(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _positive_or_none(value: Any) -> float | None:
    parsed = _flt(value)
    return parsed if parsed is not None and parsed > 0 else None


def distribution_intervalles(evenements: list) -> dict[str, float]:
    """Percentiles (ms) des intervalles entre messages — DIT si un horizon est observable."""
    ns = [e[0] for e in evenements]
    if len(ns) < 5:
        return {"n": len(ns), "p50_ms": None, "p90_ms": None}
    d = sorted((ns[i] - ns[i - 1]) / 1e6 for i in range(1, len(ns)))
    return {"n": len(ns), "p50_ms": round(d[len(d) // 2], 2),
            "p90_ms": round(d[int(len(d) * 0.9)], 2), "p99_ms": round(d[int(len(d) * 0.99)], 2)}


def horizons_observables(dist_hl: dict, horizons) -> list[float]:
    """On ne garde un horizon que s'il est >= 2× l'intervalle médian HL : sinon la 'réaction' à cet
    horizon n'est PAS observable (HL n'a pas encore réémis). C'est le garde-fou n°1 de Flo."""
    p50 = dist_hl.get("p50_ms")
    if not p50:
        return []
    return [h for h in horizons if h >= 2.0 * p50]


FENETRE_GROUPE_MS = 100.0          # deux chocs à moins de ça = le MÊME mouvement -> groupés (1 seul)


def detecter_chocs(trades: list, *, seuil_bps: float,
                   fenetre_groupe_ms: float = FENETRE_GROUPE_MS) -> list[tuple[int, float]]:
    """Chocs exécutables depuis les TRADES Binance : un saut de prix >= seuil entre trades consécutifs.
    Les chocs qui SE CHEVAUCHENT (< fenetre_groupe_ms) sont GROUPÉS en un seul (sinon on compte 5 fois
    le même mouvement et on gonfle l'échantillon). Retour [(recu_ns, direction)]."""
    out = []
    dernier_ns = -1e30
    for i in range(1, len(trades)):
        if trades[i - 1][1] <= 0:
            continue
        mv = (trades[i][1] - trades[i - 1][1]) / trades[i - 1][1] * 1e4
        if abs(mv) < seuil_bps:
            continue
        t = trades[i][0]
        if (t - dernier_ns) / 1e6 < fenetre_groupe_ms:        # chevauche le choc précédent -> groupé
            continue
        out.append((t, 1.0 if mv > 0 else -1.0))
        dernier_ns = t
    return out


def _hl_a(hl: list, t_ns: int) -> tuple | None:
    """Last quote at-or-before ``t_ns`` (diagnostics only)."""

    i = bisect.bisect_right([e[0] for e in hl], t_ns) - 1
    return hl[i] if i >= 0 else None


def _hl_apres(hl: list, t_ns: int, *, timestamps: list[int] | None = None) -> tuple | None:
    """Return the first quote observable at-or-after ``t_ns``."""

    times = timestamps if timestamps is not None else [event[0] for event in hl]
    index = bisect.bisect_left(times, t_ns)
    return hl[index] if index < len(hl) else None


def _top_capacity_usd(quote: tuple, *, side: str) -> float | None:
    if len(quote) < 6:
        return None
    if side == "BUY":
        price, size = _flt(quote[3]), _positive_or_none(quote[5])
    else:
        price, size = _flt(quote[2]), _positive_or_none(quote[4])
    if price is None or size is None:
        return None
    return price * size


from hl_observer.backtesting.lead_lag_shadow_economics import (
    _metriques,
    _placebo_direction,
    _temporal_bounds,
    backtest,
    calibrate_freeze_readiness,
    episodes_par_horizon,
    executable_campaign_evidence,
    net_par_horizon,
    summarize_executable_episodes,
)



def _legacy_geler_config(root: str | Path = ".", *, coins: list[str], coins_controle: list[str],
                         horizons_ms=HORIZONS_MS, seuil_choc_bps: float = SEUIL_CHOC_BPS,
                         frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS) -> dict[str, Any]:
    """GÈLE coins/horizons/seuils/critère AVANT le live-forward. On lira CE fichier, jamais des seuils
    réajustés après avoir vu le PnL (anti-cherry-picking)."""
    import time
    cfg = {"gele_ts": time.time(), "coins": [c.upper() for c in coins],
           "coins_controle": [c.upper() for c in coins_controle], "horizons_ms": list(horizons_ms),
           "seuil_choc_bps": seuil_choc_bps, "frais_slippage_bps": frais_slippage_bps,
           "critere_reussite": "esperance_nette_bps > 0 ET stable sur toutes les périodes ET contrôle <= 0",
           "min_chocs": MIN_CHOCS}
    p = Path(root) / CONFIG_GELE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, p)
    return cfg


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    if path.exists():
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    else:
        digest.update(b"<missing>")
    return f"sha256:{digest.hexdigest()}"


def _horizon_value(mapping: Any, horizon: float, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    for key in (horizon, str(horizon), str(int(horizon))):
        if key in mapping:
            return mapping[key]
    return default


def _register_clock_boundary_trials(
    root: Path,
    *,
    dataset_hash: str,
    pipeline_hash: str,
    requested_horizons: list[float],
) -> dict[str, Any]:
    """Register every tested clock boundary once in the global research ledger."""

    ledger = root / GLOBAL_TRIAL_LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    known_ids: set[str] = set()
    valid_rows = 0
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(row, dict):
                valid_rows += 1
                if row.get("trial_id"):
                    known_ids.add(str(row["trial_id"]))

    added = 0
    now = datetime.now(timezone.utc).isoformat()
    with ledger.open("a", encoding="utf-8") as handle:
        for horizon in requested_horizons:
            identity = "|".join(
                (dataset_hash, pipeline_hash, "lead_lag_shadow", f"{horizon:g}ms")
            )
            trial_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            if trial_id in known_ids:
                continue
            row = {
                "trial_id": trial_id,
                "strategy": "lead_lag_shadow",
                "dimension": "clock_boundary_ms",
                "value": horizon,
                "dataset_hash": dataset_hash,
                "pipeline_hash": pipeline_hash,
                "registered_at": now,
                "real_execution": False,
            }
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            known_ids.add(trial_id)
            added += 1
    return {
        "count": valid_rows + added,
        "added": added,
        "ledger": str(ledger),
    }


def geler_config(
    root: str | Path = ".",
    *,
    coins: list[str],
    coins_controle: list[str],
    horizons_ms=HORIZONS_MS,
    seuil_choc_bps: float = SEUIL_CHOC_BPS,
    frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS,
    minimum_events: int = MIN_CHOCS,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze a complete, versioned and deny-by-default lead-lag evidence artefact."""

    root_path = Path(root)
    requested = [float(value) for value in horizons_ms]
    unsupported = [value for value in requested if value not in SUPPORTED_HORIZONS_MS]
    if unsupported:
        raise ValueError(f"unsupported lead-lag horizons: {unsupported}")

    dataset_path = root_path / TAPE
    pipeline_path = Path(__file__)
    dataset_hash = _sha256_file(dataset_path)
    pipeline_hash = _sha256_file(pipeline_path)
    global_trials = _register_clock_boundary_trials(
        root_path,
        dataset_hash=dataset_hash,
        pipeline_hash=pipeline_hash,
        requested_horizons=requested,
    )
    result = evidence or backtest(
        root_path,
        seuil_choc_bps=seuil_choc_bps,
        frais_slippage_bps=frais_slippage_bps,
        horizons_ms=requested,
        coins_controle=tuple(coins_controle),
        min_chocs=minimum_events,
    )
    observable = [
        float(value)
        for value in result.get("horizons_observables", ())
        if float(value) in requested
    ]
    net_rows = result.get("net_par_horizon") or {}
    controls = result.get("controle_par_horizon") or {}
    placebos = result.get("placebo_par_horizon") or {}
    dsr_rows = result.get("dsr_par_horizon") or {}

    edges: dict[str, float] = {}
    samples: dict[str, int] = {}
    stability: dict[str, bool] = {}
    bootstrap: dict[str, list[float | None]] = {}
    placebo_edges: dict[str, float | None] = {}
    control_edges: dict[str, float | None] = {}
    dsr: dict[str, dict[str, Any]] = {}
    for horizon in observable:
        key = str(int(horizon) if horizon.is_integer() else horizon)
        row = _horizon_value(net_rows, horizon, {}) or {}
        edges[key] = float(row.get("esperance_nette_bps") or 0.0)
        samples[key] = int(row.get("n") or 0)
        stability[key] = row.get("stable") is True
        bootstrap[key] = list(row.get("bootstrap_mean_ci95_bps") or [None, None])
        placebo = _horizon_value(placebos, horizon)
        control = _horizon_value(controls, horizon)
        placebo_edges[key] = float(placebo) if placebo is not None else None
        control_edges[key] = float(control) if control is not None else None
        dsr[key] = dict(_horizon_value(dsr_rows, horizon, {}) or {})

    pbo = dict(result.get("pbo") or {})
    estimated_half_life_ms = estimate_alpha_half_life_ms(
        {float(horizon): edge for horizon, edge in edges.items()}
    )
    alpha_half_life_p95_ms = _optional_finite_positive(
        result.get("alpha_half_life_p95_ms")
    )
    end_to_end_latency_p95_ms = _optional_finite_non_negative(
        result.get("end_to_end_latency_p95_ms")
    )
    latency_safety_margin_ms = _optional_finite_non_negative(
        result.get("latency_safety_margin_ms")
    )
    if latency_safety_margin_ms is None:
        latency_safety_margin_ms = 25.0
    latency_budget_passed = (
        alpha_half_life_p95_ms is not None
        and end_to_end_latency_p95_ms is not None
        and alpha_half_life_p95_ms
        > end_to_end_latency_p95_ms + latency_safety_margin_ms
    )
    criteria = {
        "minimum_sample": bool(observable)
        and all(samples.get(str(int(h)), 0) >= minimum_events for h in observable),
        "observable_horizon": bool(observable),
        "net_positive": bool(observable)
        and all(edges.get(str(int(h)), 0.0) > 0 for h in observable),
        "period_stability": bool(observable)
        and all(stability.get(str(int(h))) is True for h in observable),
        "placebo_beaten": bool(observable)
        and all(
            placebo_edges.get(str(int(h))) is not None
            and edges.get(str(int(h)), 0.0) > float(placebo_edges[str(int(h))])
            for h in observable
        ),
        "controls_non_winning": bool(observable)
        and all(
            control_edges.get(str(int(h))) is not None
            and float(control_edges[str(int(h))]) <= 0
            for h in observable
        ),
        "costs_executable": math.isfinite(float(frais_slippage_bps))
        and float(frais_slippage_bps) >= 0,
        "bootstrap_positive": bool(observable)
        and all(
            len(bootstrap.get(str(int(h)), ())) == 2
            and bootstrap[str(int(h))][0] is not None
            and float(bootstrap[str(int(h))][0]) > 0
            for h in observable
        ),
        "pbo_acceptable": pbo.get("pbo") is not None and float(pbo["pbo"]) <= 0.5,
        "dsr_acceptable": bool(observable)
        and all(dsr.get(str(int(h)), {}).get("survit") is True for h in observable),
        "latency_budget_passed": latency_budget_passed,
    }
    promotion_status = (
        "PROMOTED"
        if all(criteria.get(name) is True for name in REQUIRED_CRITERIA)
        else "REJECTED"
    )
    now = datetime.now(timezone.utc)
    config = {
        "schema_version": SCHEMA_VERSION,
        "strategy": "lead_lag_shadow",
        "promotion_status": promotion_status,
        "dataset_hash": dataset_hash,
        "pipeline_hash": pipeline_hash,
        "freeze_ts": now.isoformat(),
        "freeze_ts_ms": int(now.timestamp() * 1000),
        "coins": sorted({str(coin).upper() for coin in coins if coin}),
        "control_coins": sorted(
            {str(coin).upper() for coin in coins_controle if coin}
        ),
        "requested_horizons_ms": requested,
        "observable_horizons_ms": observable,
        "unobservable_horizons_ms": [
            horizon for horizon in requested if horizon not in observable
        ],
        "minimum_events": int(minimum_events),
        "seuil_choc_bps": float(seuil_choc_bps),
        "edge_net_par_horizon_bps": edges,
        "sample_n_by_horizon": samples,
        "period_stability_by_horizon": stability,
        "bootstrap_mean_ci95_bps": bootstrap,
        "placebo_edge_by_horizon_bps": placebo_edges,
        "control_edge_by_horizon_bps": control_edges,
        "dsr_by_horizon": dsr,
        "pbo": pbo,
        "costs": {
            "round_trip_bps": float(frais_slippage_bps),
            "model": "real_hl_bid_ask_plus_configured_fees_and_slippage",
            "executable": criteria["costs_executable"],
        },
        "latency_budget": {
            "estimated_alpha_half_life_ms": estimated_half_life_ms,
            "alpha_half_life_p95_ms": alpha_half_life_p95_ms,
            "end_to_end_latency_p95_ms": end_to_end_latency_p95_ms,
            "safety_margin_ms": latency_safety_margin_ms,
            "remaining_budget_ms": (
                alpha_half_life_p95_ms
                - end_to_end_latency_p95_ms
                - latency_safety_margin_ms
                if latency_budget_passed
                else None
            ),
            "status": "PASS" if latency_budget_passed else "UNMEASURABLE_OR_TOO_SLOW",
        },
        "frequency": {
            "events_per_day": result.get("frequence_evenements_par_jour"),
        },
        "information_coefficient": result.get("information_coefficient")
        or {"value": None, "status": "UNMEASURABLE"},
        "regimes": result.get("regimes") or {},
        "criteria": criteria,
        "global_trials": global_trials,
        "source_status": str(result.get("statut") or "UNKNOWN"),
        "source_detail": result.get("detail"),
        "real_execution": False,
    }
    output = root_path / CONFIG_GELE
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    import os

    os.replace(temporary, output)
    return config


def _optional_finite_positive(value: Any) -> float | None:
    parsed = _optional_finite_non_negative(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _optional_finite_non_negative(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0:
        return None
    return parsed


__all__ = [
    "SEUIL_CHOC_BPS",
    "FRAIS_SLIPPAGE_BPS",
    "HORIZONS_MS",
    "charger_tape",
    "CAMPAIGN_HORIZON_MS",
    "CAMPAIGN_NOTIONAL_USD",
    "CAMPAIGN_MAX_REFERENCE_LAG_MS",
    "CAMPAIGN_MAX_EXIT_LAG_MS",
    "CAMPAIGN_EXECUTION_MODEL",
    "walk_forward_protocol_signature",
    "distribution_intervalles",
    "horizons_observables",
    "detecter_chocs",
    "episodes_par_horizon",
    "summarize_executable_episodes",
    "executable_campaign_evidence",
    "calibrate_freeze_readiness",
    "net_par_horizon",
    "backtest",
    "geler_config",
    "GLOBAL_TRIAL_LEDGER",
]
