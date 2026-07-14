"""Append CAPÉ et SANS RACE pour les fichiers de replay (marks.jsonl, candidates.jsonl).

Robustesse 48h. Plusieurs process du moteur ecrivent en meme temps. Un fichier PARTAGE
reecrit par `_cap` = race -> appends ecrases (candidates gele a 09:58 le 2026-07-09).

Solution bulletproof : CHAQUE process ecrit son PROPRE fichier `<stem>.<pid>.<ext>` (writer
UNIQUE par fichier => aucune race entre process), capé ATOMIQUEMENT (tmp + os.replace). Le
lecteur agrege tous les fichiers via glob (+ l'ancien fichier mono s'il existe).

Best-effort absolu : n'echoue jamais, ne casse jamais le moteur d'observation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

# caps genereux (fenetres de replay larges) mais BORNES — loin des 29 Go du 1er crash.
MARKS_MAX_BYTES = 60_000_000        # ~60 Mo par fichier process
MARKS_MAX_LINES = 800_000
CANDIDATES_MAX_BYTES = 20_000_000   # ~20 Mo par fichier process
CANDIDATES_MAX_LINES = 200_000


def _split(filename: str) -> tuple[str, str]:
    stem, _, ext = filename.rpartition(".")
    if not stem:
        return filename, "jsonl"
    return stem, ext


def _per_process_path(base: Path, filename: str) -> Path:
    stem, ext = _split(filename)
    return base / f"{stem}.{os.getpid()}.{ext}"


def _cap_atomic(p: Path, max_bytes: int, max_lines: int) -> None:
    """Trim atomique (tmp+replace) — writer UNIQUE sur ce fichier, donc pas de race.

    Declencheur bon marche : taille en octets. Reduit TOUJOURS reellement (contrairement a
    l'ancien _cap qui, sous le cap-lignes, reecrivait le fichier a l'identique => churn + race).
    """
    try:
        if p.stat().st_size <= int(max_bytes):
            return
    except OSError:
        return
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        if len(lines) > int(max_lines):
            keep = int(max_lines)
        else:
            keep = max(1000, len(lines) // 2)  # sous le cap-lignes mais trop gros -> on halve vraiment
        lines = lines[-keep:]
        tmp = p.with_name(p.name + f".{os.getpid()}.captmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(p))  # atomique : un lecteur ne voit jamais un fichier partiel
    except Exception:
        pass


def append_replay_lines(base: str | Path, filename: str, rows: Iterable[Any], *,
                        max_bytes: int, max_lines: int) -> int:
    """Ajoute des lignes JSONL au fichier PROPRE du process courant, puis borne. Best-effort."""
    written = 0
    try:
        b = Path(base)
        b.mkdir(parents=True, exist_ok=True)
        p = _per_process_path(b, filename)
        with p.open("a", encoding="utf-8") as fh:
            for r in rows:
                try:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    written += 1
                except (TypeError, ValueError):
                    continue
        if written:
            _cap_atomic(p, max_bytes, max_lines)
    except Exception:
        pass
    return written


_ARCHIVE_DIRNAME = "_archive"


def iter_replay_files(base: str | Path, filename: str, *, include_archive: bool = False) -> list[Path]:
    """Fichiers par-process d'un stem (+ ancien fichier mono, + archives des runs precedents si demande)."""
    b = Path(base)
    stem, ext = _split(filename)
    out: list[Path] = []
    legacy = b / filename
    if legacy.exists():
        out.append(legacy)
    try:
        out.extend(sorted(b.glob(f"{stem}.*.{ext}")))
    except Exception:
        pass
    if include_archive:
        try:
            arch = b / _ARCHIVE_DIRNAME
            out.extend(sorted(arch.glob(f"**/{stem}.*.{ext}")))
            out.extend(sorted(arch.glob(f"**/{filename}")))
        except Exception:
            pass
    return out


def archive_previous_run(base: str | Path) -> dict:
    """Deplace les fichiers replay du run PRECEDENT dans <base>/_archive/run_<ts>/.

    A appeler AU BOOT (serveur eteint), AVANT tout writer : accumule les donnees pour le replay
    tout en gardant runtime/replay/ propre pour le nouveau run. Best-effort, jamais destructif
    (deplace, ne supprime pas). Ne touche jamais _archive/ ni _merged/.
    """
    import time
    b = Path(base)
    if not b.exists():
        return {"moved": 0, "dest": None}
    tops: list[Path] = []
    for stem in ("candidates", "marks"):
        try:
            tops.extend(b.glob(f"{stem}.*.jsonl"))       # fichiers par-process
        except Exception:
            pass
        legacy = b / f"{stem}.jsonl"
        if legacy.exists():
            tops.append(legacy)
    tops = [p for p in tops if p.is_file() and not p.name.endswith(".captmp")]
    if not tops:
        return {"moved": 0, "dest": None}
    dest = b / _ARCHIVE_DIRNAME / f"run_{time.strftime('%Y%m%d_%H%M%S')}"
    moved = 0
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for p in tops:
            try:
                os.replace(str(p), str(dest / p.name))  # move atomique (meme volume)
                moved += 1
            except Exception:
                continue
    except Exception:
        pass
    return {"moved": moved, "dest": str(dest)}


def read_replay_lines(base: str | Path, filename: str, *, include_archive: bool = False) -> list[dict]:
    """Agrege toutes les lignes JSONL (multi-process + archives), best-effort. Corrompues ignorees."""
    rows: list[dict] = []
    for p in iter_replay_files(base, filename, include_archive=include_archive):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    return rows


def merge_replay(base: str | Path, out_dir: str | Path | None = None) -> dict:
    """Concatene les fichiers par-process en un seul fichier par stem (pour le replay/outillage).

    Ecrit dans <base>/_merged/ par defaut (dir DIFFERENT pour ne pas se re-lire). Best-effort.
    """
    b = Path(base)
    out = Path(out_dir) if out_dir else (b / "_merged")
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name in ("candidates.jsonl", "marks.jsonl"):
        rows = read_replay_lines(b, name, include_archive=True)  # tout l'historique accumule
        try:
            with (out / name).open("w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        except Exception:
            pass
        counts[name] = len(rows)
    return {"out": str(out), "counts": counts}


def _main(argv=None) -> int:  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(description="Outillage replay : fusion ou archivage du run precedent.")
    ap.add_argument("--base", default="runtime/replay")
    ap.add_argument("--out", default="")
    ap.add_argument("--archive-run", action="store_true",
                    help="Deplace le run precedent dans _archive/ (a appeler au boot, serveur eteint)")
    a = ap.parse_args(argv)
    if a.archive_run:
        print(json.dumps(archive_previous_run(a.base), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(merge_replay(a.base, a.out or None), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())


__all__ = ["append_replay_lines", "read_replay_lines", "iter_replay_files", "merge_replay",
           "archive_previous_run",
           "MARKS_MAX_BYTES", "MARKS_MAX_LINES", "CANDIDATES_MAX_BYTES", "CANDIDATES_MAX_LINES"]
