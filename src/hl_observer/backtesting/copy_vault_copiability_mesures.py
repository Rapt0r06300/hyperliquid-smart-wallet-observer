"""Étude de copiabilité — mesures : décroissance après observation, épisodes miroir,
attribution exécution/inventaire, rendements quotidiens par unité et persistance.

Calcul pur : aucun réseau, aucun ordre. Voir ``copy_vault_copiability`` (façade).
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from hl_observer.backtesting.copy_vault_copiability_entrees import (
    CopiabilityConfig,
    DAY_MS,
    PricePanel,
    _row_nanmean,
    _stat,
)


def observation_lag_profile(fills: pd.DataFrame) -> dict[str, Any]:
    """Retard ``observation - événement`` : la variable économique que la collecte contrôle."""

    if fills.empty:
        return {"count": 0}
    lag = (fills["obs"] - fills["time"]).to_numpy() / 1000.0
    q = np.quantile(lag, [0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
    return {
        "count": int(len(lag)),
        "p05_s": float(q[0]), "p25_s": float(q[1]), "median_s": float(q[2]),
        "p75_s": float(q[3]), "p95_s": float(q[4]), "p99_s": float(q[5]),
    }


def decay_curves(
    fills: pd.DataFrame,
    panel: PricePanel,
    units: Mapping[str, str],
    config: CopiabilityConfig | None = None,
) -> dict[str, Any]:
    """Dérive signée (bps) depuis le fill et depuis l'observation, par segment.

    Moyenne pondérée par le notionnel **à l'intérieur** d'une unité (opérateur), puis
    statistiques **entre** unités : un robot à 600 000 fills ne pèse pas plus qu'un leader lent.
    """

    cfg = config or CopiabilityConfig()
    col = fills["coin"].map(panel.column)
    keep = col.notna().to_numpy()
    f = fills.loc[keep]
    if f.empty:
        return {"status": "UNMEASURABLE", "reason": "aucun_fill_sur_un_coin_avec_prix", "segments": {}}
    c = col[keep].to_numpy().astype(np.int64)
    t = f["time"].to_numpy()
    o = f["obs"].to_numpy() + cfg.reaction_delay_ms
    s = f["signe"].to_numpy().astype(np.float64)
    w = f["notional"].to_numpy()
    m_fill = panel.at(t, c)
    m_obs = panel.at(o, c)
    columns: dict[str, np.ndarray] = {
        "leader_cost_bps": s * (f["px"].to_numpy() / m_fill - 1.0) * 1e4,
        "pre_observation_bps": s * (m_obs / m_fill - 1.0) * 1e4,
    }
    for h in cfg.horizons_s:
        columns[f"from_fill_{h}s"] = s * (panel.at(t + h * 1000, c) / m_fill - 1.0) * 1e4
        columns[f"from_observation_{h}s"] = s * (panel.at(o + h * 1000, c) / m_obs - 1.0) * 1e4
    unit_code, unit_names = pd.factorize(f["vault"].map(units).fillna(f["vault"]))
    crossed = f["crossed"].to_numpy()
    taker, maker = crossed == 1.0, crossed == 0.0
    is_open = f["is_open"].to_numpy()
    # Rapidité d'observation MESURÉE (pas supposée) : un fill vu par WebSocket l'est en une
    # fraction de seconde, un fill vu par relevé REST en dizaines de secondes. Comparer les deux
    # dit ce que vaut réellement la latence, au lieu de l'extrapoler d'une courbe.
    fast_seen = (f["obs"].to_numpy() - t) <= cfg.fast_observation_ms
    segments = {
        "ALL": np.ones(len(f), dtype=bool),
        "TAKER": taker, "MAKER": maker,
        "TAKER_OPEN": taker & is_open, "TAKER_CLOSE": taker & ~is_open,
        "MAKER_OPEN": maker & is_open, "MAKER_CLOSE": maker & ~is_open,
        "OPEN_OBS_RAPIDE": is_open & fast_seen, "OPEN_OBS_LENTE": is_open & ~fast_seen,
        "CLOSE_OBS_RAPIDE": ~is_open & fast_seen,
    }
    out: dict[str, Any] = {}
    for name, mask in segments.items():
        counts = np.bincount(unit_code[mask], minlength=len(unit_names))
        eligible = counts >= cfg.min_fills_per_unit
        segment: dict[str, Any] = {"fills": int(mask.sum()), "units": int(eligible.sum()), "metrics": {}}
        for metric, values in columns.items():
            good = mask & np.isfinite(values)
            num = np.bincount(unit_code[good], weights=(values * w)[good], minlength=len(unit_names))
            den = np.bincount(unit_code[good], weights=w[good], minlength=len(unit_names))
            per_unit = np.where(eligible & (den > 0), num / np.where(den > 0, den, 1.0), np.nan)
            segment["metrics"][metric] = _stat(per_unit, cfg)
        out[name] = segment
    hours = panel.market_hours()
    return {
        "status": "MEASURED",
        "price_provenance": panel.provenance,
        "fills_with_price": int(len(f)),
        "fills_without_price": int((~keep).sum()),
        # les fills d'une même fenêtre partagent le mouvement de marché : un horizon long sur
        # une fenêtre courte ne contient que peu d'observations réellement indépendantes.
        "independent_windows": {str(h): float(hours * 3600.0 / h) for h in cfg.horizons_s},
        "segments": out,
    }


def reconstruct_episodes(fills: pd.DataFrame) -> pd.DataFrame:
    """Épisodes ``plat -> position -> plat`` par (leader, coin), depuis ``startPosition``.

    Un fill qui inverse la position clôt l'épisode courant et ouvre le suivant. Les fills
    précédant la première ouverture observée appartiennent à une position dont l'entrée est
    inconnue : ils sont exclus (on ne peut pas copier une entrée jamais vue).
    ``continuity_breaks`` compte les ruptures ``start != position précédente`` (fills manqués).
    """

    columns = [
        "vault", "coin", "direction", "open_time", "open_obs", "open_px", "open_taker",
        "close_time", "close_obs", "closed", "fills", "leader_pnl", "leader_fee",
        "max_notional", "continuity_breaks",
    ]
    if fills.empty:
        return pd.DataFrame(columns=columns)
    f = fills
    start = f["start_pos"].to_numpy()
    after = f["after"].to_numpy()
    scale = np.maximum(1.0, np.abs(f["sz"].to_numpy()))
    flat_before = np.abs(start) <= 1e-9 * scale
    flat_after = np.abs(after) <= 1e-9 * scale
    flip = ~flat_before & ~flat_after & (np.sign(start) != np.sign(after))
    opens = (flat_before & ~flat_after) | flip
    vault_code = pd.factorize(f["vault"])[0]
    coin_code = pd.factorize(f["coin"])[0]
    new_group = np.r_[True, (vault_code[1:] != vault_code[:-1]) | (coin_code[1:] != coin_code[:-1])]
    group_id = np.cumsum(new_group) - 1
    cum = np.cumsum(opens)
    base = np.maximum.accumulate(np.where(new_group, cum - opens, 0))
    local = cum - base  # rang de l'épisode dans le groupe ; 0 = avant toute ouverture observée
    prev_after = np.r_[np.nan, after[:-1]]
    breaks = ~new_group & (np.abs(start - prev_after) > 1e-6 * np.maximum(1.0, np.abs(start)))
    in_episode = local > 0
    episode_key = group_id[in_episode].astype(np.int64) * 10_000_000 + local[in_episode]
    g = f.loc[in_episode].assign(
        _key=episode_key, _flat_after=flat_after[in_episode], _flip=flip[in_episode],
        _break=breaks[in_episode], _abs_notional=(np.abs(after) * f["px"].to_numpy())[in_episode],
    )
    # après le premier retour à plat, un fill de même rang est orphelin (ouverture manquée) :
    # son entrée est inconnue, il n'appartient à aucun épisode copiable.
    prior_flats = g.groupby("_key", sort=False)["_flat_after"].cumsum() - g["_flat_after"]
    g = g.loc[prior_flats == 0]
    if g.empty:
        return pd.DataFrame(columns=columns)
    grouped = g.groupby("_key", sort=True)
    first = g.drop_duplicates("_key", keep="first").set_index("_key").sort_index()
    last = g.drop_duplicates("_key", keep="last").set_index("_key").sort_index()
    out = pd.DataFrame({
        "vault": first["vault"], "coin": first["coin"],
        "direction": np.sign(first["after"]).astype(int),
        "open_time": first["time"], "open_obs": first["obs"], "open_px": first["px"],
        "open_taker": first["crossed"],
        "close_time": last["time"], "close_obs": last["obs"],
        "closed": last["_flat_after"].astype(bool),
        "fills": grouped.size(),
        "leader_pnl": grouped["closed_pnl"].sum(min_count=1),
        "leader_fee": grouped["fee"].sum(min_count=1),
        "max_notional": grouped["_abs_notional"].max(),
        "continuity_breaks": grouped["_break"].sum().astype(int),
    })
    # un épisode suivi, dans le même groupe, par un épisode ouvert par inversion est clos par ce fill
    keys = out.index.to_numpy()
    next_same_group = np.r_[(keys[1:] // 10_000_000) == (keys[:-1] // 10_000_000), False]
    next_first = first.shift(-1)
    next_flip = next_first["_flip"].to_numpy(dtype=object)
    next_flip = np.array([bool(x) if x is not None and x == x else False for x in next_flip])
    closed_by_flip = next_same_group & next_flip & ~out["closed"].to_numpy()
    if closed_by_flip.any():
        out.loc[closed_by_flip, "close_time"] = next_first["time"].to_numpy()[closed_by_flip].astype(np.int64)
        out.loc[closed_by_flip, "close_obs"] = next_first["obs"].to_numpy()[closed_by_flip].astype(np.int64)
        out.loc[closed_by_flip, "closed"] = True
    out["open_time"] = out["open_time"].astype(np.int64)
    out["close_time"] = out["close_time"].astype(np.int64)
    out["open_obs"] = out["open_obs"].astype(np.int64)
    out["close_obs"] = out["close_obs"].astype(np.int64)
    return out.reset_index(drop=True)[columns]


def mirror_copy_episodes(
    episodes: pd.DataFrame,
    panel: PricePanel,
    half_spread_bps: Mapping[str, float],
    units: Mapping[str, str],
    config: CopiabilityConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Copie miroir d'épisodes : net = brut - 2 x frais taker - demi-spreads d'entrée et de sortie.

    Statuts par épisode : ``OPEN_AT_END`` (aucun PnL réalisé), ``ALREADY_CLOSED_AT_OBSERVATION``
    (le leader était déjà sorti quand l'ouverture est devenue observable : abstention),
    ``UNMEASURABLE_PRICE`` / ``UNMEASURABLE_COST`` (jamais remplacés par zéro), ``COPIED``.
    """

    cfg = config or CopiabilityConfig()
    e = episodes.copy()
    if e.empty:
        return e, {"status": "UNMEASURABLE", "reason": "aucun_episode"}
    col = e["coin"].map(panel.column)
    has_col = col.notna().to_numpy()
    c = col.fillna(0).to_numpy().astype(np.int64)
    entry_t = e["open_obs"].to_numpy() + cfg.reaction_delay_ms
    exit_t = e["close_obs"].to_numpy() + cfg.reaction_delay_ms
    direction = e["direction"].to_numpy().astype(np.float64)
    m_entry = np.where(has_col, panel.at(entry_t, c), np.nan)
    m_exit = np.where(has_col, panel.at(exit_t, c), np.nan)
    m_open = np.where(has_col, panel.at(e["open_time"].to_numpy(), c), np.nan)
    hs = e["coin"].map(half_spread_bps).to_numpy(dtype=np.float64)
    e["gross_bps"] = direction * (m_exit / m_entry - 1.0) * 1e4
    e["delay_cost_bps"] = direction * (m_entry / m_open - 1.0) * 1e4
    e["cost_bps"] = 2.0 * cfg.taker_fee_bps + 2.0 * hs
    e["net_bps"] = e["gross_bps"] - e["cost_bps"]
    e["duration_s"] = (e["close_time"] - e["open_time"]) / 1000.0
    status = np.full(len(e), "COPIED", dtype=object)
    status[np.isnan(hs)] = "UNMEASURABLE_COST"
    status[~np.isfinite(e["gross_bps"].to_numpy())] = "UNMEASURABLE_PRICE"
    status[e["close_obs"].to_numpy() <= entry_t] = "ALREADY_CLOSED_AT_OBSERVATION"
    status[~e["closed"].to_numpy()] = "OPEN_AT_END"
    e["status"] = status
    e.loc[e["status"] != "COPIED", "net_bps"] = np.nan
    e["unit"] = e["vault"].map(units).fillna(e["vault"])
    copied = e[e["status"] == "COPIED"]
    closed = e[e["closed"]]
    per_unit = copied.groupby("unit")["net_bps"].agg(["size", "mean"])
    eligible = per_unit[per_unit["size"] >= cfg.min_episodes_per_unit]
    buckets = []
    for low, high in ((0, 60), (60, 300), (300, 1_800), (1_800, 7_200), (7_200, math.inf)):
        part = copied[(copied["duration_s"] >= low) & (copied["duration_s"] < high)]
        buckets.append({
            "duration_s": [low, None if math.isinf(high) else high], "episodes": int(len(part)),
            "gross_bps": _mean_or_none(part["gross_bps"]), "net_bps": _mean_or_none(part["net_bps"]),
            "hit_rate": _mean_or_none(part["net_bps"] > 0) if len(part) else None,
        })
    summary = {
        "status": "MEASURED" if len(copied) else "UNMEASURABLE",
        "price_provenance": panel.provenance,
        "episodes": int(len(e)),
        "status_counts": {k: int(v) for k, v in e["status"].value_counts().sort_index().items()},
        "closed_before_observation_share": (
            float((closed["status"] == "ALREADY_CLOSED_AT_OBSERVATION").mean()) if len(closed) else None
        ),
        "median_closed_duration_s": _median_or_none(closed["close_time"] - closed["open_time"], scale=1000.0),
        "copied": {
            "episodes": int(len(copied)),
            "gross_bps": _mean_or_none(copied["gross_bps"]),
            "delay_cost_bps": _mean_or_none(copied["delay_cost_bps"]),
            "cost_bps": _mean_or_none(copied["cost_bps"]),
            "net_bps": _mean_or_none(copied["net_bps"]),
            "hit_rate": _mean_or_none(copied["net_bps"] > 0) if len(copied) else None,
            "by_duration": buckets,
        },
        "units_net_bps": _stat(eligible["mean"].to_numpy(dtype=np.float64), cfg),
        "continuity_breaks": int(e["continuity_breaks"].sum()),
    }
    return e, summary


