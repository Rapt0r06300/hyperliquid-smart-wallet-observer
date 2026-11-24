"""COPIE FIGEE (24/11/2026) de ``attribute_pnl`` avant son acceleration : la reference des tests d'egalite.

Ne pas modifier : ``tests/test_attribution_rapide.py`` verifie que la version rapide rend EXACTEMENT ces sorties.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from hl_observer.backtesting.copy_vault_copiability_entrees import CopiabilityConfig, DAY_MS, PricePanel


def attribute_pnl_reference(
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
