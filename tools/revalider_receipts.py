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

18/11/2026 — UN REJEU IMPOSSIBLE N'EST PAS UN REJEU RATÉ. Cet outil confondait les deux : tout
code de sortie non nul devenait ``REVALIDATION_FAILED``, écrit en fin de registre (append-only,
donc définitif). Or sur une machine saturée, Windows ne parvient pas à CRÉER le processus : il
rend ``0xC0000142`` avec une sortie VIDE, sans qu'aucun test n'ait tourné. Mesuré le 17/11/2026 :
douze groupes de tests morts ainsi en 5 s. Lancé dans cet état, l'outil aurait déclaré fausses
**103 preuves qu'il n'avait pas rejouées**, et autant de tâches auraient cessé d'être comptées.

Désormais : un rejeu qui n'a pas EU LIEU n'écrit RIEN. Le reçu reste périmé et visible, le
contrôle ``rig_020`` reste rouge, et l'opérateur relance quand la machine respire. Un verdict
négatif ne s'écrit que sur des tests qui ont réellement tourné et échoué.

18/11/2026 — LA CIRCULARITÉ DES REÇUS QUI SE PROUVENT EUX-MÊMES. Certains reçus sont prouvés par
un test qui LIT le registre (``rig_020``). Tant que leur propre reçu est périmé, ce test échoue —
donc le reçu ne peut pas être rafraîchi, donc le test continue d'échouer. Trois reçus étaient
bloqués dans cette impasse : ``ASF-RIG-010`` et ``ASF-RIG-019`` depuis le 12 et le 14/11, et
``ASF-RIG-002`` produit par le passage de ce matin — le seul échec de 103 reçus.

