"""Exploration d'une variante Copy-Vault FILTRÉE par overshoot (dérivé SAFE asset_ctx).

Réutilise la machinerie prouvée de ``copy_vault_v4_train`` (sélection causale des
continuations, replay, garde-fous statistiques, placebo, LCB multiplicité-ajustée) et
AJOUTE une dimension de grille : le **seuil d'overshoot** au-dessus duquel on NE copie
PAS (débordement de liquidation ; le prix revient souvent, l'entrée copiée serait à
mauvais prix). Le signal est **causal** et dérivé du corpus **SAFE** (``asset_ctx`` :
mark vs oracle) → la variante reste *prouvable* et donc **gelable**.

Purement ADDITIF : n'altère NI ``v21`` (champion gelé) NI l'explorateur ``v4``. Le coût
anti-overfit (``trial_count``) intègre la nouvelle dimension : la variante filtrée doit
battre STRICTEMENT la baseline non filtrée pour survivre aux portes — anti-illusion.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.copy_vault_executable import (
    replay_metaorders,
    select_observed_continuations,
    temporal_bounds,
)
from hl_observer.backtesting.copy_vault_protocol import (
    COPY_DELAY_MS,
    HORIZONS_MS,
    MAX_TARGET_LAG_MS,
)
from hl_observer.backtesting.copy_vault_v4_train import (
    REQUIRED_OBSERVED_FILLS,
    _strict_positive_int,
    assess_train_variant,
)
from hl_observer.backtesting.overshoot_signal import build_overshoot_index, copie_bloquee

#: seuils d'overshoot (bps) testés. ``None`` = pas de filtre (variante baseline comparable
#: dans le MÊME budget de multiplicité -> comparaison honnête filtré vs non filtré).
SEUILS_OVERSHOOT_BPS: tuple[float | None, ...] = (None, 50.0, 100.0, 200.0)
MECHANISM_OVERSHOOT = "copy_vault_overshoot_filtered_v1"


def filtrer_continuations(
    continuations: Sequence[Mapping[str, Any]],
    index: Mapping[str, tuple[list[int], list[float]]],
    seuil_bps: float | None,
) -> list[dict[str, Any]]:
    """Garde les continuations HORS débordement. ``seuil None`` -> aucune filtre.

    Causal : le filtre ne lit que l'overshoot d'horodatage ``<= signal_ts_ms``. Une
    continuation sans ``signal_ts_ms`` entier n'est jamais filtrée (prudence)."""
    if seuil_bps is None:
        return [dict(c) for c in continuations]
    gardees: list[dict[str, Any]] = []
    for c in continuations:
        ts = c.get("signal_ts_ms")
        if not isinstance(ts, int) or isinstance(ts, bool):
            gardees.append(dict(c))
            continue
        if not copie_bloquee(index, c.get("coin"), ts, seuil_bps=seuil_bps):
            gardees.append(dict(c))
    return gardees


def explore_overshoot_filtered_train(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    asset_ctx_rows: Sequence[Mapping[str, Any]] | None,
    *,
    seuils_bps: Sequence[float | None] = SEUILS_OVERSHOOT_BPS,
) -> dict[str, Any]:
    """Explore (required × horizon × seuil_overshoot) SANS ouvrir les heldouts."""
    ordered = sorted(
        [dict(row) for row in metaorders],
        key=lambda row: (int(row.get("signal_ts_ms") or 0), str(row.get("metaorder_id") or "")),
    )
    index = build_overshoot_index(asset_ctx_rows)
    grid = [
        (required, int(horizon), seuil)
        for required in REQUIRED_OBSERVED_FILLS
        for horizon in HORIZONS_MS
        for seuil in seuils_bps
    ]
    trial_count = len(grid)
    cont_cache: dict[int, tuple[list[dict[str, Any]], dict[str, Any]]] = {}
    variants: list[dict[str, Any]] = []
    for required, horizon, seuil in grid:
        if required not in cont_cache:
            cont_cache[required] = select_observed_continuations(
                ordered, required_observed_fills=required,
            )
        continuations, selection_audit = cont_cache[required]
        filtrees = filtrer_continuations(continuations, index, seuil)
        purge_ms = COPY_DELAY_MS + int(horizon) + MAX_TARGET_LAG_MS
        bounds = temporal_bounds(filtrees, purge_ms=purge_ms)
        ts0 = _strict_positive_int(bounds.get("train_start_ms"))
        ts1 = _strict_positive_int(bounds.get("train_end_ms"))
        if ts0 is not None and ts1 is not None and ts1 >= ts0 and filtrees:
            trades, replay_audit = replay_metaorders(
                filtrees, books_by_coin, horizon_ms=horizon,
                start_ms=ts0, end_ms=ts1, require_causal_observation=True,
            )
            placebo_trades, placebo_audit = replay_metaorders(
                filtrees, books_by_coin, horizon_ms=horizon,
                start_ms=ts0, end_ms=ts1, direction_multiplier=-1,
                require_causal_observation=True,
            )
        else:
            replay_audit = {
                "metaorders_considered": 0, "completed_positions": 0,
                "INVALID_OR_MISSING_TRAIN_BOUNDS": len(filtrees),
            }
            placebo_audit = dict(replay_audit)
            trades = []
            placebo_trades = []
        annotated = [
            {
                **trade, "mechanism": MECHANISM_OVERSHOOT, "walk_forward_segment": "train",
                "required_observed_fills": required, "continuation_horizon_ms": horizon,
                "overshoot_seuil_bps": seuil, "sizing_policy": "FIXED_PAPER_NOTIONAL_USD",
            }
            for trade in trades
        ]
        assessment = assess_train_variant(annotated, placebo_trades, trial_count=trial_count)
        variants.append(
            {
                "required_observed_fills": required, "horizon_ms": horizon,
                "overshoot_seuil_bps": seuil,
                "continuations_gardees": len(filtrees),
                "continuations_totales": len(continuations),
                "selection_audit": selection_audit, "replay_audit": replay_audit,
                "placebo_replay_audit": placebo_audit, **assessment,
            }
        )
    eligibles = [v for v in variants if v.get("eligible")]
    return {
        "mechanism": MECHANISM_OVERSHOOT, "trial_count": trial_count,
        "variants": variants, "eligible_count": len(eligibles),
    }


def explorer_si_le_contexte_existe(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    asset_ctx_rows: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """L'exploration, sauf si elle ne peut rien filtrer : alors elle est refusée, pas jouée à vide.

    Sans aucun point mark/oracle, le filtre ne bloque jamais rien : chaque variante filtrée est la
    copie exacte de la variante sans filtre. Mesuré le 2026-11-11 sur le corpus réel (ruban de contexte
    vide) : 256 replays complets pour rien à chaque passage du labo, et 96 essais comptés dans la
    multiplicité sans qu'aucun ne teste quoi que ce soit. ``LookupError`` : l'appelant note
    l'exploration comme sautée, avec sa raison.
    """
    if not build_overshoot_index(asset_ctx_rows):
        raise LookupError("NO_ASSET_CTX_POINTS")
    return explore_overshoot_filtered_train(metaorders, books_by_coin, asset_ctx_rows)


__all__ = [
    "SEUILS_OVERSHOOT_BPS", "MECHANISM_OVERSHOOT",
    "filtrer_continuations", "explore_overshoot_filtered_train", "explorer_si_le_contexte_existe",
]
