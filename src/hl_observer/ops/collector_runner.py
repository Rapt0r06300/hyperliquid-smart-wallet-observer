"""Boucle fiable d'un collecteur read-only.

Chaque passe publie un état JSON atomique. Les journaux sont archivés en gzip
au lieu d'être tronqués, afin de conserver l'autopsie complète sans remplir le
disque avec un unique fichier actif.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ETATS_RELPATH = Path("runtime") / "data" / "collecteurs"
LOG_MAX_BYTES = 20 * 1024 * 1024


def _ecrire_json_atomique(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=1)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def archiver_log_si_necessaire(
    root: Path, nom: str, *, max_bytes: int = LOG_MAX_BYTES
) -> Path | None:
    """Compresse un log devenu gros; aucune génération n'est écrasée."""
    log = Path(root) / "runtime" / "logs" / f"{nom}.log"
    try:
        if log.stat().st_size <= max_bytes:
            return None
    except OSError:
        return None
    archive_dir = Path(root) / "runtime" / "logs" / "archive" / nom
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    archive = archive_dir / f"{stamp}_{time.time_ns()}.log.gz"
    with log.open("rb") as source, gzip.open(archive, "wb", compresslevel=6) as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    log.unlink()
    return archive


def executer_une_passe(
    *,
    root: Path,
    nom: str,
    script: Path,
    arguments: Sequence[str],
    python: Path,
    log: Path,
    etat_precedent: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """Exécute réellement l'enfant et publie son résultat exploitable."""
    debut = time.time()
    total = int(etat_precedent.get("total_passes") or 0) + 1
    failures = int(etat_precedent.get("consecutive_failures") or 0)
    status_path = Path(root) / ETATS_RELPATH / f"{nom}.json"
    base = {
        "schema_version": 1,
        "collector": nom,
        "pid": os.getpid(),
        "python": str(Path(python).resolve()),
        "script": str(script),
        "pass_started_at": debut,
        "updated_at": debut,
        "total_passes": total,
        "total_failures": int(etat_precedent.get("total_failures") or 0),
        "consecutive_failures": failures,
        "state": "RUNNING",
        "exit_code": None,
    }
    _ecrire_json_atomique(status_path, base)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8", errors="replace") as stream:
        stream.write(
            f"\n--- passe {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
            f"python: {Path(python).resolve()}\nscript: {script}\n"
        )
        stream.flush()
        try:
            completed = subprocess.run(
                [str(python), str(script), *map(str, arguments)],
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
            code = int(completed.returncode)
        except OSError as exc:
            stream.write(f"[runner] lancement impossible: {type(exc).__name__}: {exc}\n")
            code = 127
        stream.write(f"[fin de passe, code de sortie = {code}]\n")
    fin = time.time()
    if code:
        failures += 1
    else:
        failures = 0
    etat = {
        **base,
        "state": "ERROR" if code else "WAITING",
        "exit_code": code,
        "pass_ended_at": fin,
        "updated_at": fin,
        "duration_s": round(fin - debut, 3),
        "consecutive_failures": failures,
        "total_failures": int(base["total_failures"]) + (1 if code else 0),
    }
    _ecrire_json_atomique(status_path, etat)
    return code, etat


def delai_apres_passe(*, intervalle_s: int, echecs_consecutifs: int) -> int:
    """Cadence normale après succès; réparation rapide et bornée après crash."""
    if echecs_consecutifs <= 0:
        return max(1, int(intervalle_s))
    return min(300, max(30, 2 ** min(int(echecs_consecutifs), 9)))


def _lire_etat(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3:
        print("usage: collector_runner NOM SCRIPT INTERVALLE_S [arguments...]", flush=True)
        return 2
    nom, script_arg, intervalle_arg, *arguments = args
    try:
        intervalle = max(1, int(intervalle_arg))
    except ValueError:
        print(f"[collector-runner] intervalle invalide: {intervalle_arg}", flush=True)
        return 2
    root = Path.cwd().resolve()
    script = Path(script_arg)
    if not script.is_absolute():
        script = root / script
    python = Path(sys.executable).resolve()
    log = root / "runtime" / "logs" / f"{nom}.log"
    status_path = root / ETATS_RELPATH / f"{nom}.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(
            f"\n=== session {time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"collector={nom} python={python} ===\n"
        )
    marker_path = root / "runtime" / "data" / "lanceur_session_marqueur.txt"
    try:
        marker = marker_path.read_text(encoding="utf-8").strip()
    except OSError:
        marker = ""
    try:
        max_passes = max(0, int(os.environ.get("HYPERSMART_COLLECTOR_MAX_PASSES", "0")))
    except ValueError:
        max_passes = 0
    passes_session = 0
    etat = _lire_etat(status_path)
    while True:
        from tools.collecteur_doit_vivre import doit_vivre

        vivre, motif = doit_vivre(marker, root)
        if not vivre:
            arret = {
                **etat,
                "collector": nom,
                "pid": os.getpid(),
                "state": "STOPPED",
                "reason": motif,
                "updated_at": time.time(),
            }
            _ecrire_json_atomique(status_path, arret)
            with log.open("a", encoding="utf-8") as stream:
                stream.write(f"[arrêt propre anti-orphelin] {motif}\n")
            return 0
        archiver_log_si_necessaire(root, nom)
        code, etat = executer_une_passe(
            root=root,
            nom=nom,
            script=script,
            arguments=arguments,
            python=python,
            log=log,
            etat_precedent=etat,
        )
        passes_session += 1
        if max_passes and passes_session >= max_passes:
            return code
        delai = delai_apres_passe(
            intervalle_s=intervalle,
            echecs_consecutifs=int(etat.get("consecutive_failures") or 0),
        )
        etat["next_retry_s"] = delai
        etat["updated_at"] = time.time()
        _ecrire_json_atomique(status_path, etat)
        time.sleep(delai)


if __name__ == "__main__":
    raise SystemExit(main())
