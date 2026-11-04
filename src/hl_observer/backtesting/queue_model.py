"""LE MODÈLE DE FILE (idée `queue_position` de docs/archive/root-history/moisson-fini.md).

*On ne modélise **aucune** file. Et hftbacktest nous a montré le bug jumeau : le **double
comptage** (le trade **ET** la baisse du carnet) → des fills **2× trop tôt**.*

Ici on reconstruit `qty_ahead` (le volume devant nous, en FIFO) depuis les deltas L2, **corrigé du
double comptage** : la baisse de la taille d'un niveau **contient déjà** le volume tradé — on ne le
recompte pas.

🔒 **L'argument de domination (T1b).** T1b a mesuré le MM à la **borne haute** (100 % de fill) →
**0/29**. Un modèle de file ne peut qu'**abaisser** le fill. Donc ce module est **conservateur par
construction** : il n'avance notre position QUE sur les trades exécutés (jamais sur les annulations
« devant »), ce qui garantit `fill_modélisé ≤ fill_100 %`. *Si un modèle rend le MM rentable, il
est FAUX — on le jette, on ne le croit pas.* Ce module ne se branche PAS sur le chemin live : il
sert à **re-mesurer T1b** honnêtement.

Module PUR (aucun réseau, aucun état global).
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EtatFile:
    qty_devant: float   # volume restant devant nous
    rempli: bool        # notre tour est-il passé ?

    def as_dict(self) -> dict[str, Any]:
        return {"qty_devant": self.qty_devant, "rempli": self.rempli}


def cancels_nets(chg_carnet: float, qty_trade: float) -> float:
    """La part de la baisse d'un niveau qui n'est **pas** due au trade (= vraies annulations).

    🔴 C'est exactement le terme qu'hftbacktest oubliait : `chg -= cum_trade_qty`.
    """
    return max(0.0, -float(chg_carnet) - max(0.0, float(qty_trade)))


def avancer(qty_devant: float, *, chg_carnet: float, qty_trade: float) -> EtatFile:
    """Fait avancer notre position d'un tick.

    `chg_carnet` : variation SIGNÉE de la taille du niveau (négatif = il rétrécit).
    `qty_trade`  : volume EXÉCUTÉ à ce niveau ce tick.

    On ne consomme la file que par les **trades** (ils passent devant nous, FIFO). Les annulations
    nettes (`cancels_nets`) sont **calculées et exposées** pour l'audit, mais **ne nous font pas
    avancer** — c'est le choix conservateur qui garantit `fill ≤ 100 %`.
    """
    qty_devant = max(0.0, float(qty_devant))
    tr = max(0.0, float(qty_trade))
    rempli = qty_devant <= tr + 1e-12       # les trades ont dépassé ce qui nous précédait
    nouveau = max(0.0, qty_devant - tr)
    return EtatFile(qty_devant=nouveau, rempli=rempli)


def rejouer(
    qty_devant_initial: float,
    evenements: Sequence[tuple[float, float]],
) -> EtatFile:
    """Rejoue une file entière. `evenements` = suite de (chg_carnet, qty_trade)."""
    q0 = max(0.0, float(qty_devant_initial))
    etat = EtatFile(qty_devant=q0, rempli=(q0 <= 0.0))
    for chg, tr in evenements:
        if etat.rempli:
            break
        etat = avancer(etat.qty_devant, chg_carnet=chg, qty_trade=tr)
    return etat


def rejouer_evenements_l2(
    qty_devant_initial: float,
    evenements: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Replay observed aggregate L2 queue events without inventing fills.

    This evidence boundary requires a positive timestamp, a native event id,
    and finite observed volumes.  Missing or out-of-order observations remain
    ``UNMEASURABLE`` and never advance the queue.
    """

    normalized: list[tuple[float, float]] = []
    cancellation_total = 0.0
    previous_ts = 0
    for index, row in enumerate(evenements or ()):
        if not isinstance(row, Mapping):
            return {"status": "UNMEASURABLE", "reason": "L2_ROW_NOT_MAPPING", "index": index}
        try:
            ts_ms = int(row.get("ts_ms"))
        except (TypeError, ValueError, OverflowError):
            ts_ms = 0
        event_id = str(row.get("event_id") or row.get("native_event_id") or "").strip()
        if ts_ms <= 0 or not event_id or (previous_ts and ts_ms < previous_ts):
            return {
                "status": "UNMEASURABLE",
                "reason": "L2_TIMESTAMP_OR_ID_INVALID",
                "index": index,
            }
        previous_ts = ts_ms
        raw_change = row.get("chg_carnet", row.get("book_change_qty"))
        raw_trade = row.get("qty_trade", row.get("trade_qty", row.get("executed_qty")))
        try:
            change = float(raw_change)
            trade = float(raw_trade)
        except (TypeError, ValueError, OverflowError):
            return {"status": "UNMEASURABLE", "reason": "L2_VOLUME_MISSING", "index": index}
        if not math.isfinite(change) or not math.isfinite(trade) or trade < 0.0:
            return {"status": "UNMEASURABLE", "reason": "L2_VOLUME_INVALID", "index": index}
        normalized.append((change, trade))
        cancellation_total += cancels_nets(change, trade)

    if not normalized:
        return {"status": "UNMEASURABLE", "reason": "L2_EVENTS_EMPTY"}
    state = rejouer(qty_devant_initial, normalized)
    return {
        "status": "PROVEN",
        "state": state.as_dict(),
        "observed_event_count": len(normalized),
        "cancellation_qty": round(cancellation_total, 12),
        "paper_only": True,
        "real_execution": False,
    }


