"""Affichage de phase pour les CMD Alina — appelé comme sous-processus.

Usage depuis un .cmd :
    "%PYTHON%" tools/cmd_progress.py phase "Telechargement shards" 1 3
    "%PYTHON%" tools/cmd_progress.py done 42.5
    "%PYTHON%" tools/cmd_progress.py elapsed

Modes :
    phase <nom> <index> <total>   — affiche la phase avec %
    done <seconds>                — affiche la durée totale
    elapsed                       — affiche le temps écoulé depuis ALINA_CMD_START

READ-ONLY : ce module ne fait qu'afficher, aucune mutation.
"""
from __future__ import annotations

import os
import sys
import time


def _format_duration(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m{s % 60:02d}s"
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h}h{m:02d}m"


def _bar(pct: float, width: int = 20) -> str:
    filled = int(pct / 100.0 * width)
    filled = max(0, min(width, filled))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def main() -> int:
    if len(sys.argv) < 2:
        return 1

    mode = sys.argv[1]

    if mode == "phase" and len(sys.argv) >= 5:
        name = sys.argv[2]
        index = int(sys.argv[3])
        total = int(sys.argv[4])
        pct = index / max(total, 1) * 100
        print(
            f"  {_bar(pct)} {pct:5.1f}% | etape {index}/{total} : {name}",
            flush=True,
        )
        return 0

    if mode == "done":
        seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 0
        print(f"  {_bar(100)} 100.0% | TERMINE en {_format_duration(seconds)}", flush=True)
        return 0

    if mode == "elapsed":
        start_str = os.environ.get("ALINA_CMD_START", "")
        if start_str:
            try:
                elapsed = time.time() - float(start_str)
                print(f"  ecoulé: {_format_duration(elapsed)}", flush=True)
            except ValueError:
                print("  ecoulé: --:--", flush=True)
        return 0

    if mode == "start":
        print(f"{time.time()}", end="")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
