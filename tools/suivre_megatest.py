"""OBSERVATEUR DU MEGATEST -- a lancer dans une 2e fenetre, PENDANT que le test tourne.

STRICTEMENT EN LECTURE SEULE. Il ne touche a RIEN :
  - il n'ecrit aucun fichier
  - il ne tue aucun processus
  - il ne parle pas au reseau
Il se contente de RELIRE, toutes les 3 secondes, les fichiers que le MEGATEST ecrit
au fur et a mesure. Le fermer (Ctrl-C) n'a AUCUN effet sur le test en cours.

CE QU'IL LIT
------------
  MEGATEST.md            reecrit APRES CHAQUE SECTION -> quelles sections sont finies
  resultat-audit.md      reecrit APRES CHAQUE CONTROLE -> ou en est l'audit (le plus long)
  tools/audit_timings.json  les durees des passages PRECEDENTS -> l'ETA

POURQUOI IL EXISTE
------------------
La section "audit" ne dit rien pendant qu'elle tourne (33 controles + toute la suite
pytest avec couverture). On croit que c'est gele. Ca ne l'est pas -- c'est juste long.
Cet observateur le prouve, en montrant la progression reelle.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEGATEST_MD = ROOT / "MEGATEST.md"
AUDIT_MD = ROOT / "resultat-audit.md"
TIMINGS = ROOT / "tools" / "audit_timings.json"

RAFRAICHIR_S = 3.0

# Au-dela de ce delai sans ecriture, un fichier vient d'un passage PRECEDENT, pas du
# passage en cours. Sans ce garde-fou, l'observateur affiche fierement la progression
# d'un audit vieux de 27 heures -- et fait croire qu'un test avance alors qu'il demarre.
# C'est exactement le mensonge que ce projet traque : une donnee perimee presentee
# comme fraiche. Un fichier trop vieux n'est pas une progression : c'est un souvenir.
FRAICHEUR_MAX_S = 900.0  # 15 min

# Les 8 sections, dans l'ordre ou megatest.py les lance.
SECTIONS = [
    "Garde ASCII des .cmd",
    "Audit code + suite de tests complete",
    "Pourquoi le bot n'ouvre aucune position",
    "Seuil de funding du Grinder",
    "Carnet L2",
    "Carry delta-neutre",
    "Flux public",
    "Memoire",
]


def _age(p: Path) -> float | None:
    """Secondes depuis la derniere ecriture. None si le fichier n'existe pas."""
    try:
        return max(0.0, time.time() - p.stat().st_mtime)
    except OSError:
        return None


def _mmss(s: float) -> str:
    s = int(max(0, s))
    return f"{s // 60:2d}m{s % 60:02d}s"


def _est_frais(p: Path) -> bool:
    """Le fichier a-t-il ete ecrit RECEMMENT ? Sinon il vient d'un passage precedent.

    Deny-by-default : dans le doute (fichier absent, illisible), on repond NON.
    Mieux vaut dire "je ne sais pas" que d'afficher un souvenir comme une progression.
    """
    a = _age(p)
    return a is not None and a < FRAICHEUR_MAX_S


def _sections_finies() -> list[str]:
    """MEGATEST.md est reecrit APRES chaque section : ce qu'il contient est FINI.

    Rend [] si le fichier est PERIME : un rapport de la veille ne dit rien du
    passage en cours.
    """
    if not _est_frais(MEGATEST_MD):
        return []
    try:
        texte = MEGATEST_MD.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [s for s in SECTIONS if s.lower()[:22] in texte.lower()]


