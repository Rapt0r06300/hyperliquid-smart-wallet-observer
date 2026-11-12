"""Affichage et diagnostic léger pour les CMD Alina.

Usage depuis un .cmd :
    "%PYTHON%" tools/cmd_progress.py phase "Telechargement shards" 1 3
    "%PYTHON%" tools/cmd_progress.py done 42.5
    "%PYTHON%" tools/cmd_progress.py elapsed

Modes :
    phase <nom> <index> <total>   — affiche la phase avec %
    percent <pourcentage> <nom>   — affiche un jalon global explicite
    done <seconds>                — affiche la durée totale
    elapsed                       — affiche le temps écoulé depuis ALINA_CMD_START
    retry-decision <receipt> <rc> — retente seulement un incident transitoire
    summary <receipt> <rc>        — résumé humain du reçu Git final

READ-ONLY : ce module ne fait qu'afficher, aucune mutation.
"""
from __future__ import annotations

import os
import json
import re
import sys
import time
from pathlib import Path


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


def _clean(value: object, limit: int = 240) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"https://[^/@\s]+@", "https://[REDACTED]@", text)
    text = re.sub(r"(?:ghp_|github_pat_)[A-Za-z0-9_]+", "[REDACTED]", text)
    return text[:limit]


def _load_receipt(raw_path: str) -> dict[str, object] | None:
    try:
        value = json.loads(Path(raw_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _retry_decision(receipt: dict[str, object] | None, return_code: int) -> int:
    """Return 0 only when rerunning the complete engine is justified."""
    if return_code == 0:
        print("[REPRISE] Inutile : execution reussie.", flush=True)
        return 1
    if receipt is None:
        print("[REPRISE] STOP : aucun recu fiable; nouvel essai automatique refuse.", flush=True)
        return 1
    classes = receipt.get("push_failure_classes")
    last_class = ""
    if isinstance(classes, list) and classes:
        last_class = str(classes[-1]).casefold()
    error = _clean(receipt.get("error"), 1200).casefold()
    retryable_markers = (
        "could not resolve host", "failed to connect", "connection reset",
        "connection timed out", "operation timed out", "remote end hung up",
        "rpc failed", "temporary failure", "network is unreachable",
        "github a avance", "github avance", "index.lock", "verrou git",
    )
    retryable = last_class in {"retryable_race", "retryable_network"} or any(
        marker in error for marker in retryable_markers
    )
    if retryable:
        reason = last_class or next(
            marker for marker in retryable_markers if marker in error
        )
        print(f"[REPRISE] OUI : incident transitoire ({reason}).", flush=True)
        return 0
    detail = _clean(receipt.get("error")) or str(receipt.get("status") or "echec")
    print(f"[REPRISE] NON : correction necessaire, pas d'attente inutile | {detail}", flush=True)
    return 1


def _summary(receipt: dict[str, object] | None, return_code: int) -> int:
    print("\n---------------- RESUME GIT ----------------", flush=True)
    if receipt is None:
        print(f"Statut       : ECHEC (code {return_code})", flush=True)
        print("Diagnostic   : recu LAST_SYNC.json absent ou illisible", flush=True)
        print("Action       : consulter le journal du terminal", flush=True)
        print("--------------------------------------------", flush=True)
        return 1
    status = _clean(receipt.get("status")) or "UNKNOWN"
    duration_ms = receipt.get("duration_ms")
    try:
        duration = _format_duration(float(duration_ms or 0) / 1000.0)
    except (TypeError, ValueError):
        duration = "inconnue"
    commands = receipt.get("git_commands")
    command_list = commands if isinstance(commands, list) else []
    local_sha = _clean(receipt.get("head_after") or receipt.get("head_before"), 64)
    remote_sha = _clean(receipt.get("remote_sha_observed"), 64)
    commit_message = _clean(
        receipt.get("commit_message") or receipt.get("proposed_commit_message")
    )
    success = return_code == 0 and status in {
        "SYNCHRONIZED", "DRY_RUN_ONLY", "LOCAL_CHECKPOINT_ONLY"
    }
    print(f"Statut       : {'OK' if success else 'ECHEC'} - {status}", flush=True)
    print(f"Progression  : {'100.0%' if success else str(receipt.get('progress_percent', '?')) + '% (arretee)'}", flush=True)
    print(f"Duree moteur : {duration} | commandes Git : {len(command_list)}", flush=True)
    if commit_message:
        print(f"Commit       : {commit_message}", flush=True)
    if local_sha:
        print(f"SHA local    : {local_sha[:12]}", flush=True)
    if remote_sha:
        print(f"SHA GitHub   : {remote_sha[:12]}", flush=True)
    if local_sha and remote_sha:
        print(f"Parite SHA   : {'OUI' if local_sha == remote_sha else 'NON'}", flush=True)
    slow: list[dict[str, object]] = [
        item for item in command_list
        if isinstance(item, dict) and float(item.get("duration_ms") or 0) >= 1000
    ]
    slow.sort(key=lambda item: float(item.get("duration_ms") or 0), reverse=True)
    for index, item in enumerate(slow[:3], 1):
        seconds = float(item.get("duration_ms") or 0) / 1000.0
        print(
            f"Lent #{index}      : {seconds:.1f}s - {_clean(item.get('operation'), 120)}",
            flush=True,
        )
    error = _clean(receipt.get("error"))
    if error:
        print(f"Diagnostic   : {error}", flush=True)
    if success:
        print("Action       : aucune; preuve enregistree dans LAST_SYNC.json", flush=True)
    else:
        print("Action       : corriger le diagnostic puis relancer; aucune force appliquee", flush=True)
    print("--------------------------------------------", flush=True)
    return 0 if success else 1


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

    if mode == "percent" and len(sys.argv) >= 4:
        pct = max(0.0, min(100.0, float(sys.argv[2])))
        name = sys.argv[3]
        print(f"  {_bar(pct)} {pct:5.1f}% | {name}", flush=True)
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
                print(f"  ecoule : {_format_duration(elapsed)}", flush=True)
            except ValueError:
                print("  ecoule : --:--", flush=True)
        return 0

    if mode == "start":
        print(f"{time.time()}", end="")
        return 0


    if mode == "retry-decision" and len(sys.argv) >= 4:
        receipt = _load_receipt(sys.argv[2])
        try:
            return_code = int(sys.argv[3])
        except ValueError:
            return_code = 1
        return _retry_decision(receipt, return_code)

    if mode == "summary" and len(sys.argv) >= 4:
        receipt = _load_receipt(sys.argv[2])
        try:
            return_code = int(sys.argv[3])
        except ValueError:
            return_code = 1
        return _summary(receipt, return_code)

    return 1


if __name__ == "__main__":
    sys.exit(main())
