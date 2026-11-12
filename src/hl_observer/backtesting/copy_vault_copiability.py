"""Étude de copiabilité Copy-Vault : que reste-t-il au copieur APRÈS observation et coûts ?

Ce module répond, de façon déterministe et falsifiable, à la question fondatrice de la
famille : *quels comportements de leaders contiennent encore une information exploitable
après que nous les observons, et après tous les coûts de copie ?*

Quatre instruments, tous causaux (un prix n'est lu que s'il est daté ``<= t`` et frais) :

1. **Courbes de décroissance** : dérive du prix dans le sens du fill, mesurée depuis le fill
   (contenu informationnel) puis depuis l'instant d'observation (ce qui reste au copieur).
2. **Épisodes miroir** : position leader ``0 -> ouverte -> 0`` reconstruite depuis
   ``startPosition`` ; copie « entrée à l'ouverture observée, sortie à la clôture observée »,
   nette des frais taker et des demi-spreads mesurés.
3. **Attribution du PnL leader** : exécution (fill contre mid : capture de spread, non
   copiable) contre inventaire (position x variation de prix : copiable en principe), puis
   réplication causale lente (rééquilibrage toutes les K minutes) nette de rotation.
4. **Persistance** : la sélection de leaders faite sur les jours passés gagne-t-elle le
   jour suivant ? Sans assez de jours indépendants le verdict reste ``MORE_DATA``.

Règles d'honnêteté : une donnée absente reste ``NaN`` (jamais 0) ; un coût inconnu rend le
résultat ``UNMEASURABLE`` ; une position non clôturée ne produit aucun PnL réalisé ; les
résultats issus du coffre LOCAL sont exploratoires et ne constituent pas une preuve.

PAPER / READ-ONLY : aucun ordre, aucune signature, aucun accès réseau.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

# Façade : les entrées et les mesures vivent dans deux modules voisins ; tout reste
# importable d'ici (interface inchangée pour l'outil d'étude et les tests).
from hl_observer.backtesting.copy_vault_copiability_entrees import (  # noqa: F401
    CopiabilityConfig,
    DAY_MS,
    DIRECTIONAL_LABELS,
    EVIDENCE_TIER_LOCAL,
    FILL_COLUMNS,
    H_FAST_FOLLOW,
    H_NAIVE_MIRROR,
    H_SLOW_REPLICATION,
    IDENTITY_COLUMNS,
    MECHANISM,
    PricePanel,
    SCHEMA_VERSION,
    _to_float,
    alias_legacy_symbols,
    build_candle_panel,
    build_funding_rates,
    build_mid_panel,
    build_print_panel,
    detect_sybil_clusters,
    fills_frame_from_rows,
    parse_fill_row,
    prepare_fills,
)
from hl_observer.backtesting.copy_vault_copiability_mesures import (  # noqa: F401
    attribute_pnl,
    decay_curves,
    mirror_copy_episodes,
    observation_lag_profile,
    reconstruct_episodes,
    slow_replication_persistence,
    unit_time_series_tests,
)


# --------------------------------------------------------------------------- 4. synthèse


def classify_units(
    attribution: Mapping[str, Any],
    episodes: pd.DataFrame,
    config: CopiabilityConfig | None = None,
) -> list[dict[str, Any]]:
    """Archétype de chaque unité, à partir de faits mesurés (rotation, durée, part exécution).

    * ``HFT`` : épisodes plus courts que notre latence ou rotation journalière >= 20 x
      l'exposition — information consommée avant observation, non copiable.
    * ``DIRECTIONAL_SLOW`` : rotation journalière <= 3 x l'exposition — l'inventaire porte le
      PnL, le retard de copie est sans effet : seule cible sensée d'une réplication.
    * ``SWING`` : entre les deux. ``INSUFFICIENT`` : trop peu d'exposition mesurée.
    La classe ne dit rien de la compétence : elle dit seulement si copier est *possible*.
    """

    cfg = config or CopiabilityConfig()
    if attribution.get("status") != "MEASURED":
        return []
    hours = float(attribution["market_hours"])
    closed = episodes[episodes["closed"]] if len(episodes) else episodes
    by_unit = closed.groupby("unit") if len(closed) and "unit" in closed else None
    median_duration = by_unit["duration_s"].median().to_dict() if by_unit is not None else {}
    closed_before = (
        by_unit["status"].apply(lambda s: float((s == "ALREADY_CLOSED_AT_OBSERVATION").mean())).to_dict()
        if by_unit is not None else {}
    )
    k_slow, k_fast = max(cfg.rebalance_minutes), min(cfg.rebalance_minutes)
    out = []
    for row in attribution["leaders"]:
        expo = row["mean_exposure_usd"] or 0.0
        turnover_day = row[f"turnover_k{k_fast}_usd"] / expo * 24.0 / hours if expo > 0 and hours > 0 else None
        duration = median_duration.get(row["unit"])
        before = closed_before.get(row["unit"])
        if expo < cfg.min_exposure_usd:
            archetype = "INSUFFICIENT"
        elif (turnover_day is not None and turnover_day >= 20.0) or (before is not None and before >= 0.5):
            archetype = "HFT"
        elif turnover_day is not None and turnover_day <= 3.0:
            archetype = "DIRECTIONAL_SLOW"
        else:
            archetype = "SWING"
        gross_split = abs(row["inventory_true_usd"]) + abs(row["execution_usd"])
        out.append({
            "unit": row["unit"], "archetype": archetype, "fills": row["fills"],
            "mean_exposure_usd": expo,
            "turnover_per_exposure_per_day": turnover_day,
            "median_episode_s": None if duration is None or not math.isfinite(duration) else float(duration),
            "closed_before_observation_share": before,
            "taker_notional_share": row["taker_notional_share"],
            "inventory_share_of_pnl": (abs(row["inventory_true_usd"]) / gross_split) if gross_split > 0 else None,
            f"net_k{k_slow}_usd": row[f"net_k{k_slow}_usd"],
        })
    order = {"DIRECTIONAL_SLOW": 0, "SWING": 1, "HFT": 2, "INSUFFICIENT": 3}
    return sorted(out, key=lambda r: (order[r["archetype"]], -r["mean_exposure_usd"], r["unit"]))


def fast_follow_verdict(decay: Mapping[str, Any], config: CopiabilityConfig | None = None) -> dict[str, Any]:
    """Suivre en taker les fills taker des leaders : la dérive résiduelle couvre-t-elle les frais ?

    Rejeté si, pour **chaque** horizon, la borne haute de l'IC 95 % de la dérive depuis
    l'observation reste sous les seuls frais taker aller-retour (hypothèse favorable : spread nul).
    """

    cfg = config or CopiabilityConfig()
    segment = (decay.get("segments") or {}).get("TAKER_OPEN")
    floor = 2.0 * cfg.taker_fee_bps
    if not segment or segment["units"] < 10:
        return {"hypothesis": H_FAST_FOLLOW, "status": "MORE_DATA", "reason": "moins de 10 unités taker mesurées",
                "break_even_bps": floor}
    windows = decay.get("independent_windows") or {}
    best = None
    for h in cfg.horizons_s:
        if h > cfg.fast_horizon_max_s:
            continue
        if windows and float(windows.get(str(h), 0.0)) < cfg.min_independent_windows:
            continue  # trop peu de fenêtres disjointes : horizon non concluant
        stat = segment["metrics"][f"from_observation_{h}s"]
        high = stat["ci95"][1]
        if high is not None and (best is None or high > best["ci95_high_bps"]):
            best = {"horizon_s": h, "mean_bps": stat["mean"], "ci95_high_bps": high}
    if best is None:
        return {"hypothesis": H_FAST_FOLLOW, "status": "UNMEASURABLE", "reason": "aucun horizon rapide mesurable",
                "break_even_bps": floor}
    pre = segment["metrics"]["pre_observation_bps"]["mean"]
    status = "REJECTED" if best["ci95_high_bps"] < floor else "MORE_DATA"
    # Contre-épreuve à latence quasi nulle : les ouvertures vues en moins de fast_observation_ms.
    fast_segment = (decay.get("segments") or {}).get("OPEN_OBS_RAPIDE")
    fast_evidence: dict[str, Any] = {"units": 0, "status": "MORE_DATA"}
    if fast_segment and fast_segment["units"]:
        highs = [
            (fast_segment["metrics"][f"from_observation_{h}s"]["ci95"][1], h,
             fast_segment["metrics"][f"from_observation_{h}s"]["mean"])
            for h in cfg.horizons_s if h <= cfg.fast_horizon_max_s
        ]
        highs = [x for x in highs if x[0] is not None]
        fast_evidence = {"units": fast_segment["units"], "fills": fast_segment["fills"]}
        if highs and fast_segment["units"] >= 10:
            top = max(highs)
            fast_evidence.update({
                "best_horizon_s": top[1], "mean_bps": top[2], "ci95_high_bps": top[0],
                "status": "REJECTED" if top[0] < floor else "MORE_DATA",
            })
        else:
            fast_evidence["status"] = "MORE_DATA"
    return {
        "hypothesis": H_FAST_FOLLOW, "status": status, "break_even_bps": floor,
        "fast_horizon_max_s": cfg.fast_horizon_max_s,
        "fast_observation": fast_evidence,
        "best_horizon": best, "drift_lost_before_observation_bps": pre, "units": segment["units"],
        "reason": (
            f"dérive résiduelle après observation sous les frais taker à tout horizon <= {cfg.fast_horizon_max_s} s "
            "(même avec un spread supposé nul)"
            if status == "REJECTED" else "au moins un horizon rapide n'exclut pas le seuil de rentabilité"
        ),
    }


def naive_mirror_verdict(summary: Mapping[str, Any], config: CopiabilityConfig | None = None) -> dict[str, Any]:
    """Copier chaque épisode en miroir : rejeté si l'IC 95 % entre unités est entièrement négatif."""

    cfg = config or CopiabilityConfig()
    stat = summary.get("units_net_bps") or {}
    if summary.get("status") != "MEASURED" or not stat.get("units"):
        return {"hypothesis": H_NAIVE_MIRROR, "status": "UNMEASURABLE", "reason": "aucun épisode copié mesurable"}
    high = stat["ci95"][1]
    if stat["units"] < 10 or high is None:
        status, reason = "MORE_DATA", f"{stat['units']} unité(s) avec >= {cfg.min_episodes_per_unit} épisodes"
    elif high < 0:
        status, reason = "REJECTED", "IC 95 % du net par unité entièrement négatif après coûts"
    elif stat["ci95"][0] is not None and stat["ci95"][0] > 0:
        status, reason = "PROMISING", "IC 95 % du net par unité entièrement positif (exploratoire)"
    else:
        status, reason = "MORE_DATA", "l'IC 95 % du net par unité contient zéro"
    return {
        "hypothesis": H_NAIVE_MIRROR, "status": status, "reason": reason,
        "units": stat["units"], "mean_net_bps": stat["mean"], "ci95_net_bps": stat["ci95"],
        "closed_before_observation_share": summary.get("closed_before_observation_share"),
    }


