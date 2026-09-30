"""[DATA lot2 #68] RAW PLAYBACK HARNESS : un harnais pour REJOUER des feeds réels (messages bruts capturés) dans les
tests, dans l'ordre exact, à travers un callback. Cela permet de tester le pipeline sur des données réelles
reproductibles plutôt que sur des mocks (Cryptofeed offre un playback de fichiers bruts). Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


class Playback:
    """Rejoue une séquence de messages bruts dans l'ordre, en appelant un handler pour chacun."""

    def __init__(self, messages_bruts: Iterable[Any]) -> None:
        self._messages = list(messages_bruts)

    def rejouer(self, handler: Callable[[Any], Any]) -> dict[str, Any]:
        """Passe chaque message brut au handler, dans l'ordre. Compte traités et erreurs (un handler qui lève
        n'interrompt pas le playback : l'erreur est comptée, pas masquée)."""
        traites = 0
        erreurs = 0
        for m in self._messages:
            try:
                handler(m)
                traites += 1
            except Exception:
                erreurs += 1
        return {"traites": traites, "erreurs": erreurs, "total": len(self._messages)}

    def nombre(self) -> int:
        return len(self._messages)


__all__ = ["Playback"]
