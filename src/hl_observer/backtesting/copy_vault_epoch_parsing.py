"""Lecture STRICTE des horodatages d'époque du chargeur de carnets Copy-Vault.

POURQUOI CE MODULE EST À PART (17/11/2026). Ces quatre fonctions vivaient dans
``copy_vault_book_loader.py``, que la segmentation des trous et la vérification du lien de
référence du 16/11 avaient porté de 793 à 889 lignes pour un plafond de 800. Elles ne dépendent
d'aucun état du chargeur : elles sont extraites ici, à l'identique, et le chargeur les réimporte
sous leurs noms d'origine.

Elles refusent plutôt qu'elles n'arrondissent : un horodatage hors plage ou d'un type inattendu
lève ou rend zéro, jamais une valeur « proche ».
"""
from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

from hl_observer.paper_trading.execution_truth import MAX_SUPPORTED_EPOCH_MS


def _epoch_seconds_to_ms(value: object) -> int:
    """Convert a numeric UTC epoch-seconds value without rounding forward."""

    if type(value) is int:
        seconds = Decimal(value)
    elif isinstance(value, Decimal):
        seconds = value
    else:
        raise ValueError("epoch seconds must be a JSON number")
    milliseconds = seconds * 1_000
    if (
        not milliseconds.is_finite()
        or milliseconds <= 0
        or milliseconds > MAX_SUPPORTED_EPOCH_MS
    ):
        raise ValueError("epoch seconds outside supported UTC range")
    timestamp_ms = int(milliseconds.to_integral_value(rounding=ROUND_FLOOR))
    if timestamp_ms <= 0:
        raise ValueError("epoch seconds below millisecond resolution")
    return timestamp_ms


def _required_epoch_ms(value: object, name: str) -> int:
    if type(value) is not int or not 0 < value <= MAX_SUPPORTED_EPOCH_MS:
        raise ValueError(f"{name} must be a supported integer epoch millisecond")
    return value


def _exact_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _optional_epoch_ms(value: object) -> int:
    if type(value) is int and 0 <= value <= MAX_SUPPORTED_EPOCH_MS:
        return value
    return 0


__all__ = ["_epoch_seconds_to_ms", "_exact_non_negative_int", "_optional_epoch_ms",
           "_required_epoch_ms"]
