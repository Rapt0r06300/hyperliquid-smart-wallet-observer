"""LE REGISTRE DES FLAGS -- reconstruit sur la source de verite de T3 (2026-07-12).

Sortie : docs/CONFIG_FLAGS.md. Lecture seule, aucun ordre.

POURQUOI CE FICHIER A ETE REECRIT
---------------------------------
L'ancienne version avait TROIS bugs, et ils se renforcaient :

  1. **Elle ne lisait QU'UN lanceur** : `LANCER_HYPERSMART.cmd`. Or les flags sont poses dans
     `tools/start_hypersmart_simulation.ps1`, que ce .cmd appelle. Le generateur regardait a
     cote et concluait « pose par personne » -- avec assurance.
  2. **Elle comptait une simple MENTION du nom comme une lecture.** Un flag cite dans un
     commentaire comptait comme un consommateur.
  3. **Elle scannait les `.ps1` et `.cmd` comme du "code".** Un flag seulement POSE dans le
     lanceur y comptait donc comme LU par le code.

Resultat mesure : **11 flags etiquetes `code-only`** (= « le lanceur ne le pose pas ») alors
que le lanceur les pose bel et bien. Dont `HYPERSMART_EXTERNAL_PROFILES_SCOPE` -- le bus GitHub.

C'est exactement la maladie du projet : **un outil qui regarde au mauvais endroit, ne trouve
rien, et le rapporte comme une absence.** Une doc qui ment sur l'etat des interrupteurs est
pire que pas de doc : c'est comme ca qu'on croit une capacite eteinte alors qu'elle tourne.

CE QU'ELLE FAIT MAINTENANT
--------------------------
Elle delegue a `hl_observer.audit.cablage`, qui distingue TROIS choses differentes que
l'ancienne version melangeait :

    LU par le code       -> `flags_lus()`   : AST, os.environ.get/getenv, hors tests
    POSE par un lanceur  -> `flags_poses()` : cmd, PowerShell (LES DEUX syntaxes), sh, yaml
    MORT                 -> lu avec un defaut ETEINT, et pose par PERSONNE

Une seule source de verite, deja couverte par 21 tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hl_observer.audit.cablage import auditer_les_interrupteurs  # noqa: E402

OUT = ROOT / "docs" / "CONFIG_FLAGS.md"
PREFIXES = ("HYPERSMART_", "HL_", "V26_", "V27_")
IGNORE = ("__pycache__", "runtime/", "data/", "_archive", "cli_pkg_DISABLED")


def _lire(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _collecter(motifs: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for motif in motifs:
        for p in ROOT.glob(motif):
            rel = p.relative_to(ROOT).as_posix()
            if any(x in rel for x in IGNORE):
                continue
            out[rel] = _lire(p)
    return out


def build_markdown(inters: list) -> str:
    morts = [i for i in inters if i.mort]
    ambigus = [i for i in inters if i.ambigu]
    orphelins = [i for i in inters if i.pose_par and not i.lu_par]

    lignes = [
        "# Registre des flags de configuration (auto-genere)",
        "",
        "> Genere par `python tools/gen_config_flags.py`, sur la meme source de verite que",
        "> `T3-CABLAGE.cmd` (`hl_observer.audit.cablage`). **Ne pas editer a la main.**",
        "",
        "Trois choses DIFFERENTES, qu'une ancienne version de ce generateur confondait :",
        "",
        "- **lu** : le code appelle `os.environ.get(...)` dessus (AST, hors tests) ;",
        "- **pose** : un lanceur lui donne une valeur (`.cmd`, `.ps1` **dans ses deux syntaxes**,",
        "  `.sh`, `.yaml`) ;",
        "- **MORT** : lu avec un defaut ETEINT (`0`/`false`/`no`/`off`) et pose par **personne**",
        "  -> la capacite existe, elle est cablee, et elle ne s'allumera **jamais**, sans un log.",
        "",
        "| statut | nb |",
        "|---|---:|",
        "| flags a nous | %d |" % len(inters),
        "| **MORTS** (capacite eteinte en silence) | **%d** |" % len(morts),
        "| ambigus (defaut vide : « aucune limite » ou « eteint » ? on ne tranche pas) | %d |" % len(ambigus),
        "| poses par un lanceur mais lus par personne (flag orphelin) | %d |" % len(orphelins),
        "",
    ]

    if morts:
        lignes += ["## 🔴 Interrupteurs MORTS", "",
                   "Lus par le code, defaut eteint, poses par aucun lanceur.", ""]
        for i in morts:
            lignes.append("- `%s` (defaut `%r`) -- lu par %s" % (i.nom, i.defaut, ", ".join(i.lu_par)))
        lignes.append("")

    if orphelins:
        lignes += ["## ⚠️ Flags poses au lanceur mais lus par PERSONNE", "",
                   "Un reglage qui ne regle rien. A retirer du lanceur, ou a brancher.", ""]
        for i in orphelins:
            lignes.append("- `%s` -- pose par %s" % (i.nom, ", ".join(i.pose_par)))
        lignes.append("")

    if ambigus:
        lignes += ["## À lire à la main (defaut vide)", ""]
        for i in ambigus:
            lignes.append("- `%s` -- lu par %s" % (i.nom, ", ".join(i.lu_par)))
        lignes.append("")

    lignes += ["## Tous les flags", "",
               "| Flag | defaut | lu par | pose par | statut |",
               "|---|---|---:|---|---|"]
    for i in sorted(inters, key=lambda x: x.nom):
        if i.mort:
            statut = "🔴 MORT"
        elif i.ambigu:
            statut = "à verifier"
        elif i.pose_par and not i.lu_par:
            statut = "⚠️ pose, jamais lu"
        elif i.pose_par:
            statut = "pose au lanceur"
        else:
            statut = "defaut du code"
        lignes.append("| `%s` | `%s` | %d | %s | %s |"
                      % (i.nom, i.defaut if i.defaut is not None else "-",
                         len(i.lu_par),
                         ", ".join(Path(p).name for p in i.pose_par) or "-",
                         statut))
    return "\n".join(lignes) + "\n"


def main() -> int:
    py = _collecter(("src/**/*.py", "hyper_smart_observer/**/*.py", "tests/**/*.py"))
    lanceurs = _collecter(("*.cmd", "*.ps1", "*.sh",
                           "tools/**/*.cmd", "tools/**/*.ps1", "tools/**/*.sh",
                           "config/**/*.yaml", "config/**/*.yml"))

    inters = auditer_les_interrupteurs(py, lanceurs, prefixes=PREFIXES)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build_markdown(inters), encoding="utf-8")

    morts = [i for i in inters if i.mort]
    orph = [i for i in inters if i.pose_par and not i.lu_par]
    print("ecrit %s" % OUT.relative_to(ROOT))
    print("  %d flags | %d MORTS | %d poses mais jamais lus"
          % (len(inters), len(morts), len(orph)))
    for i in morts:
        print("    MORT : %s (defaut %r)" % (i.nom, i.defaut))
    for i in orph:
        print("    POSE MAIS JAMAIS LU : %s (%s)" % (i.nom, ", ".join(i.pose_par)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
