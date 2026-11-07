"""Affichage temps réel compact : pourcentage, ETA, débit, pour tous les CMD Alina.

Usage depuis n'importe quel script :

    from progress_display import ProgressTracker
    tracker = ProgressTracker(total=1000, label="Replay")
    for i in range(1000):
        do_work(i)
        tracker.update(1)
    tracker.finish()

Pour une campagne bornée en durée (collecteurs) :

    tracker = ProgressTracker(total_seconds=518400, label="Campagne collecte")
    while running:
        tracker.tick()   # met à jour le temps écoulé
        ...
    tracker.finish()

Pour des étapes nommées sans total connu :

    tracker = ProgressTracker(label="AlinaSync")
    tracker.step("Téléchargement shards")
    ...
    tracker.step("Décompression")
    ...
    tracker.finish()

READ-ONLY : ce module ne fait qu'afficher, il ne touche à aucun fichier ni réseau.
"""
from __future__ import annotations

import sys
import time


def _format_duration(seconds: float) -> str:
    if seconds < 0:
        return "--:--"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    h = s // 3600
    m = (s % 3600) // 60
    if h < 24:
        return f"{h}h{m:02d}m"
    d = h // 24
    h_rest = h % 24
    return f"{d}j{h_rest:02d}h{m:02d}m"


def _bar(pct: float, width: int = 20) -> str:
    filled = int(pct / 100.0 * width)
    filled = max(0, min(width, filled))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


class ProgressTracker:
    """Affichage temps réel minimal, compatible Windows CMD."""

    def __init__(
        self,
        *,
        total: int | float | None = None,
        total_seconds: float | None = None,
        label: str = "",
    ) -> None:
        self._total = float(total) if total is not None else None
        self._total_seconds = float(total_seconds) if total_seconds is not None else None
        self._label = label
        self._done = 0.0
        self._start = time.monotonic()
        self._last_print = 0.0
        self._steps: list[str] = []
        self._finished = False

    def _elapsed(self) -> float:
        return time.monotonic() - self._start

    def _pct(self) -> float:
        if self._total and self._total > 0:
            return min(100.0, self._done / self._total * 100.0)
        if self._total_seconds and self._total_seconds > 0:
            return min(100.0, self._elapsed() / self._total_seconds * 100.0)
        return 0.0

    def _eta(self) -> float:
        elapsed = self._elapsed()
        pct = self._pct()
        if pct <= 0 or pct >= 100 or elapsed < 1:
            return -1.0
        return elapsed / pct * (100.0 - pct)

    def _print(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_print) < 2.0:
            return
        self._last_print = now
        elapsed = self._elapsed()
        pct = self._pct()
        eta = self._eta()

        parts = []
        if self._label:
            parts.append(self._label)
        if pct > 0:
            parts.append(f"{_bar(pct)} {pct:5.1f}%")
        parts.append(f"ecoulé: {_format_duration(elapsed)}")
        if eta > 0:
            parts.append(f"ETA: {_format_duration(eta)}")
        if self._total and self._total > 0:
            rate = self._done / max(elapsed, 0.01)
            if rate >= 1:
                parts.append(f"{rate:.0f}/s")
            elif rate > 0:
                parts.append(f"{rate:.2f}/s")

        line = " | ".join(parts)
        sys.stdout.write(f"\r{line}  ")
        sys.stdout.flush()

    def update(self, n: int | float = 1) -> None:
        self._done += n
        self._print()

    def set_progress(self, done: int | float) -> None:
        self._done = float(done)
        self._print()

    def tick(self) -> None:
        self._print()

    def step(self, name: str) -> None:
        self._steps.append(name)
        elapsed = self._elapsed()
        label = f"{self._label} | " if self._label else ""
        line = f"\n[{label}étape {len(self._steps)}] {name} (à {_format_duration(elapsed)})"
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def message(self, text: str) -> None:
        sys.stdout.write(f"\n{text}\n")
        sys.stdout.flush()

    def finish(self, *, summary: str = "") -> None:
        if self._finished:
            return
        self._finished = True
        elapsed = self._elapsed()
        pct = self._pct()
        parts = []
        if self._label:
            parts.append(self._label)
        if pct > 0:
            parts.append(f"{_bar(min(pct, 100))} {min(pct, 100):5.1f}%")
        parts.append(f"TERMINÉ en {_format_duration(elapsed)}")
        if self._total and self._total > 0:
            parts.append(f"{int(self._done)}/{int(self._total)}")
        if summary:
            parts.append(summary)
        line = " | ".join(parts)
        sys.stdout.write(f"\r{line}  \n")
        sys.stdout.flush()


__all__ = ["ProgressTracker", "_format_duration", "_bar"]
