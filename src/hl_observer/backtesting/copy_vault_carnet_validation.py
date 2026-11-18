"""VALIDER UN CARNET AVANT DE L'ADMETTRE AU REPLAY, et refuser un carnet venu du futur.

POURQUOI CE MODULE EXISTE. Ces trois fonctions vivaient dans `copy_vault_book_loader.py`, que la
borne basse `depuis_ms` du 18/11/2026 a porté de 790 à 820 lignes — au-dessus du plafond de 800 que
`test_invariants_architecture.py` défend. Son message dit la bonne chose : « corriger le câblage au
lieu de relever le plafond ». Elles forment un ensemble cohérent et autonome, donc elles partent
ensemble ; le chargeur les réimporte et les réexporte sous leurs noms d'origine.

CE QU'ELLES GARANTISSENT, et qui n'est pas négociable :

* un carnet dont l'horodatage dépasse la coupure causale est **REJETÉ**, jamais corrigé ni décalé.
  C'est la frontière qui empêche de lire l'avenir pour décider du passé ;
* un carnet incomplet est **UNMEASURABLE**, pas « nul ». Les deux états ne se confondent pas : l'un
  dit « cette donnée dit non », l'autre « cette donnée ne dit rien » ;
* les cinq niveaux de chaque côté sont validés ensemble ou refusés ensemble (`L2_SIDE_MISSING`) :
  un carnet qui n'aurait qu'un côté donnerait un spread inventé.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from hl_observer.backtesting.copy_vault_epoch_parsing import _required_epoch_ms
from hl_observer.normalization.l2_book import validate_l2_book_sides


def validated_recorded_levels(
    raw: dict[str, Any], *, bid: float, ask: float
) -> tuple[tuple[list[list[float]] | None, list[list[float]] | None] | None, str | None]:
    """Les cinq niveaux enregistrés, validés ensemble — ou refusés ensemble.

    Un carnet sans aucun niveau est accepté (il reste utilisable pour le meilleur prix), mais un
    carnet qui n'aurait QU'UN côté est refusé : son spread serait inventé.
    """
    has_bids, has_asks = "bids5" in raw, "asks5" in raw
    if not has_bids and not has_asks:
        return (None, None), None
    if has_bids != has_asks:
        return None, "L2_SIDE_MISSING"
    return validate_l2_book_sides(raw.get("bids5"), raw.get("asks5"), bid=bid, ask=ask)


def validate_complete_causal_l2(row: Mapping[str, Any], *, as_of_ms: object) -> dict[str, object]:
    """Validate a complete point-in-time L2 row before replay admission.

    Les trois états sont distincts et le restent : `UNMEASURABLE` quand la donnée ne dit rien
    (coupure invalide, carnet incomplet), `REJECTED` quand elle dit non (horodatage postérieur à la
    coupure, prix absurdes), `PROVEN` quand elle est admissible.
    """
    if type(as_of_ms) is not int or as_of_ms <= 0:
        return {"status": "UNMEASURABLE", "reason": "CUTOFF_INVALID"}
    try:
        ts = _required_epoch_ms(row.get("ts_ms"), "ts_ms")
        bid, ask = float(row["bid"]), float(row["ask"])
        bids, asks = row["bids5"], row["asks5"]
    except (KeyError, TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "L2_INCOMPLETE"}
    if (
        ts > as_of_ms
        or not all(math.isfinite(value) for value in (bid, ask))
        or bid <= 0.0
        or ask <= bid
    ):
        return {"status": "REJECTED", "reason": "L2_NOT_CAUSAL"}
    validated, reason = validate_l2_book_sides(bids, asks, bid=bid, ask=ask)
    if validated is None:
        return {"status": "REJECTED", "reason": reason or "L2_INVALID"}
    return {
        "status": "PROVEN", "reason": "OK", "ts_ms": ts,
        "levels": len(validated[0]) + len(validated[1]),
    }


def future_book_access_receipt(
    row: Mapping[str, Any], *, as_of_ms: object,
) -> dict[str, object]:
    """Reject a book snapshot that was received after the replay cutoff.

    Le reçu porte `future_snapshot_never_admitted` : c'est la trace qu'un carnet postérieur à la
    coupure n'a pas pu entrer, et elle est publiée même quand le verdict est positif.
    """
    result = validate_complete_causal_l2(row, as_of_ms=as_of_ms)
    if result.get("status") == "REJECTED" and result.get("reason") == "L2_NOT_CAUSAL":
        verdict = "REJECTED"
    elif result.get("status") == "PROVEN":
        verdict = "PROVEN"
    else:
        verdict = "UNMEASURABLE"
    return {
        **result,
        "verdict": verdict,
        "future_snapshot_never_admitted": (
            verdict != "PROVEN" or result.get("ts_ms", 0) <= int(as_of_ms)
            if type(as_of_ms) is int
            else True
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "validated_recorded_levels",
    "validate_complete_causal_l2",
    "future_book_access_receipt",
]