def _mean_or_none(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if len(values) else None


def _median_or_none(series: pd.Series, *, scale: float = 1.0) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.median() / scale) if len(values) else None


def attribute_pnl(
    fills: pd.DataFrame,
    panel: PricePanel,
    half_spread_bps: Mapping[str, float],
    units: Mapping[str, str],
    config: CopiabilityConfig | None = None,
    *,
    observation_times: Mapping[str, np.ndarray] | None = None,
    max_staleness_ms: int | None = None,
    measure_execution: bool = True,
    funding_rates: Mapping[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    """Décompose le PnL leader et mesure la réplication causale d'inventaire, par unité et par jour.

    * ``execution_usd`` : somme ``q x (prix_de_référence - prix_du_fill)`` — non copiable.
    * ``inventory_true_usd`` : position vraie x variation de prix (information parfaite).
    * ``inventory_k{K}_usd`` : position **connue du copieur** (dernier fill observé avant
      ``t - réaction``), figée entre deux rééquilibrages espacés de K minutes.
    * ``cost_k{K}_usd`` : rotation x (frais taker + demi-spread mesuré). Demi-spread inconnu
      => la paire est exclue du net et comptée dans ``cost_unmeasured_turnover_share``.
    Les intervalles sans prix frais sont exclus : PnL inconnu, jamais nul.

    ``observation_times`` + ``max_staleness_ms`` (positions issues d'instantanés) : la position
    d'un leader n'est réputée connue que si son dernier instantané date de moins de
    ``max_staleness_ms`` ; au-delà (collecte arrêtée) elle est INCONNUE et l'intervalle est
    exclu, au lieu de prolonger indéfiniment une position périmée.
    ``measure_execution=False`` : les événements ne sont pas des fills (pas de prix d'exécution).
    ``funding_rates`` (``build_funding_rates``) : funding payé ou reçu par la position répliquée
    (``-position x prix x taux horaire x durée`` : un long paie un taux positif). Là où le taux
    est inconnu, le funding n'est pas compté ET l'exposition concernée est tracée dans
    ``funding_unmeasured_k{K}_usd_hours`` : un net sans funding n'est jamais présenté comme complet.
    """

    cfg = config or CopiabilityConfig()
    ts = panel.ts
    if len(ts) < 2 or fills.empty:
        return {"status": "UNMEASURABLE", "reason": "panel_ou_fills_vides"}
    valid = panel.valid_intervals()
    dt_hours = np.where(valid, np.diff(ts), 0) / 3_600_000.0
    day = ts // DAY_MS
    days = np.unique(day)
    day_idx = np.searchsorted(days, day)
    n_days = len(days)
    day_hours = np.bincount(day_idx[:-1], weights=dt_hours, minlength=n_days)
    rebalance_index: dict[int, np.ndarray] = {}
    for k in cfg.rebalance_minutes:
        bucket = ts // (k * 60_000)
        change = np.r_[True, bucket[1:] != bucket[:-1]]
        rebalance_index[k] = np.maximum.accumulate(np.where(change, np.arange(len(ts)), 0))
    f = fills[fills["coin"].map(panel.column).notna()]
    unit_of = f["vault"].map(units).fillna(f["vault"])
    unit_names = sorted(unit_of.unique())
    unit_pos = {name: i for i, name in enumerate(unit_names)}
    n_units = len(unit_names)
    fields = ["execution_usd", "inventory_true_usd", "exposure_usd_hours", "leader_closed_pnl_usd", "leader_fee_usd"]
    for k in cfg.rebalance_minutes:
        fields += [f"inventory_k{k}_usd", f"static_k{k}_usd", f"turnover_k{k}_usd", f"cost_k{k}_usd",
                   f"unmeasured_turnover_k{k}_usd", f"funding_k{k}_usd", f"funding_unmeasured_k{k}_usd_hours"]
    acc = {name: np.zeros((n_units, n_days)) for name in fields}
    # Heures où la position de l'unité est CONNUE, par jour. Sans instantanés c'est la couverture
    # de prix du jour ; avec instantanés, seules comptent les heures où le dernier instantané est
    # frais. Diviser l'exposition par 24 h alors que la collecte n'a tourné que 3 h la
    # sous-estimerait d'un facteur 8 et gonflerait d'autant les rendements.
    unit_day_hours = np.tile(day_hours, (n_units, 1)) if observation_times is None or max_staleness_ms is None \
        else np.zeros((n_units, n_days))
    hours_done: set[str] = set()
    fills_count = np.zeros(n_units, dtype=np.int64)
    taker_notional = np.zeros(n_units)
    notional = np.zeros(n_units)
    for (vault, coin), g in f.groupby(["vault", "coin"], sort=True):
        u = unit_pos[units.get(vault, vault)]
        ci = panel.column(coin)
        price = panel.px[:, ci]
        dpx = np.diff(price)
        ok = valid & np.isfinite(dpx)
        if observation_times is not None and max_staleness_ms is not None:
            seen_times = observation_times.get(vault)
            if seen_times is None or len(seen_times) == 0:
                continue
            last = np.searchsorted(seen_times, ts, side="right") - 1
            known = (last >= 0) & ((ts - seen_times[np.clip(last, 0, len(seen_times) - 1)]) <= max_staleness_ms)
            ok = ok & known[:-1]
            if vault not in hours_done:
                hours_done.add(vault)
                measured = valid & known[:-1]
                vault_hours = np.bincount(day_idx[:-1][measured], weights=dt_hours[measured], minlength=n_days)
                unit_day_hours[u] = np.maximum(unit_day_hours[u], vault_hours)
        # la rotation est valorisée au dernier prix connu (estimation de coût, pas de PnL)
        price_known = pd.Series(price).ffill().to_numpy()
        tm = g["time"].to_numpy()
        seen = np.maximum.accumulate(g["obs"].to_numpy()) + cfg.reaction_delay_ms
        after = g["after"].to_numpy()
        first_start = float(g["start_pos"].to_numpy()[0])
        q = (g["signe"] * g["sz"]).to_numpy()
        ref = panel.at(tm, ci)
        inside = (tm >= ts[0]) & (tm <= ts[-1])
        fill_day = np.clip(np.searchsorted(days, tm // DAY_MS), 0, n_days - 1)
        priced = inside & np.isfinite(ref)
        if measure_execution:
            acc["execution_usd"][u] += np.bincount(
                fill_day[priced], weights=(q * (ref - g["px"].to_numpy()))[priced], minlength=n_days
            )
        acc["leader_closed_pnl_usd"][u] += np.bincount(
            fill_day[inside], weights=np.nan_to_num(g["closed_pnl"].to_numpy())[inside], minlength=n_days
        )
        acc["leader_fee_usd"][u] += np.bincount(
            fill_day[inside], weights=np.nan_to_num(g["fee"].to_numpy())[inside], minlength=n_days
        )

        def position(times: np.ndarray, initial: float) -> np.ndarray:
            j = np.searchsorted(times, ts, side="right") - 1
            return np.where(j >= 0, after[np.clip(j, 0, len(after) - 1)], initial)

        # la position vraie avant le premier fill est ``startPosition`` ; le copieur, lui, ne
        # sait rien avant sa première observation : il ne porte aucune position (pas d'avance).
        p_true, p_seen = position(tm, first_start), position(seen, 0.0)
        d = day_idx[:-1]
        acc["inventory_true_usd"][u] += np.bincount(d[ok], weights=(p_true[:-1] * dpx)[ok], minlength=n_days)
        expo = np.abs(p_seen[:-1]) * price[:-1] * dt_hours
        acc["exposure_usd_hours"][u] += np.bincount(d[ok], weights=expo[ok], minlength=n_days)
        hs = half_spread_bps.get(coin)
        rate = None if hs is None or not math.isfinite(hs) else (cfg.taker_fee_bps + hs) * 1e-4
        for k in cfg.rebalance_minutes:
            p_k = p_seen[rebalance_index[k]]
            acc[f"inventory_k{k}_usd"][u] += np.bincount(d[ok], weights=(p_k[:-1] * dpx)[ok], minlength=n_days)
            # Diagnostic exposition / prédiction : la part « statique » est ce qu'aurait gagné la
            # position MOYENNE de la fenêtre, tenue sans jamais bouger (pari directionnel, bêta).
            # Le reste (inventaire - statique) vient du choix des moments. La moyenne utilise
            # toute la fenêtre : c'est une décomposition a posteriori, pas une stratégie.
            weight = dt_hours[ok]
            if weight.sum() > 0:
                mean_position = float((p_k[:-1][ok] * weight).sum() / weight.sum())
                acc[f"static_k{k}_usd"][u] += mean_position * np.bincount(d[ok], weights=dpx[ok], minlength=n_days)
            # Funding de la position répliquée (connu seulement là où le taux a été observé).
            notional_hours = p_k[:-1] * price[:-1] * dt_hours
            funding_rate = None if funding_rates is None else funding_rates.get(coin)
            if funding_rate is None:
                acc[f"funding_unmeasured_k{k}_usd_hours"][u] += np.bincount(
                    d[ok], weights=np.abs(notional_hours)[ok], minlength=n_days)
            else:
                with_rate = ok & np.isfinite(funding_rate[:-1])
                acc[f"funding_k{k}_usd"][u] += np.bincount(
                    d[with_rate], weights=(-notional_hours * funding_rate[:-1])[with_rate], minlength=n_days)
                without = ok & ~np.isfinite(funding_rate[:-1])
                acc[f"funding_unmeasured_k{k}_usd_hours"][u] += np.bincount(
                    d[without], weights=np.abs(notional_hours)[without], minlength=n_days)
            turn = np.abs(np.diff(p_k)) * price_known[1:]
            turn_ok = np.isfinite(turn)
            by_day = np.bincount(day_idx[1:][turn_ok], weights=turn[turn_ok], minlength=n_days)
            acc[f"turnover_k{k}_usd"][u] += by_day
            if rate is None:
                acc[f"unmeasured_turnover_k{k}_usd"][u] += by_day
            else:
                acc[f"cost_k{k}_usd"][u] += by_day * rate
        fills_count[u] += len(g)
        notional[u] += float(g["notional"].sum())
        taker_notional[u] += float(g.loc[g["crossed"] == 1.0, "notional"].sum())
    hours_total = float(day_hours.sum())
    leaders = []
    for i, name in enumerate(unit_names):
        row: dict[str, Any] = {
            "unit": name, "fills": int(fills_count[i]),
            "taker_notional_share": float(taker_notional[i] / notional[i]) if notional[i] > 0 else None,
            "mean_exposure_usd": (
                float(acc["exposure_usd_hours"][i].sum() / unit_day_hours[i].sum())
                if unit_day_hours[i].sum() > 0 else None
            ),
            "known_hours": float(unit_day_hours[i].sum()),
        }
        for name_field in fields:
            row[name_field] = float(acc[name_field][i].sum())
        for k in cfg.rebalance_minutes:
            row[f"net_k{k}_usd"] = row[f"inventory_k{k}_usd"] - row[f"cost_k{k}_usd"] + row[f"funding_k{k}_usd"]
            row[f"timing_k{k}_usd"] = row[f"inventory_k{k}_usd"] - row[f"static_k{k}_usd"]
        leaders.append(row)
    return {
        "status": "MEASURED",
        "price_provenance": panel.provenance,
        "market_hours": hours_total,
        "days": [int(x) for x in days],
        "day_hours": [float(x) for x in day_hours],
        "unit_names": unit_names,
        "leaders": leaders,
        "daily": {name: acc[name] for name in fields},
        "unit_day_hours": unit_day_hours,
        "funding_measured": funding_rates is not None,
        "fills_without_price": int(len(fills) - len(f)),
    }


def _daily_unit_returns(
    attribution: Mapping[str, Any], k: int, cfg: CopiabilityConfig, component: str = "net"
) -> tuple[np.ndarray, list[str]]:
    """Rendements journaliers (bps de l'exposition moyenne du jour) des unités éligibles.

    ``component`` : ``net`` (inventaire - coûts) ou ``timing`` (inventaire - part statique -
    coûts : ce qui reste quand on retire le pari directionnel moyen). Unité éligible :
    exposition moyenne suffisante et coût mesuré sur au moins 95 % de sa rotation.
    Jour exploitable : couverture de prix suffisante. Tout le reste vaut ``NaN``.
    """

    if component not in ("net", "timing"):
        raise ValueError("component doit valoir 'net' ou 'timing'")
    daily = attribution["daily"]
    day_hours = np.array(attribution["day_hours"], dtype=np.float64)
    pnl = daily[f"inventory_k{k}_usd"] - daily[f"cost_k{k}_usd"]
    if f"funding_k{k}_usd" in daily:
        pnl = pnl + daily[f"funding_k{k}_usd"]
    if component == "timing":
        pnl = pnl - daily[f"static_k{k}_usd"]
    unmeasured = daily[f"unmeasured_turnover_k{k}_usd"].sum(axis=1)
    turnover = daily[f"turnover_k{k}_usd"].sum(axis=1)
    # heures où la position de CHAQUE unité est connue (par défaut : couverture de prix du jour)
    hours = np.asarray(attribution.get("unit_day_hours", np.tile(day_hours, (pnl.shape[0], 1))), dtype=np.float64)
    usable = hours >= cfg.min_day_coverage_hours          # [unités, jours]
    usable_day = usable.any(axis=0)                       # jour exploitable pour au moins une unité
    exposure = daily["exposure_usd_hours"] / np.where(hours > 0, hours, np.nan)
    # Base de capital STABLE par unité : son exposition moyenne pondérée par le temps, sur ses
    # jours exploitables. Diviser par l'exposition du jour même ferait exploser le rendement les
    # jours où la position est presque nulle — un artefact, pas une performance.
    known = np.where(usable, hours, 0.0).sum(axis=1)
    base = np.where(known > 0, np.where(usable, daily["exposure_usd_hours"], 0.0).sum(axis=1)
                    / np.where(known > 0, known, 1.0), np.nan)
    eligible = np.nan_to_num(base) >= cfg.min_exposure_usd
    eligible &= unmeasured <= 0.05 * np.where(turnover > 0, turnover, 1.0)
    # Fenêtre propre à l'unité : du premier au dernier jour où une position a été répliquée.
    # Avant sa première observation le copieur ne sait rien : ces jours ne sont pas des « 0 ».
    active = usable & (np.nan_to_num(exposure) > 0)
    index = np.arange(active.shape[1])
    first = np.where(active.any(axis=1), active.argmax(axis=1), active.shape[1])
    last = np.where(active.any(axis=1), active.shape[1] - 1 - active[:, ::-1].argmax(axis=1), -1)
    in_span = (index >= first[:, None]) & (index <= last[:, None])
    safe_base = np.where(base > 0, base, np.nan)[:, None]
    ret = np.where(usable & in_span, pnl / safe_base, np.nan) * 1e4
    names = [name for name, keep in zip(attribution["unit_names"], eligible, strict=True) if keep]
    return ret[eligible][:, usable_day], names


def unit_time_series_tests(
    attribution: Mapping[str, Any], rebalance_minutes: int, config: CopiabilityConfig | None = None,
    *, component: str = "net", min_days: int = 10,
) -> dict[str, Any]:
    """Test par opérateur : son rendement journalier de réplication est-il positif dans le temps ?

    Test t unilatéral par unité sur ses jours mesurés, puis correction de Bonferroni sur le
    nombre d'unités testées (on cherche un gagnant parmi N : le seuil monte avec N).
    Limite connue : les rendements journaliers d'une même position sont autocorrélés, le t
    est donc optimiste ; un « significatif » ici n'est qu'un candidat à rejouer hors échantillon.
    """

    cfg = config or CopiabilityConfig()
    if attribution.get("status") != "MEASURED":
        return {"status": "UNMEASURABLE", "reason": "attribution_non_mesuree", "units": []}
    from scipy import stats  # dépendance déclarée du projet ; import local pour un module léger

    ret, names = _daily_unit_returns(attribution, rebalance_minutes, cfg, component)
    rows = []
    for name, series in zip(names, ret, strict=True):
        x = series[np.isfinite(series)]
        if len(x) < min_days:
            continue
        sd = float(np.std(x, ddof=1))
        t = float(np.mean(x) / (sd / math.sqrt(len(x)))) if sd > 0 else 0.0
        rows.append({"unit": name, "days": int(len(x)), "mean_bps_per_day": float(np.mean(x)),
                     "sd_bps": sd, "t": t, "share_positive_days": float((x > 0).mean())})
    tested = len(rows)
    for row in rows:
        row["critical_t_bonferroni"] = float(stats.t.ppf(1.0 - 0.05 / tested, df=row["days"] - 1))
        row["significant_after_bonferroni"] = bool(row["t"] > row["critical_t_bonferroni"])
    rows.sort(key=lambda r: (-r["t"], r["unit"]))
    return {
        "status": "MEASURED" if tested else "MORE_DATA",
        "component": component, "rebalance_minutes": rebalance_minutes,
        "units_tested": tested, "min_days": min_days,
        "units_positive_mean": sum(1 for r in rows if r["mean_bps_per_day"] > 0),
        "units_significant_after_bonferroni": sum(1 for r in rows if r["significant_after_bonferroni"]),
        "units": rows,
    }


def slow_replication_persistence(
    attribution: Mapping[str, Any], rebalance_minutes: int, config: CopiabilityConfig | None = None,
    *, component: str = "net",
) -> dict[str, Any]:
    """La sélection de leaders sur le passé gagne-t-elle le jour suivant ? (marche avant stricte)

    Rendement journalier d'une unité = net de réplication / exposition moyenne du jour.
    Pour chaque jour ``d`` (après ``min_train_days``), on retient les unités dont la moyenne
    passée est positive, puis on mesure leur rendement moyen **le jour d** uniquement.
    Verdict ``MORE_DATA`` tant que le nombre de jours hors échantillon est insuffisant.
    """

    cfg = config or CopiabilityConfig()
    if attribution.get("status") != "MEASURED":
        return {"status": "UNMEASURABLE", "reason": "attribution_non_mesuree"}
    k = rebalance_minutes
    ret, eligible_names = _daily_unit_returns(attribution, k, cfg, component)
    n_days = ret.shape[1] if ret.ndim == 2 else 0
    result: dict[str, Any] = {
        "rebalance_minutes": k,
        "component": component,
        "usable_days": int(n_days),
        "eligible_units": len(eligible_names),
        "required_independent_days": cfg.min_independent_days,
        "unit_daily_return_bps": _stat(_row_nanmean(ret) if n_days else np.array([]), cfg),
    }
    oos: list[float] = []
    for d in range(cfg.min_train_days, n_days):
        past = _row_nanmean(ret[:, :d])
        chosen = np.isfinite(past) & (past > 0) & np.isfinite(ret[:, d])
        if chosen.sum() >= 3:
            oos.append(float(ret[chosen, d].mean()))
    result["walk_forward_days"] = len(oos)
    result["walk_forward_mean_bps_per_day"] = float(np.mean(oos)) if oos else None
    if n_days >= 2:
        half = n_days // 2
        a, b = _row_nanmean(ret[:, :half]), _row_nanmean(ret[:, half:])
        both = np.isfinite(a) & np.isfinite(b)
        if both.sum() >= 8:
            rank_a, rank_b = pd.Series(a[both]).rank(), pd.Series(b[both]).rank()
            if rank_a.std() > 0 and rank_b.std() > 0:
                result["split_half_rank_correlation"] = float(rank_a.corr(rank_b))
            result["split_half_units"] = int(both.sum())
    if len(oos) < cfg.min_independent_days:
        result["status"] = "MORE_DATA"
        result["reason"] = (
            f"{len(oos)} jour(s) hors échantillon < {cfg.min_independent_days} requis ; "
            "une fenêtre courte mesure surtout le bêta de marché, pas la compétence"
        )
    else:
        mean, sd = float(np.mean(oos)), float(np.std(oos, ddof=1))
        t = mean / (sd / math.sqrt(len(oos))) if sd > 0 else 0.0
        result["walk_forward_t"] = t
        result["status"] = "PROMISING" if t >= 2.0 else "REJECTED" if t <= 0.0 else "MORE_DATA"
        result["reason"] = "marche avant sur jours indépendants ; exploratoire tant que non rejoué sur corpus SAFE"
    return result
