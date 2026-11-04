"""[AUD-308/360/361/372] Qualite de marche : regime d'OPTIONS (a partir d'IV/skew), filtre anti-
MANIPULATION (spoofing/wash/quote flicker), detection de PANNES CORRELEES de sources et de
CHANGEMENTS SILENCIEUX d'API (schema). stdlib pure, 0 reseau, 0 ordre reel."""
from __future__ import annotations

import math
from typing import Mapping, Sequence


def classer_regime_options(*, iv_atm: float, skew_25d: float) -> dict:
    """Regime d'options (offline) a partir de l'IV ATM et du skew 25-delta : un skew tres negatif +
    une IV haute = demande de protection = peur (PANIQUE)."""
    if iv_atm >= 0.8 or skew_25d <= -0.10:
        regime = "PANIQUE"
    elif iv_atm >= 0.5 or skew_25d <= -0.05:
        regime = "STRESSE"
    else:
        regime = "CALME"
    return {"regime": regime, "iv_atm": iv_atm, "skew_25d": skew_25d}


def filtrer_manipulation(quotes: Sequence[Mapping], *, flicker_ms: float = 50.0) -> dict:
    """Filtre les quotes MANIPULATOIRES : ordres poses puis retires en < flicker_ms (spoofing/flicker)
    -> ne pas croire un carnet epais qui s'evapore a l'approche."""
    suspects = [i for i, q in enumerate(quotes)
                if q.get("annule_apres_ms") is not None and q["annule_apres_ms"] < flicker_ms]
    sset = set(suspects)
    return {"propres": [q for i, q in enumerate(quotes) if i not in sset],
            "suspects": suspects, "n_suspects": len(suspects)}


