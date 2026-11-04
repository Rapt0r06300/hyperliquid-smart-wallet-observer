"""[COPY-VAULT #62] PER-COIN SERIALIZATION : deux fills du même vault/coin ne peuvent pas modifier SIMULTANÉMENT
l'état de position. Les mises à jour d'un même (vault, coin) doivent être sérialisées, sinon deux deltas concurrents
se marchent dessus (lost update). Ce verrou par clé détecte et empêche l'accès ré-entrant. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any


class VerrouParCoin:
    """Verrou logique par (vault, coin). `acquerir` échoue si la clé est déjà détenue (traitement concurrent)."""

    def __init__(self) -> None:
        self._detenus: set[tuple] = set()

    def _cle(self, vault: str, coin: str) -> tuple:
        return (str(vault).lower(), str(coin).upper())

    def acquerir(self, vault: str, coin: str) -> dict[str, Any]:
        """Prend le verrou si libre ; sinon refuse (un autre fill du même coin est en cours de traitement)."""
        cle = self._cle(vault, coin)
        if cle in self._detenus:
            return {"ok": False, "raison": "COIN_DEJA_EN_TRAITEMENT"}
        self._detenus.add(cle)
        return {"ok": True, "raison": "OK"}

    def liberer(self, vault: str, coin: str) -> None:
        self._detenus.discard(self._cle(vault, coin))

    def detenu(self, vault: str, coin: str) -> bool:
        return self._cle(vault, coin) in self._detenus


def serialization_receipt(*, vault: str, coin: str) -> dict[str, Any]:
    """Prove local same-key exclusion and release without performing any I/O."""
    if not isinstance(vault, str) or not vault.strip() or not isinstance(coin, str) or not coin.strip():
        return {"status": "UNMEASURABLE", "reason": "KEY_INVALID"}
    lock = VerrouParCoin()
    first = lock.acquerir(vault, coin)
    second = lock.acquerir(vault, coin)
    held_before_release = lock.detenu(vault, coin)
    lock.liberer(vault, coin)
    released = not lock.detenu(vault, coin)
    if first.get("ok") is not True or second.get("ok") is not False or not held_before_release or not released:
        return {"status": "REJECTED", "reason": "SERIALIZATION_CONTRACT_FAILED"}
    return {"status": "PROVEN", "first_acquire": first, "reentrant_acquire": second, "released": released}


__all__ = ["VerrouParCoin", "serialization_receipt"]