def collection_needs(
    fills: pd.DataFrame,
    panel: PricePanel,
    half_spread_bps: Mapping[str, float],
    lag: Mapping[str, Any],
    classification: Sequence[Mapping[str, Any]],
    persistence: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Besoins précis transmis aux collecteurs, classés par coût économique de l'absence.

    Chaque besoin est un fait mesuré sur les données présentes ; il ne lit aucun résultat futur
    et ne modifie donc pas la causalité des expériences.
    """

    needs: list[dict[str, Any]] = []
    total = float(fills["notional"].sum()) or 1.0
    priced = fills["coin"].map(panel.column).notna()
    missing = fills.loc[~priced].groupby("coin")["notional"].sum().sort_values(ascending=False)
    if len(missing):
        prefixes: dict[str, float] = {}
        for coin, value in missing.items():
            prefix = coin.split(":", 1)[0] if ":" in coin else "(dex principal)"
            prefixes[prefix] = prefixes.get(prefix, 0.0) + float(value)
        needs.append({
            "need": "PRIX_MANQUANT",
            "impact": f"{float(missing.sum()) / total:.1%} du notionnel des leaders sans série de prix : dérive et PnL non mesurables",
            "notional_share": float(missing.sum()) / total,
            "by_dex_prefix": {k: v / total for k, v in sorted(prefixes.items(), key=lambda kv: -kv[1])},
            "action": "collecter les mids des dex HIP-3 (info allMids avec le paramètre dex) pour les préfixes listés",
        })
    priced_coins = fills.loc[priced].groupby("coin")["notional"].sum()
    no_spread = priced_coins[[c not in half_spread_bps for c in priced_coins.index]].sort_values(ascending=False)
    if len(no_spread):
        needs.append({
            "need": "SPREAD_MANQUANT",
            "impact": f"{float(no_spread.sum()) / total:.1%} du notionnel sur des coins sans carnet/BBO : coût de copie non mesurable",
            "notional_share": float(no_spread.sum()) / total,
            "top_coins": [str(c) for c in no_spread.index[:25]],
            # classement complet (part du notionnel leader) : alimente la liste de coins des collecteurs L2
            "coins_by_notional": [[str(c), float(v) / total] for c, v in no_spread.iloc[:200].items()],
            "action": "ajouter ces coins à la collecte L2/BBO (priorité au notionnel leader)",
        })
    gaps = panel.gaps()
    if gaps:
        span = float(panel.ts[-1] - panel.ts[0]) or 1.0
        lost = float(sum(g["duration_ms"] for g in gaps))
        needs.append({
            "need": "TROUS_DE_PRIX",
            "impact": f"{lost / span:.1%} de la fenêtre sans prix frais ({len(gaps)} trou(s)) : PnL d'inventaire inconnu sur ces intervalles",
            "gap_share": lost / span, "gaps": gaps[:20],
            "action": "garder le flux de prix actif en continu, indépendamment des redémarrages des collecteurs de fills",
        })
    slow = [row for row in classification if row["archetype"] in ("DIRECTIONAL_SLOW", "SWING")]
    hft = [row for row in classification if row["archetype"] == "HFT"]
    hft_fills = sum(row["fills"] for row in hft)
    all_fills = sum(row["fills"] for row in classification) or 1
    needs.append({
        "need": "BUDGET_LEADERS",
        "impact": (
            f"{hft_fills / all_fills:.1%} des fills collectés viennent d'unités HFT non copiables ; "
            f"seulement {len(slow)} unité(s) lente(s)/swing observée(s)"
        ),
        "hft_fill_share": hft_fills / all_fills, "slow_units": len(slow), "hft_units": len(hft),
        "action": "réduire la cadence des unités HFT (elles restent dans l'univers) et élargir la découverte aux leaders à rotation lente",
    })
    needs.append({
        "need": "POSITIONS_COMPLETES",
        "impact": "la position d'un leader n'est connue que sur les coins tradés pendant la fenêtre ; le portefeuille répliqué est partiel",
        "action": "instantanés périodiques clearinghouseState des unités lentes/swing (cible de réplication, auto-réparant après fills manqués)",
        "units": [row["unit"] for row in slow[:60]],
    })
    if persistence.get("status") == "MORE_DATA":
        needs.append({
            "need": "PROFONDEUR_HISTORIQUE",
            "impact": persistence.get("reason"),
            "usable_days": persistence.get("usable_days"), "required_days": persistence.get("required_independent_days"),
            "action": "accumuler des jours complets de prix + positions sur l'univers lent ; l'historique de PnL de compte (info portfolio) permet de tester la persistance sans attendre",
        })
    if lag.get("count"):
        needs.append({
            "need": "LATENCE_OBSERVATION",
            "impact": f"retard médian {lag['median_s']:.0f} s (p95 {lag['p95_s']:.0f} s) : sans effet sur une réplication lente, fatal pour tout suivi rapide",
            "action": "ne pas dépenser de budget API pour réduire la latence des unités HFT ; mesurer et publier le retard par flux",
        })
    return needs


def run_copiability_study(
    fills: pd.DataFrame,
    panel: PricePanel,
    half_spread_bps: Mapping[str, float],
    config: CopiabilityConfig | None = None,
    *,
    funding_rates: Mapping[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    """Enchaîne les instruments sur des fills **déjà préparés** et renvoie un rapport sérialisable."""

    cfg = config or CopiabilityConfig()
    units = detect_sybil_clusters(fills, cfg)
    cluster_sizes: dict[str, int] = {}
    for representative in units.values():
        cluster_sizes[representative] = cluster_sizes.get(representative, 0) + 1
    lag = observation_lag_profile(fills)
    decay = decay_curves(fills, panel, units, cfg)
    episodes = reconstruct_episodes(fills)
    episodes, mirror = mirror_copy_episodes(episodes, panel, half_spread_bps, units, cfg)
    attribution = attribute_pnl(fills, panel, half_spread_bps, units, cfg, funding_rates=funding_rates)
    k_slow = max(cfg.rebalance_minutes)
    persistence = slow_replication_persistence(attribution, k_slow, cfg)
    classification = classify_units(attribution, episodes, cfg)
    verdicts = [
        naive_mirror_verdict(mirror, cfg),
        fast_follow_verdict(decay, cfg),
        {"hypothesis": H_SLOW_REPLICATION, **{k: v for k, v in persistence.items()}},
    ]
    universe: dict[str, Any] = {}
    if attribution.get("status") == "MEASURED":
        totals = {key: float(value.sum()) for key, value in attribution["daily"].items()}
        universe = {"market_hours": attribution["market_hours"], **totals}
        for k in cfg.rebalance_minutes:
            universe[f"net_k{k}_usd"] = (
                totals[f"inventory_k{k}_usd"] - totals[f"cost_k{k}_usd"] + totals.get(f"funding_k{k}_usd", 0.0)
            )
            universe[f"timing_k{k}_usd"] = totals[f"inventory_k{k}_usd"] - totals[f"static_k{k}_usd"]
    return {
        "schema_version": SCHEMA_VERSION,
        "mechanism": MECHANISM,
        "config": cfg.as_dict(),
        "paper_read_only": True,
        "real_execution": False,
        "economically_proven": False,
        "inputs": {
            "fills": int(len(fills)), "leaders": int(fills["vault"].nunique()) if len(fills) else 0,
            "units": len(cluster_sizes), "coins": int(fills["coin"].nunique()) if len(fills) else 0,
            "sybil_clusters": sorted(
                ({"representative": k, "addresses": v} for k, v in cluster_sizes.items() if v > 1),
                key=lambda r: (-r["addresses"], r["representative"]),
            ),
            "price_provenance": panel.provenance, "price_market_hours": panel.market_hours(),
            "coins_with_half_spread": len(half_spread_bps),
        },
        "observation_lag": lag,
        "decay": decay,
        "mirror_episodes": mirror,
        "universe_attribution": universe,
        "persistence": persistence,
        "classification": classification,
        "verdicts": verdicts,
        "collection_needs": collection_needs(fills, panel, half_spread_bps, lag, classification, persistence),
        "hypotheses_tested": len(verdicts),
        "sybil_units": dict(sorted(units.items())),
    }


def position_events_from_snapshots(
    snapshots: Iterable[Mapping[str, Any]],
) -> tuple[pd.DataFrame, dict[str, np.ndarray], dict[str, int]]:
    """Convertit des instantanés de portefeuille en événements de changement de position.

    Entrée : ``{vault, ts_ms, positions: [{coin, szi}, ...]}`` (portefeuille COMPLET observé à
    ``ts_ms``). Sortie : une table au format des fills (une ligne par changement de taille sur
    un coin, observée à l'instant de l'instantané), les instants d'observation par vault, et le
    décompte des instantanés écartés. Un coin absent d'un instantané est une position nulle
    (le portefeuille est complet) ; avant le premier instantané d'un vault rien n'est connu.

    Un instantané marqué ``perimetre_change`` (un dex du compte vient d'entrer dans le suivi) sert de
    nouveau point de départ : les positions qu'il révèle existaient déjà, AUCUN changement n'en est déduit.
    """

    per_vault: dict[str, dict[int, dict[str, float]]] = {}
    amorces: dict[str, set[int]] = {}
    rejects: dict[str, int] = {}
    for snap in snapshots:
        vault = str(snap.get("vault") or "").lower()
        ts = snap.get("ts_ms")
        positions = snap.get("positions")
        if snap.get("dex"):
            # Portefeuille d'un dex HIP-3 : il ne contient PAS les positions du dex principal. Le lire
            # comme un portefeuille complet ferait croire que tout le reste vient d'être fermé.
            rejects["portefeuille_autre_dex_non_fusionne"] = rejects.get("portefeuille_autre_dex_non_fusionne", 0) + 1
            continue
        if not vault or type(ts) is not int or ts <= 0 or not isinstance(positions, list):
            rejects["instantane_invalide"] = rejects.get("instantane_invalide", 0) + 1
            continue
        book: dict[str, float] = {}
        valid = True
        for position in positions:
            coin = str(position.get("coin") or "") if isinstance(position, Mapping) else ""
            size = _to_float(position.get("szi")) if isinstance(position, Mapping) else float("nan")
            if not coin or not math.isfinite(size):
                valid = False
                break
            book[coin] = size
        if not valid:
            rejects["position_illisible"] = rejects.get("position_illisible", 0) + 1
            continue
        if ts in per_vault.setdefault(vault, {}):
            rejects["doublon_instant"] = rejects.get("doublon_instant", 0) + 1
            continue
        per_vault[vault][ts] = book
        if snap.get("perimetre_change"):
            amorces.setdefault(vault, set()).add(ts)
    rows: list[tuple[Any, ...]] = []
    seen: dict[str, np.ndarray] = {}
    for vault in sorted(per_vault):
        times = sorted(per_vault[vault])
        seen[vault] = np.array(times, dtype=np.int64)
        previous: dict[str, float] = {}
        for ts in times:
            book = per_vault[vault][ts]
            if ts in amorces.get(vault, ()):
                rejects["perimetre_change_sans_evenement"] = rejects.get("perimetre_change_sans_evenement", 0) + 1
                previous = book
                continue
            for coin in sorted(set(previous) | set(book)):
                before, after = previous.get(coin, 0.0), book.get(coin, 0.0)
                if after != before:
                    rows.append((vault, coin, ts, ts, before, after, 1 if after > before else -1, abs(after - before)))
            previous = book
    frame = pd.DataFrame(rows, columns=["vault", "coin", "time", "obs", "start_pos", "after", "signe", "sz"])
    frame["px"] = np.nan          # un instantané n'a pas de prix d'exécution
    frame["closed_pnl"] = np.nan
    frame["fee"] = np.nan
    frame["crossed"] = np.nan
    frame["notional"] = 0.0
    return frame, seen, rejects


def run_position_replication_study(
    events: pd.DataFrame,
    observation_times: Mapping[str, np.ndarray],
    panel: PricePanel,
    half_spread_bps: Mapping[str, float],
    config: CopiabilityConfig | None = None,
    *,
    max_staleness_ms: int = 900_000,
    capital_usd: float = 350.0,
    funding_rates: Mapping[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    """Réplication lente du PORTEFEUILLE OBSERVÉ des leaders : persiste-t-elle, coûts déduits ?

    Positions : réellement observées (instantanés), donc causales. Le copieur tient à tout
    instant le dernier portefeuille vu avant ``t - réaction`` ; si le dernier instantané est
    trop ancien la position est inconnue et l'intervalle exclu. Les prix peuvent être
    reconstruits (bougies) : le rapport le dit. Résultat exploratoire, jamais une preuve.
    """

    cfg = config or CopiabilityConfig()
    units = {vault: vault for vault in observation_times}
    attribution = attribute_pnl(
        events, panel, half_spread_bps, units, cfg,
        observation_times=observation_times, max_staleness_ms=max_staleness_ms, measure_execution=False,
        funding_rates=funding_rates,
    )
    k_slow = max(cfg.rebalance_minutes)
    net = slow_replication_persistence(attribution, k_slow, cfg)
    timing = slow_replication_persistence(attribution, k_slow, cfg, component="timing")
    tests_net = unit_time_series_tests(attribution, k_slow, cfg)
    tests_timing = unit_time_series_tests(attribution, k_slow, cfg, component="timing")
    universe: dict[str, Any] = {}
    leaders: list[dict[str, Any]] = []
    if attribution.get("status") == "MEASURED":
        totals = {key: float(value.sum()) for key, value in attribution["daily"].items()}
        universe = {"market_hours": attribution["market_hours"], **totals}
        for k in cfg.rebalance_minutes:
            universe[f"net_k{k}_usd"] = (
                totals[f"inventory_k{k}_usd"] - totals[f"cost_k{k}_usd"] + totals.get(f"funding_k{k}_usd", 0.0)
            )
            universe[f"timing_k{k}_usd"] = totals[f"inventory_k{k}_usd"] - totals[f"static_k{k}_usd"]
        leaders = sorted(attribution["leaders"], key=lambda r: (-(r["mean_exposure_usd"] or 0.0), r["unit"]))
    priced = events["coin"].map(panel.column).notna() if len(events) else pd.Series([], dtype=bool)
    mean_bps = (net.get("unit_daily_return_bps") or {}).get("mean")
    return {
        "schema_version": SCHEMA_VERSION,
        "mechanism": "copy_vault_slow_replication_observed_positions_v1",
        "config": cfg.as_dict(),
        "max_staleness_ms": int(max_staleness_ms),
        "paper_read_only": True, "real_execution": False, "economically_proven": False,
        "caveats": [
            "positions observées par instantanés : un changement survenu entre deux instantanés est vu au suivant",
            "position inconnue (donc non mesurée) quand le dernier instantané est trop ancien",
            f"prix : {panel.provenance} ; l'exécution à l'intérieur d'un pas de prix n'est pas modélisée",
            "coins sans série de prix exclus : le portefeuille répliqué peut être partiel",
            "rendements journaliers autocorrélés : les statistiques t sont optimistes",
        ],
        "inputs": {
            "position_changes": int(len(events)), "leaders": len(observation_times),
            "snapshots": int(sum(len(v) for v in observation_times.values())),
            "coins": int(events["coin"].nunique()) if len(events) else 0,
            "position_changes_priced_share": float(priced.mean()) if len(events) else None,
            "price_provenance": panel.provenance, "price_market_hours": panel.market_hours(),
            "coins_with_half_spread": len(half_spread_bps),
        },
        "universe_attribution": universe,
        "leaders": leaders,
        "persistence_net": net,
        "persistence_timing": timing,
        "unit_tests_net": tests_net,
        "unit_tests_timing": tests_timing,
        "economic_scale": {
            "capital_usd": capital_usd, "leverage": 1.0,
            "usd_per_day_per_10_bps": capital_usd * 10.0 / 1e4,
            "mean_unit_return_bps_per_day": mean_bps,
            "implied_usd_per_day_at_mean": None if mean_bps is None else capital_usd * mean_bps / 1e4,
        },
        "verdicts": [{"hypothesis": H_SLOW_REPLICATION, "evidence": "OBSERVED_POSITIONS", **net}],
        "hypotheses_tested": 1,
    }


def run_retrospective_study(
    fills: pd.DataFrame,
    panel: PricePanel,
    half_spread_bps: Mapping[str, float],
    config: CopiabilityConfig | None = None,
    *,
    assumed_lag_ms: int,
    capital_usd: float = 350.0,
    funding_rates: Mapping[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    """Persistance de la réplication lente sur un historique RECONSTRUIT (fills de backfill).

    Ces fills n'ont pas été observés en temps réel : l'instant d'observation est une
    HYPOTHÈSE (``événement + assumed_lag_ms``) et l'univers a été choisi a posteriori. Le
    résultat éclaire la question « la compétence d'inventaire persiste-t-elle ? » sur plus de
    jours qu'une collecte récente, mais il ne peut **ni** promouvoir un candidat **ni** servir
    de preuve : au mieux ``PROMISING`` exploratoire, à confirmer sur des jours observés.
    """

    cfg = config or CopiabilityConfig()
    units = detect_sybil_clusters(fills, cfg)
    attribution = attribute_pnl(fills, panel, half_spread_bps, units, cfg, funding_rates=funding_rates)
    k_slow = max(cfg.rebalance_minutes)
    net = slow_replication_persistence(attribution, k_slow, cfg)
    timing = slow_replication_persistence(attribution, k_slow, cfg, component="timing")
    tests_net = unit_time_series_tests(attribution, k_slow, cfg)
    tests_timing = unit_time_series_tests(attribution, k_slow, cfg, component="timing")
    universe: dict[str, Any] = {}
    leaders: list[dict[str, Any]] = []
    if attribution.get("status") == "MEASURED":
        totals = {key: float(value.sum()) for key, value in attribution["daily"].items()}
        universe = {"market_hours": attribution["market_hours"], **totals}
        for k in cfg.rebalance_minutes:
            universe[f"net_k{k}_usd"] = (
                totals[f"inventory_k{k}_usd"] - totals[f"cost_k{k}_usd"] + totals.get(f"funding_k{k}_usd", 0.0)
            )
            universe[f"timing_k{k}_usd"] = totals[f"inventory_k{k}_usd"] - totals[f"static_k{k}_usd"]
        leaders = sorted(attribution["leaders"], key=lambda r: (-(r["mean_exposure_usd"] or 0.0), r["unit"]))
    # Échelle économique : ce qu'un rendement en bps de l'exposition représente pour NOTRE capital,
    # sans levier. Sert à garder les ordres de grandeur honnêtes ; ce n'est pas une prévision.
    mean_bps = (net.get("unit_daily_return_bps") or {}).get("mean")
    scale = {
        "capital_usd": capital_usd, "leverage": 1.0,
        "usd_per_day_per_10_bps": capital_usd * 10.0 / 1e4,
        "mean_unit_return_bps_per_day": mean_bps,
        "implied_usd_per_day_at_mean": None if mean_bps is None else capital_usd * mean_bps / 1e4,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "mechanism": "copy_vault_slow_replication_retrospective_v1",
        "config": cfg.as_dict(),
        "assumed_observation_lag_ms": int(assumed_lag_ms),
        "paper_read_only": True, "real_execution": False, "economically_proven": False,
        "caveats": [
            "fills récupérés après coup (REST backfill) : instant d'observation supposé, non mesuré",
            "univers de vaults choisi a posteriori : biais de survie possible, non corrigé",
            "prix = clôtures de bougies récupérées après coup : exécution intra-bougie non modélisée",
            "rendements journaliers autocorrélés : les statistiques t sont optimistes",
        ],
        "inputs": {
            "fills": int(len(fills)), "leaders": int(fills["vault"].nunique()) if len(fills) else 0,
            "coins": int(fills["coin"].nunique()) if len(fills) else 0,
            "price_provenance": panel.provenance, "price_market_hours": panel.market_hours(),
            "coins_with_half_spread": len(half_spread_bps),
            "fills_without_price": attribution.get("fills_without_price"),
        },
        "universe_attribution": universe,
        "leaders": leaders,
        "persistence_net": net,
        "persistence_timing": timing,
        "unit_tests_net": tests_net,
        "unit_tests_timing": tests_timing,
        "economic_scale": scale,
        "verdicts": [{"hypothesis": H_SLOW_REPLICATION, "evidence": "RETROSPECTIVE_RECONSTRUCTED", **net}],
        "hypotheses_tested": 1,
    }


__all__ = [
    "CopiabilityConfig",
    "DAY_MS",
    "DIRECTIONAL_LABELS",
    "IDENTITY_COLUMNS",
    "EVIDENCE_TIER_LOCAL",
    "FILL_COLUMNS",
    "H_FAST_FOLLOW",
    "H_NAIVE_MIRROR",
    "H_SLOW_REPLICATION",
    "MECHANISM",
    "PricePanel",
    "SCHEMA_VERSION",
    "alias_legacy_symbols",
    "attribute_pnl",
    "build_candle_panel",
    "build_funding_rates",
    "build_mid_panel",
    "build_print_panel",
    "classify_units",
    "collection_needs",
    "decay_curves",
    "detect_sybil_clusters",
    "fast_follow_verdict",
    "fills_frame_from_rows",
    "mirror_copy_episodes",
    "naive_mirror_verdict",
    "observation_lag_profile",
    "parse_fill_row",
    "position_events_from_snapshots",
    "prepare_fills",
    "reconstruct_episodes",
    "run_copiability_study",
    "run_position_replication_study",
    "run_retrospective_study",
    "slow_replication_persistence",
    "unit_time_series_tests",
]
