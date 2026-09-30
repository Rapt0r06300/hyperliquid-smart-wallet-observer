"""[COPY-VAULT lot2 #41] LEADER-STATE VERSIONING : chaque snapshot (equity + positions) du leader reçoit un NUMÉRO
DE VERSION immuable et monotone. La version permet de savoir si deux lectures viennent du même instant logique et de
rendre les décisions reproductibles/traçables. Une fois émise, une version ne change plus. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

import copy
from typing import Any


class VersionneurEtat:
    """Attribue une version monotone à chaque snapshot equity+positions. Les snapshots passés restent immuables."""

    def __init__(self) -> None:
        self._version = 0
        self._snapshots: dict[int, dict[str, Any]] = {}

    def nouveau_snapshot(self, *, equity: Any, positions: Any) -> dict[str, Any]:
        """Émet un nouveau snapshot versionné. Copie PROFONDE au stockage ET au retour : muter la valeur rendue
        n'affecte jamais le snapshot stocké (immutabilité réelle)."""
        self._version += 1
        snap = {"version": self._version, "equity": equity, "positions": copy.deepcopy(positions)}
        self._snapshots[self._version] = snap
        return copy.deepcopy(snap)

    def version_courante(self) -> int:
        return self._version

    def obtenir(self, version: int) -> Any:
        s = self._snapshots.get(int(version))
        return copy.deepcopy(s) if s is not None else None


__all__ = ["VersionneurEtat"]
