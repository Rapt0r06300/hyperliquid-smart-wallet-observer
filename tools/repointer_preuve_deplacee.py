r"""Repointer un fichier de preuve DEPLACE, et seulement si le test le lit vraiment.

LE CAS QUI MOTIVE CET OUTIL (22/11/2026). Neuf recus -- `ASF-113` a `ASF-120` et `ASF-RIG-019`
-- epinglaient `POUSSER-GITHUB-FORCE.cmd`, supprime le 18/11 par le commit b44aac91 intitule
« lanceur: POUSSER-GITHUB, sans le FORCE qu'il ne fait pas ». Le lanceur annoncait un push force
qu'il n'executait pas : **sa suppression etait une correction de veracite**, et le recreer serait
une regression.

Leurs tests passent (32 verts) et le rejeu rend 0. Seule l'empreinte etait incalculable, d'ou
l'etat `EVIDENCE_FILE_ABSENT`. Et la liste epinglee etait simplement PERIMEE : le test cite
(`tests/test_asf_113_120_launchers_copy_vault.py:15`) lit `ROOT / "POUSSER-GITHUB.cmd"`, le
successeur. Repointer est donc une correction FACTUELLE.

CE QUE CET OUTIL REFUSE DE FAIRE, et c'est l'essentiel :

1. il ne repointe RIEN si l'ancien chemin existe encore sur le disque -- on ne « deplace » pas
   une preuve qui est la ;
2. il ne repointe RIEN si le nouveau chemin est absent ;
3. il ne repointe RIEN si les FICHIERS DE TEST du recu ne mentionnent pas le nouveau chemin.
   C'est la garde qui empeche un repointage arbitraire : la preuve doit suivre ce que le test
   LIT, pas ce qui arrangerait le decompte ;
4. il **ne decerne jamais la preuve lui-meme**. Il corrige la liste et laisse le verdict tel
   quel. Seul `revalider_receipts.py` peut rendre un recu `VERIFIED_DONE`, et seulement par le
   chemin prevu : rejouer les tests, obtenir le code 0, recalculer les empreintes.

Le registre est APPEND-ONLY : on ajoute une ligne corrigee, on n'en modifie aucune.

PAPER / lecture seule sauf l'ajout au registre.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

from revalider_receipts import (  # noqa: E402
    BACKUPS,
    RECEIPTS,
    fichiers_de_test,
    recus_a_reprendre,
)


def _mentionne(nouveau: str, tests: tuple[str, ...], racine: Path) -> bool:
    """Un fichier de test du recu cite-t-il le nouveau chemin ?

    On compare sur le NOM de base : un test ecrit `ROOT / "POUSSER-GITHUB.cmd"`, pas le chemin
    relatif complet. Lire le fichier plutot que supposer : c'est la difference entre une
    correction factuelle et un repointage de confort.
    """
    cible = Path(nouveau).name
    for relatif in tests:
        chemin = racine / relatif
        if not chemin.is_file():
            continue
        if cible in chemin.read_text(encoding="utf-8", errors="replace"):
            return True
    return False


def examiner(racine: Path, *, de: str, vers: str) -> dict:
    """Ce qui serait repointe, et pourquoi -- sans rien ecrire."""
    racine = racine.resolve()
    motifs: list[str] = []
    if (racine / de).exists():
        motifs.append(f"REFUS : l'ancien chemin existe encore ({de}) — rien n'a ete deplace")
    if not (racine / vers).is_file():
        motifs.append(f"REFUS : le nouveau chemin est absent ({vers})")
    if motifs:
        return {"verdict": "REFUSE", "motifs": motifs, "recus": []}

    retenus: list[dict] = []
    ignores: list[dict] = []
    for row in recus_a_reprendre(racine / RECEIPTS, racine):
        files = [str(f) for f in (row.get("files") or [])]
        if de not in files:
            continue
        tests = fichiers_de_test(str(row.get("command") or ""), racine)
        if not _mentionne(vers, tests, racine):
            ignores.append({"task_id": row.get("task_id"),
                            "pourquoi": f"aucun test du recu ne cite {Path(vers).name}"})
            continue
        retenus.append(row)
    return {
        "verdict": "REPOINTABLE" if retenus else "RIEN_A_REPOINTER",
        "motifs": motifs,
        "recus": [str(r.get("task_id")) for r in retenus],
        "ignores": ignores,
        "lignes": retenus,
    }


def repointer(racine: Path, *, de: str, vers: str, appliquer: bool = False) -> dict:
    racine = racine.resolve()
    bilan = examiner(racine, de=de, vers=vers)
    bilan.pop("lignes", None)
    if not appliquer or bilan["verdict"] != "REPOINTABLE":
        bilan["ecrit"] = 0
        return bilan

    detail = examiner(racine, de=de, vers=vers)["lignes"]
    registre = racine / RECEIPTS
    horodatage = datetime.now(UTC).isoformat()
    sauvegarde = racine / BACKUPS / (
        "receipts_repointage_" + horodatage.replace(":", "").replace("-", "")[:15] + ".jsonl")
    sauvegarde.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(registre, sauvegarde)

    with registre.open("a", encoding="utf-8") as flux:
        for row in detail:
            nouveau = dict(row)
            nouveau["files"] = [vers if str(f) == de else str(f)
                                for f in (row.get("files") or [])]
            # Le verdict NE BOUGE PAS : seul `revalider_receipts` peut rendre une preuve, et
            # seulement en rejouant les tests. Ici on corrige une liste perimee, rien de plus.
            nouveau["repointage"] = {
                "de": de, "vers": vers, "quand_utc": horodatage,
                "pourquoi": ("l'ancien chemin a ete supprime du depot ; le test cite par ce recu "
                             f"lit {Path(vers).name}"),
            }
            flux.write(json.dumps(nouveau, ensure_ascii=False) + "\n")
    bilan["ecrit"] = len(detail)
    bilan["sauvegarde"] = str(sauvegarde.relative_to(racine).as_posix())
    bilan["ensuite"] = ("lancer `tools/revalider_receipts.py --reprendre` : c'est LUI qui "
                        "rejoue les tests et decerne la preuve, pas cet outil")
    return bilan


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--racine", default=str(RACINE))
    p.add_argument("--de", required=True, help="chemin de preuve disparu")
    p.add_argument("--vers", required=True, help="son successeur, present sur le disque")
    p.add_argument("--appliquer", action="store_true",
                   help="sans ce drapeau, on examine et on n'ecrit rien")
    args = p.parse_args(argv)
    bilan = repointer(Path(args.racine), de=args.de, vers=args.vers, appliquer=args.appliquer)
    print(json.dumps(bilan, ensure_ascii=False, indent=1))
    return 0 if bilan["verdict"] in {"REPOINTABLE", "RIEN_A_REPOINTER"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
