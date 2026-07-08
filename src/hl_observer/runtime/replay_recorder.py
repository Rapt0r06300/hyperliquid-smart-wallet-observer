"""Append CAPÉ (anti-bloat) pour les fichiers de replay (marks.jsonl, candidates.jsonl).

Le 1er run 48h a CRASHÉ sur du stockage brut non borné (29 Go → DB corrompue). Les
fichiers de replay sont en append : sans cap, ils regonflent pareil sur 48h. Ce
helper écrit puis rogne le fichier aux N dernières lignes / M octets — jamais de
croissance infinie. On garde toujours les plus RÉCENTS (fenêtre de replay glissante ;
les vieux candidats sans marks deviennent UNMEASURABLE, déjà géré par le replay).
Best-effort absolu : n'échoue jamais, ne casse jamais le moteur d'observation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

# caps généreux (fenêtres de replay larges) mais BORNÉS — loin des 29 Go.
MARKS_MAX_BYTES = 60_000_000        # ~60 Mo
MARKS_MAX_LINES = 800_000
CANDIDATES_MAX_BYTES = 20_000_000   # ~20 Mo
CANDIDATES_MAX_LINES = 200_000


def _cap(p: Path, max_bytes: int, max_lines: int) -> None:
    try:
        if p.stat().st_size > int(max_bytes):
            lines = p.read_text(encoding="utf-8").splitlines()[-int(max_lines):]
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def append_replay_lines(base: str | Path, filename: str, rows: Iterable[Any], *,
                        max_bytes: int, max_lines: int) -> int:
    """Ajoute des lignes JSONL puis borne le fichier. Retourne le nb écrit. Best-effort."""
    written = 0
    try:
        b = Path(base)
        b.mkdir(parents=True, exist_ok=True)
        p = b / filename
        with p.open("a", encoding="utf-8") as fh:
            for r in rows:
                try:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    written += 1
                except (TypeError, ValueError):
                    continue
        _cap(p, max_bytes, max_lines)
    except Exception:
        pass
    return written


__all__ = ["append_replay_lines", "MARKS_MAX_BYTES", "MARKS_MAX_LINES",
           "CANDIDATES_MAX_BYTES", "CANDIDATES_MAX_LINES"]