Les faire passer en les déclarant vrais serait une complaisance. On fait l'inverse : après avoir
écrit le verdict négatif (le reçu n'est donc plus compté comme une preuve), on REJOUE le groupe
une seconde fois. Le registre est alors dans son état final et le test peut dire la vérité. Le
reçu n'est rafraîchi que si ce second rejeu PASSE réellement. Un échec pour une autre cause
échoue deux fois et reste négatif.

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
sys.path.insert(0, str(ROOT / "src"))

from alina_roadmap_progress import (  # noqa: E402
    _file_set_fingerprint,
    load_receipts,
    receipt_is_verified,
)
from sous_processus_isole import run_isole  # noqa: E402
from hl_observer.ops.echec_silencieux import noter as _noter_echec  # noqa: E402

RECEIPTS = Path("runtime") / "roadmap" / "ALINA_ROADMAP_3120.receipts.jsonl"
BACKUPS = Path("runtime") / "roadmap" / "backups"
_TEST_FILE = re.compile(r"tests/[\w./-]+\.py")
#: tests qui lisent le registre : rejoués en dernier, quand les autres reçus sont à jour
_LISENT_LE_REGISTRE = ("test_asf_rig_001_020_copy_vault.py", "test_roadmap_3120_progress.py")

#: Codes de sortie qui disent « le sous-processus n'a PAS pu DÉMARRER », jamais « les tests ont
#: échoué » : 0xC0000142 (Windows n'a pas pu initialiser le processus — mémoire saturée),
#: 0xC0000017 (plus de mémoire), -9 (tué par l'OS, OOM killer POSIX).
CODES_NON_LANCE = frozenset({3221225794, 3221225495, -9})

#: Attente maximale, en secondes, pour laisser la mémoire respirer avant un groupe de tests.
ATTENTE_MEMOIRE_S = 120.0


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


def recus_a_reprendre(path: Path, root: Path) -> list[dict[str, Any]]:
    """Derniers reçus ``REVALIDATION_FAILED`` : candidats à une NOUVELLE tentative.

    Un verdict négatif n'est pas définitif : il peut venir d'un état transitoire (machine saturée,
    catalogue de données en retard) ou de la circularité d'un reçu qui se prouve lui-même. On ne le
    lève jamais sans rejouer : ces reçus repassent par le même chemin que les autres.
    """
    return [
        row for row in load_receipts(path).values()
        if str(row.get("verdict") or "").upper() == "REVALIDATION_FAILED"
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
        # `verdict` et `run_status` sont REMIS explicitement : un reçu repris après un
        # REVALIDATION_FAILED doit redevenir une preuve, et seulement par ce chemin — tests
        # rejoués avec le code 0 et empreintes recalculées.
        **row, "verdict": "VERIFIED_DONE", "run_status": "COMPLETED", "file_sha256": hashes,
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


def _souffler() -> None:
    """Laisse la mémoire respirer avant de lancer un groupe de tests. NE LÈVE JAMAIS.

    Sans cela, le groupe suivant part dans une machine saturée et ne démarre pas du tout.
    """
    try:
        from hl_observer.ops import budget_ram as BR

        if BR.decision()["action"] == BR.PAUSER:
            BR.attendre_que_ca_respire(limite_s=ATTENTE_MEMOIRE_S)
    except Exception as exc:  # noqa: BLE001 — un gouverneur absent ne doit pas bloquer la revalidation
        _noter_echec("tools/revalider_receipts.py:souffler", exc)


def _rejouer(tests: tuple[str, ...], root: Path, timeout_s: int) -> int | None:
    """Code de sortie des tests, ou ``None`` quand ils n'ont PAS PU être rejoués.

    ``None`` n'est pas un échec : c'est une absence de mesure. L'appelant ne doit alors rien écrire.
    """
    commande = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests]
    _souffler()
    try:
        # groupe de processus isolé : un Ctrl-C émis par pytest ne doit pas tuer cet outil ni sa mesure
        issue = run_isole(commande, cwd=root, timeout=timeout_s)
    except (OSError, subprocess.SubprocessError):
        return None
    if issue.returncode in CODES_NON_LANCE:
        return None
    # pytest écrit TOUJOURS quelque chose, même pour refuser : une sortie vide = il n'a pas tourné.
    if not ((issue.stdout or "") + (issue.stderr or "")).strip():
        return None
    return issue.returncode


def lit_le_registre(tests: tuple[str, ...]) -> bool:
    """Ce groupe de tests lit-il le registre des reçus ? Alors son reçu se prouve lui-même."""
    return any(str(name).endswith(_LISENT_LE_REGISTRE) for name in tests)


def _ajouter(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def _ecrire_verdicts(path: Path, rows: list[dict[str, Any]], root: Path, *, code: int,
                     now_utc: str, bilan: dict[str, Any]) -> int:
    """Écrit un verdict par reçu du groupe ; rend le nombre de lignes ajoutées."""
    ecrits = 0
    for row in rows:
        nouveau = recu_rafraichi(row, root, now_utc=now_utc) if code == 0 else None
        if nouveau is not None:
            _ajouter(path, nouveau)
            bilan["rafraichis"] += 1
        else:
            raison = "tests re-run failed" if code != 0 else "evidence file missing"
            _ajouter(path, recu_echec(row, exit_code=code, now_utc=now_utc, raison=raison))
            bilan["echecs"] += 1
        ecrits += 1
    return ecrits


def revalider(root: Path, *, timeout_s: int = 1800, rejouer=_rejouer, now_utc: str | None = None,
              reprendre: bool = False) -> dict[str, Any]:
    """Rejoue puis ajoute les reçus. ``rejouer`` est injectable pour les tests.

    ``reprendre`` ajoute aux candidats les reçus déjà ``REVALIDATION_FAILED`` : ils sont rejoués
    comme les autres, et ne redeviennent une preuve que si leurs tests passent.
    """
    path = root / RECEIPTS
    now_utc = now_utc or datetime.now(UTC).isoformat()
    perimes = recus_perimes(path, root)
    repris = recus_a_reprendre(path, root) if reprendre else []
    bilan: dict[str, Any] = {"perimes": len(perimes), "repris": len(repris), "rafraichis": 0,
                             "echecs": 0, "non_rejouables": 0,
                             "non_mesurables": 0, "groupes_de_tests": 0,
                             "rafraichis_au_second_essai": 0, "sauvegarde": None}
    perimes = perimes + repris
    if not perimes:
        return bilan
    sauvegarde = root / BACKUPS / f"receipts_{now_utc.replace(':', '').replace('-', '')[:15]}.jsonl"
    sauvegarde.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, sauvegarde)
    bilan["sauvegarde"] = str(sauvegarde.relative_to(root).as_posix())
    groupes: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in perimes:
        groupes.setdefault(fichiers_de_test(str(row.get("command") or ""), root), []).append(row)
    ordre = sorted(groupes, key=lambda tests: (lit_le_registre(tests), tests))
    for tests in ordre:
        rows = groupes[tests]
        if not tests:
            bilan["non_rejouables"] += len(rows)      # aucune preuve rejouable : le reçu reste périmé, visible
            continue
        bilan["groupes_de_tests"] += 1
        code = rejouer(tests, root, timeout_s)
        # La règle vit ICI, au point où l'on écrit la preuve, et pas seulement dans le lanceur :
        # le rejeu n'a pas EU LIEU (processus non démarré, machine saturée, délai dépassé), donc on
        # n'écrit RIEN. Le reçu reste périmé et visible. Écrire REVALIDATION_FAILED déclarerait
        # fausse une preuve que personne n'a rejouée — 103 reçus étaient en jeu le 17/11/2026.
        if code is None or code in CODES_NON_LANCE:
            bilan["non_mesurables"] += len(rows)
            continue
        ecrits = _ecrire_verdicts(path, rows, root, code=code, now_utc=now_utc, bilan=bilan)
        # Un reçu prouvé par un test qui LIT le registre ne peut pas se rafraîchir tant qu'il est
        # lui-même périmé : le test voit sa propre péremption et échoue. Le verdict négatif qu'on
        # vient d'écrire lève cette péremption ; on rejoue donc UNE fois, registre à jour, et on ne
        # rafraîchit que si le test passe pour de bon.
        if ecrits and code != 0 and lit_le_registre(tests):
            second = rejouer(tests, root, timeout_s)
            if second == 0:
                for row in rows:
                    nouveau = recu_rafraichi(row, root, now_utc=now_utc)
                    if nouveau is not None:
                        _ajouter(path, nouveau)
                        bilan["rafraichis"] += 1
                        bilan["rafraichis_au_second_essai"] += 1
                        bilan["echecs"] -= 1
    bilan["encore_perimes"] = len(recus_perimes(path, root))
    bilan["encore_en_echec"] = len(recus_a_reprendre(path, root))
    return bilan


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--lister", action="store_true", help="liste les reçus périmés sans rien exécuter ni écrire")
    parser.add_argument("--timeout-s", type=int, default=1800, help="délai maximal par groupe de tests")
    parser.add_argument("--reprendre", action="store_true",
                        help="retente aussi les reçus déjà REVALIDATION_FAILED (ils ne redeviennent "
                             "une preuve que si leurs tests passent)")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not (root / RECEIPTS).is_file():
        print(f"[revalider] registre absent : {RECEIPTS.as_posix()} — rien à faire.")
        return 0
    if args.lister:
        perimes = recus_perimes(root / RECEIPTS, root)
        en_echec = recus_a_reprendre(root / RECEIPTS, root)
        groupes = {fichiers_de_test(str(row.get("command") or ""), root) for row in perimes}
        print(json.dumps({"perimes": len(perimes), "en_echec": len(en_echec),
                          "groupes_de_tests": len(groupes - {()}),
                          "exemples": sorted(str(row.get("task_id")) for row in perimes)[:20],
                          "exemples_en_echec": sorted(str(row.get("task_id")) for row in en_echec)[:20]},
                         ensure_ascii=False))
        return 0
    bilan = revalider(root, timeout_s=args.timeout_s, reprendre=args.reprendre)
    print(json.dumps(bilan, ensure_ascii=False, indent=1))
    return 0 if not bilan["echecs"] and not bilan.get("encore_perimes") else 3


if __name__ == "__main__":
    raise SystemExit(main())