def fill_borne_par_100(
    qty_devant_initial: float,
    evenements: Sequence[tuple[float, float]],
) -> bool:
    """Invariant : notre fill ne peut JAMAIS être plus précoce que le modèle « 100 % de fill ».

    Le modèle 100 % remplit dès qu'un trade touche le niveau. Nous, on attend que les trades
    cumulés dépassent `qty_devant_initial`. Donc notre fill arrive **au plus tard** — jamais avant.
    """
    q0 = max(0.0, float(qty_devant_initial))
    cumul_trades = 0.0
    etat = EtatFile(qty_devant=q0, rempli=(q0 <= 0.0))
    for chg, tr in evenements:
        cumul_trades += max(0.0, float(tr))
        modele_100_rempli = cumul_trades > 0.0        # le modèle 100 % remplit dès le 1er trade
        if not etat.rempli:
            etat = avancer(etat.qty_devant, chg_carnet=chg, qty_trade=tr)
        if etat.rempli and not modele_100_rempli:
            return False   # on serait rempli AVANT le modèle 100 % → invariant violé
    return True


def maker_fill_bound_receipt(*, queue_ahead: object, trade_volume: object, observed_l2_delta: object) -> dict[str, Any]:
    """Bound unknown maker fills by observed FIFO queue volume, never by price touch."""

    try:
        queue, trades, delta = float(queue_ahead), float(trade_volume), float(observed_l2_delta)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "QUEUE_OBSERVATION_INVALID"}
    if not all(math.isfinite(value) for value in (queue, trades, delta)) or min(queue, trades) < 0.0:
        return {"status": "UNMEASURABLE", "reason": "QUEUE_OBSERVATION_INVALID"}
    return {"status": "PROVEN", "fill_upper_bound": bool(trades > queue), "cancellation_component": cancels_nets(delta, trades), "double_counting": False}


def reconcile_trade_and_delta_receipt(*, book_change: object, trade_volume: object) -> dict[str, Any]:
    """Expose one reconciliation so trade volume is not counted twice with the L2 delta."""

    try:
        change, trade = float(book_change), float(trade_volume)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "L2_VOLUME_INVALID"}
    if not math.isfinite(change) or not math.isfinite(trade) or trade < 0.0:
        return {"status": "UNMEASURABLE", "reason": "L2_VOLUME_INVALID"}
    return {"status": "PROVEN", "trade_volume": trade, "net_cancellation": cancels_nets(change, trade), "counted_once": True}