def _audit_progression() -> tuple[int, int, str]:
    """(controles faits, total attendu, dernier titre lu) depuis resultat-audit.md.

    Rend (0, 33, ...) si le fichier est PERIME -- l'audit du passage en cours n'a
    encore rien ecrit, et le vieux fichier n'est pas une progression.
    """
    if not _est_frais(AUDIT_MD):
        a = _age(AUDIT_MD)
        if a is None:
            return 0, 33, "-- pas encore commence --"
        return 0, 33, f"-- rien d'ecrit pour CE passage (le fichier date de {_mmss(a)}) --"
    try:
        lignes = AUDIT_MD.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0, 33, "-- pas encore commence --"
    titres = [l.strip() for l in lignes if l.startswith("## ")]
    dernier = titres[-1].lstrip("# ").strip()[:52] if titres else "-- demarrage --"
    return len(titres), max(33, len(titres)), dernier


def _eta_audit(faits: int, total: int, ecoule: float) -> str:
    """ETA a partir des durees du passage PRECEDENT si on les a, sinon extrapolation."""
    try:
        t = json.loads(TIMINGS.read_text(encoding="utf-8"))
        total_prec = float(sum(float(v) for v in t.values() if isinstance(v, (int, float))))
        if total_prec > 0:
            return f"~{_mmss(max(0.0, total_prec - ecoule))} restantes  (d'apres le passage precedent)"
    except (OSError, ValueError, TypeError):
        pass
    if faits >= 2 and ecoule > 5:
        par_controle = ecoule / faits
        return f"~{_mmss(par_controle * (total - faits))} restantes  (extrapolation)"
    return "ETA inconnue (premier passage)"


def main() -> int:
    debut = time.time()
    print("=" * 74)
    print("  OBSERVATEUR DU MEGATEST -- LECTURE SEULE")
    print("  Il ne touche a RIEN. Ctrl-C ici n'arrete PAS le test en cours.")
    print("=" * 74)

    try:
        while True:
            ecoule = time.time() - debut
            finies = _sections_finies()
            faits, total, dernier = _audit_progression()
            age_audit = _age(AUDIT_MD)

            os.system("cls" if os.name == "nt" else "clear")
            print("=" * 74)
            print("  OBSERVATEUR DU MEGATEST -- LECTURE SEULE  (Ctrl-C = ferme CETTE fenetre)")
            print("=" * 74)
            print(f"  Observe depuis : {_mmss(ecoule)}")
            print()

            print("  SECTIONS")
            for i, nom in enumerate(SECTIONS, 1):
                if nom in finies:
                    print(f"    [{i}/8] {nom:<42} TERMINEE")
                elif len(finies) == i - 1:
                    print(f"    [{i}/8] {nom:<42} EN COURS ...")
                else:
                    print(f"    [{i}/8] {nom:<42} en attente")
            print()

            if "Audit code + suite de tests complete" not in finies:
                print("  AUDIT (la section la plus longue : 33 controles + toute la suite pytest)")
                largeur = 40
                rempli = int(largeur * min(1.0, faits / max(1, total)))
                barre = "#" * rempli + "." * (largeur - rempli)
                print(f"    [{barre}]  {faits}/{total} controles")
                print(f"    en cours : {dernier}")
                print(f"    {_eta_audit(faits, total, ecoule)}")
                if _est_frais(AUDIT_MD):
                    etat = "il ecrit -> il travaille" if (age_audit or 0) < 120 else "silencieux (pytest tourne sans doute : il n'ecrit qu'a la fin)"
                    print(f"    resultat-audit.md ecrit il y a {_mmss(age_audit or 0)}  ({etat})")
                elif age_audit is None:
                    print("    resultat-audit.md pas encore cree (le 1er controle n'est pas fini)")
                else:
                    print(f"    resultat-audit.md date de {_mmss(age_audit)} -> PASSAGE PRECEDENT, pas celui-ci.")
                    print("    L'audit en cours n'a encore RIEN ecrit. C'est normal au demarrage.")
                print()

            print("  RAPPEL : MEGATEST.md et resultat-audit.md sont reecrits au fur et a mesure.")
            print("           Meme si tu fais Ctrl-C dans l'autre fenetre, RIEN n'est perdu.")
            time.sleep(RAFRAICHIR_S)
    except KeyboardInterrupt:
        print("\n  Observateur ferme. Le MEGATEST, lui, continue.")
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
