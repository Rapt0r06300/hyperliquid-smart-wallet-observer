"""[LAB α item 15] Rafraîchissement PÉRIODIQUE du dashboard/ETA — même pendant une opération BLOQUANTE
(grosse lecture, checksum, replay, backtest). Un thread de fond appelle le callback toutes les
`intervalle_s`, indépendamment de l'avancement des étapes. La logique de boucle est PURE et injectable
(horloge/sleep) → testable sans thread ni temps réel. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable


def boucler_rafraichissement(callback: Callable[[], Any], arret: threading.Event, *,
                             intervalle_s: float = 1.0, dormir: Callable[[float], None] = time.sleep,
                             max_passes: int | None = None) -> int:
    """Boucle PURE : `callback()` puis dort `intervalle_s`, jusqu'à `arret` (ou `max_passes`). Rend le
    nombre de passes. Le callback est appelé AVANT chaque sleep → au moins une passe même si l'arrêt est
    demandé tout de suite après le démarrage d'une opération bloquante."""
    n = 0
    while not arret.is_set():
        callback()
        n += 1
        if max_passes is not None and n >= max_passes:
            break
        dormir(max(0.01, float(intervalle_s)))
    return n


class RafraichisseurPeriodique:
    """Contexte : démarre un thread daemon qui rafraîchit toutes les `intervalle_s` pendant le bloc `with`,
    puis s'arrête proprement (join borné). Un verrou évite deux rendus simultanés (thread de fond vs boucle
    principale). Usage : `with RafraichisseurPeriodique(rendre, intervalle_s=1.0): grosse_operation()`."""

    def __init__(self, callback: Callable[[], Any], *, intervalle_s: float = 1.0):
        self._verrou = threading.Lock()
        self._callback_brut = callback
        self.intervalle_s = float(intervalle_s)
        self._arret = threading.Event()
        self._th: threading.Thread | None = None
        self.passes = 0

    def _rendre_verrouille(self) -> None:
        # sérialise les rendus : le thread de fond n'entre jamais en concurrence d'affichage avec l'appelant.
        with self._verrou:
            self._callback_brut()
            self.passes += 1

    def __enter__(self) -> "RafraichisseurPeriodique":
        self._arret.clear()

        def _run() -> None:
            while not self._arret.wait(self.intervalle_s):
                try:
                    self._rendre_verrouille()
                except Exception:  # noqa: BLE001 — un rendu qui échoue ne doit jamais tuer le travail
                    import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
                    _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)

        self._th = threading.Thread(target=_run, name="dashboard-refresh", daemon=True)
        self._th.start()
        return self

    def rafraichir_maintenant(self) -> None:
        """Rendu immédiat, thread-safe (utilisable aussi par la boucle principale)."""
        self._rendre_verrouille()

    def __exit__(self, *exc: Any) -> None:
        self._arret.set()
        if self._th is not None:
            self._th.join(timeout=2.0)
            self._th = None


__all__ = ["boucler_rafraichissement", "RafraichisseurPeriodique"]