def pannes_correlees(status_par_source: Mapping[str, str]) -> dict:
    """Pannes CORRELEES : si plusieurs sources tombent en meme temps, c'est peut-etre NOTRE infra (pas
    les sources) -> ne pas conclure a tort que 'le marche est calme'."""
    down = sorted(n for n, s in status_par_source.items() if s == "DOWN")
    total = len(status_par_source)
    correle = total > 0 and len(down) >= max(2, total // 2)
    return {"panne_correlee": correle, "down": down,
            "cause_probable": "INFRA_LOCALE" if correle else "SOURCE_ISOLEE"}


def detecter_changement_api(schema_avant: Mapping, schema_apres: Mapping) -> dict:
    """Changement SILENCIEUX d'API : champs disparus/apparus/de type change entre deux captures de
    schema -> on ne parse pas a l'aveugle un format qui a bouge."""
    a, b = set(schema_avant), set(schema_apres)
    disparus, apparus = sorted(a - b), sorted(b - a)
    types_changes = sorted(k for k in (a & b) if schema_avant[k] != schema_apres[k])
    return {"a_change": bool(disparus or apparus or types_changes),
            "disparus": disparus, "apparus": apparus, "types_changes": types_changes}


def assess_copy_vault_market_quality(
    row: Mapping,
    *,
    as_of_ms: int,
    max_spread_bps: float = 15.0,
    min_depth_usd: float = 1_000.0,
    signal_ts_field: str = "opened_at_ms",
    book_ts_field: str = "book_ts_ms",
    spread_field: str = "spread_bps",
    depth_field: str = "depth_usd",
) -> dict:
    """Admit a Copy-Vault row only with a causal, point-in-time book snapshot."""

    if isinstance(as_of_ms, bool) or not isinstance(as_of_ms, int) or as_of_ms <= 0:
        return {"status": "UNMEASURABLE", "reason": "INVALID_CUTOFF", "admissible": False}
    try:
        max_spread = float(max_spread_bps)
        min_depth = float(min_depth_usd)
    except (TypeError, ValueError):
        max_spread = min_depth = float("nan")
    if (
        not math.isfinite(max_spread)
        or max_spread < 0
        or not math.isfinite(min_depth)
        or min_depth <= 0
    ):
        return {"status": "UNMEASURABLE", "reason": "INVALID_THRESHOLDS", "admissible": False}
    if not isinstance(row, Mapping):
        return {"status": "UNMEASURABLE", "reason": "INVALID_ROW", "admissible": False}
    signal_ts = row.get(signal_ts_field)
    book_ts = row.get(book_ts_field)
    try:
        spread = float(row.get(spread_field))
        depth = float(row.get(depth_field))
    except (TypeError, ValueError):
        return {"status": "UNMEASURABLE", "reason": "MISSING_BOOK_EVIDENCE", "admissible": False}
    if (
        isinstance(signal_ts, bool)
        or not isinstance(signal_ts, int)
        or signal_ts <= 0
        or signal_ts > as_of_ms
        or isinstance(book_ts, bool)
        or not isinstance(book_ts, int)
        or book_ts <= 0
        or book_ts > signal_ts
        or not math.isfinite(spread)
        or spread < 0
        or not math.isfinite(depth)
        or depth < 0
    ):
        return {"status": "UNMEASURABLE", "reason": "NON_CAUSAL_BOOK_EVIDENCE", "admissible": False}
    admissible = spread <= max_spread and depth >= min_depth
    return {
        "status": "ADMISSIBLE" if admissible else "REJECTED_MARKET_QUALITY",
        "reason": None if admissible else "SPREAD_OR_DEPTH_VETO",
        "admissible": admissible,
        "signal_ts_ms": signal_ts,
        "book_ts_ms": book_ts,
        "spread_bps": spread,
        "depth_usd": depth,
        "max_spread_bps": max_spread,
        "min_depth_usd": min_depth,
        "causal_snapshot": True,
        "paper_read_only": True,
        "real_execution": False,
    }


def compare_copy_vault_liquidity_veto(
    train_rows: Sequence[Mapping],
    oos_rows: Sequence[Mapping],
    *,
    cutoff_ms: int,
    max_spread_bps: float = 15.0,
    min_depth_usd: float = 1_000.0,
    gross_pnl_field: str = "gross_pnl_bps",
    cost_field: str = "cost_bps",
    signal_ts_field: str = "opened_at_ms",
    book_ts_field: str = "book_ts_ms",
    episode_id_field: str = "episode_id",
    trial_id_field: str = "trial_id",
) -> dict:
    """Compare baseline and causal spread/depth veto on the same OOS rows."""

    if isinstance(cutoff_ms, bool) or not isinstance(cutoff_ms, int) or cutoff_ms <= 0:
        return {"status": "UNMEASURABLE", "reason": "INVALID_CUTOFF", "paper_read_only": True}

    def _parse(rows: Sequence[Mapping], *, train: bool) -> tuple[list[dict], str | None]:
        parsed = []
        seen: set[str] = set()
        for row in rows or ():
            if not isinstance(row, Mapping):
                return [], "INVALID_ROW"
            episode = str(row.get(episode_id_field) or "").strip()
            trial = str(row.get(trial_id_field) or "").strip()
            ts = row.get(signal_ts_field)
            try:
                gross = float(row.get(gross_pnl_field))
                cost = float(row.get(cost_field))
            except (TypeError, ValueError):
                return [], "INVALID_NUMERIC_EVIDENCE"
            if (
                not episode
                or not trial
                or episode in seen
                or isinstance(ts, bool)
                or not isinstance(ts, int)
                or ts <= 0
                or (train and ts > cutoff_ms)
                or (not train and ts <= cutoff_ms)
                or not math.isfinite(gross)
                or not math.isfinite(cost)
                or cost < 0
            ):
                return [], "INVALID_SPLIT_OR_DUPLICATE_EPISODE"
            quality = assess_copy_vault_market_quality(
                row,
                as_of_ms=ts,
                max_spread_bps=max_spread_bps,
                min_depth_usd=min_depth_usd,
                signal_ts_field=signal_ts_field,
                book_ts_field=book_ts_field,
            )
            if quality["status"] == "UNMEASURABLE":
                return [], quality["reason"]
            seen.add(episode)
            parsed.append({
                "episode_id": episode,
                "trial_id": trial,
                "gross_pnl_bps": gross,
                "cost_bps": cost,
                "net_pnl_bps": gross - cost,
                "admissible": quality["admissible"],
            })
        return parsed, None

    train, train_error = _parse(train_rows, train=True)
    oos, oos_error = _parse(oos_rows, train=False)
    if train_error or oos_error or not train or not oos:
        return {
            "status": "UNMEASURABLE",
            "reason": train_error or oos_error or "EMPTY_SPLIT",
            "paper_read_only": True,
            "real_execution": False,
        }

    def _metrics(rows: Sequence[Mapping]) -> dict:
        if not rows:
            return {"rows": 0, "trials": 0, "net_pnl_bps": None, "cost_bps": None}
        net = sum(float(row["net_pnl_bps"]) for row in rows)
        cost = sum(float(row["cost_bps"]) for row in rows)
        return {
            "rows": len(rows),
            "trials": len({str(row["trial_id"]) for row in rows}),
            "net_pnl_bps": round(net, 8),
            "cost_bps": round(cost, 8),
            "mean_net_pnl_bps": round(net / len(rows), 8),
        }

    selected = [row for row in oos if row["admissible"]]
    baseline = _metrics(oos)
    filtered = _metrics(selected)
    comparable = bool(selected)
    return {
        "status": "COMPARABLE" if comparable else "UNMEASURABLE",
        "reason": None if comparable else "ALL_OOS_ROWS_VETOED",
        "cutoff_ms": cutoff_ms,
        "train_rows": len(train),
        "baseline_oos": baseline,
        "vetoed_oos": _metrics([row for row in oos if not row["admissible"]]),
        "accepted_oos": filtered,
        "accepted_episode_count": len(selected),
        "same_oos_episodes_and_cost_fields": True,
        "max_spread_bps": float(max_spread_bps),
        "min_depth_usd": float(min_depth_usd),
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
    }
