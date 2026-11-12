"""Revalidation HONNÊTE des reçus de la roadmap après une modification de code.

Un reçu ``VERIFIED_DONE`` épingle l'empreinte SHA-256 des fichiers qui le prouvent. Dès qu'un de
ces fichiers change, le reçu est périmé et le contrôle ``rig_020`` rougit : c'est voulu, une
preuve ne survit pas à la modification de ce qu'elle prouve.

``tools/regenerer_receipts.py`` recalcule ces empreintes À L'AVEUGLE et réécrit le registre : il
déclare vraie une preuve que personne n'a rejouée. Cet outil fait l'inverse :

1. il sauvegarde le registre (``runtime/roadmap/backups/``) ;
2. pour chaque reçu périmé, il REJOUE les fichiers de test cités par la commande du reçu ;
3. il AJOUTE une ligne en fin de registre (jamais de réécriture) : un reçu rafraîchi si les tests
   passent, sinon un reçu ``REVALIDATION_FAILED`` — la tâche n'est alors plus comptée comme faite.

Les deux tests qui lisent le registre lui-même sont rejoués en dernier, une fois les autres reçus
rafraîchis. Lecture seule vis-à-vis du réseau ; aucun ordre, aucune collecte.

Usage :
    python tools/revalider_receipts.py --lister        # ce qui est périmé, sans rien exécuter
    python tools/revalider_receipts.py                 # rejoue puis ajoute les reçus
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from alina_roadmap_progress import (  # noqa: E402
    _file_set_fingerprint,
    load_receipts,
    receipt_is_verified,
)
from sous_processus_isole import run_isole  # noqa: E402

RECEIPTS = Path("runtime") / "roadmap" / "ALINA_ROADMAP_3120.receipts.jsonl"
BACKUPS = Path("runtime") / "roadmap" / "backups"
_TEST_FILE = re.compile(r"tests/[\w./-]+\.py")
#: tests qui lisent le registre : rejoués en dernier, quand les autres reçus sont à jour
_LISENT_LE_REGISTRE = ("test_asf_rig_001_020_copy_vault.py", "test_roadmap_3120_progress.py")


def fichiers_de_test(command: str, root: Path) -> tuple[str, ...]:
    """Fichiers de test existants cités par la commande du reçu (ordre stable, sans doublon)."""
    cites = dict.fromkeys(_TEST_FILE.findall(str(command).replace("\\", "/")))
    return tuple(name for name in cites if (root / name).is_file())


def recus_perimes(path: Path, root: Path) -> list[dict[str, Any]]:
    """Derniers reçus ``VERIFIED_DONE`` dont la preuve ne correspond plus aux fichiers actuels."""
    return [
        row for row in load_receipts(path).values()
        if str(row.get("verdict") or "").upper() == "VERIFIED_DONE"
        and not receipt_is_verified(row, None, root)
    ]


def _empreintes(files: list[str], root: Path) -> dict[str, str] | None:
    hashes: dict[str, str] = {}
    for name in files:
        try:
            hashes[str(name)] = hashlib.sha256((root / str(name)).read_bytes()).hexdigest()
        except OSError:
            return None
    return hashes


def recu_rafraichi(row: dict[str, Any], root: Path, *, now_utc: str) -> dict[str, Any] | None:
    """Reçu identique, empreintes recalculées. ``None`` si un fichier de preuve est introuvable."""
    files = row.get("files")
    if not isinstance(files, list) or not files:
        return None
    hashes = _empreintes([str(name) for name in files], root)
    if hashes is None:
        return None
    return {
        **row, "file_sha256": hashes,
        "sha": _file_set_fingerprint([str(name) for name in files], hashes),
        "exit_code": 0, "revalidated_at_utc": now_utc,
        "revalidation_note": "Revalidated: test files of the receipt command re-run with exit code 0 "
                              "after a code change; file hashes refreshed.",
    }


def recu_echec(row: dict[str, Any], *, exit_code: int | None, now_utc: str, raison: str) -> dict[str, Any]:
    return {
        **row, "verdict": "REVALIDATION_FAILED", "run_status": "FAILED", "exit_code": exit_code,
        "revalidated_at_utc": now_utc, "revalidation_note": raison,
    }


def _rejouer(tests: tuple[str, ...], root: Path, timeout_s: int) -> int | None:
    commande = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests]
    try:
        # groupe de processus isolé : un Ctrl-C émis par pytest ne doit pas tuer cet outil ni sa mesure
        return run_isole(commande, cwd=root, timeout=timeout_s).returncode
    except (OSError, subprocess.SubprocessError):
        return None


def _ajouter(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def revalider(root: Path, *, timeout_s: int = 1800, rejouer=_rejouer, now_utc: str | None = None) -> dict[str, Any]:
    """Rejoue puis ajoute les reçus. ``rejouer`` est injectable pour les tests."""
    path = root / RECEIPTS
    now_utc = now_utc or datetime.now(UTC).isoformat()
    perimes = recus_perimes(path, root)
    bilan: dict[str, Any] = {"perimes": len(perimes), "rafraichis": 0, "echecs": 0, "non_rejouables": 0,
                             "groupes_de_tests": 0, "sauvegarde": None}
    if not perimes:
        return bilan
    sauvegarde = root / BACKUPS / f"receipts_{now_utc.replace(':', '').replace('-', '')[:15]}.jsonl"
    sauvegarde.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, sauvegarde)
    bilan["sauvegarde"] = str(sauvegarde.relative_to(root).as_posix())
    groupes: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in perimes:
        groupes.setdefault(fichiers_de_test(str(row.get("command") or ""), root), []).append(row)
    ordre = sorted(groupes, key=lambda tests: (any(name.endswith(_LISENT_LE_REGISTRE) for name in tests), tests))
    for tests in ordre:
        rows = groupes[tests]
        if not tests:
            bilan["non_rejouables"] += len(rows)      # aucune preuve rejouable : le reçu reste périmé, visible
            continue
        bilan["groupes_de_tests"] += 1
        code = rejouer(tests, root, timeout_s)
        for row in rows:
            nouveau = recu_rafraichi(row, root, now_utc=now_utc) if code == 0 else None
            if nouveau is not None:
                _ajouter(path, nouveau)
                bilan["rafraichis"] += 1
            else:
                raison = ("tests re-run failed" if code not in (0, None) else
                          "tests could not be run" if code is None else "evidence file missing")
                _ajouter(path, recu_echec(row, exit_code=code, now_utc=now_utc, raison=raison))
                bilan["echecs"] += 1
    bilan["encore_perimes"] = len(recus_perimes(path, root))
    return bilan


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--lister", action="store_true", help="liste les reçus périmés sans rien exécuter ni écrire")
    parser.add_argument("--timeout-s", type=int, default=1800, help="délai maximal par groupe de tests")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not (root / RECEIPTS).is_file():
        print(f"[revalider] registre absent : {RECEIPTS.as_posix()} — rien à faire.")
        return 0
    if args.lister:
        perimes = recus_perimes(root / RECEIPTS, root)
        groupes = {fichiers_de_test(str(row.get("command") or ""), root) for row in perimes}
        print(json.dumps({"perimes": len(perimes), "groupes_de_tests": len(groupes - {()}),
                          "exemples": sorted(str(row.get("task_id")) for row in perimes)[:20]}, ensure_ascii=False))
        return 0
    bilan = revalider(root, timeout_s=args.timeout_s)
    print(json.dumps(bilan, ensure_ascii=False, indent=1))
    return 0 if not bilan["echecs"] and not bilan.get("encore_perimes") else 3


if __name__ == "__main__":
    raise SystemExit(main())
