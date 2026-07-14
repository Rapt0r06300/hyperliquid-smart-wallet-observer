"""#597 -- LA PORTE QUE L'AUDIT NE VOYAIT PAS : LES OUTILS DE RECHERCHE.

Le cliquet de cablage a rougi : 304 morts pour un plafond de 303. Le reflexe serait de
relever le plafond. C'est EXACTEMENT ce qu'un cliquet interdit -- alors on va voir pourquoi.

Et dans la liste des « morts », on trouve `hl_observer.backtesting.scenario_search` : le moteur
qui a evalue 150 M de scenarios, lance des dizaines de fois. Le declarer mort est un MENSONGE.

Cause : les lanceurs ne demarrent pas la recherche par `python -m hl_observer.X` (la seule
forme que l'audit connaissait), mais par `python tools\\xxx.py`.

Cet outil mesure, cote a cote, l'ANCIENNE definition et la NOUVELLE -- avec le MEME perimetre
que la fixture du test, sinon on compare des choux et des carottes.

Aucun ordre reel. Lecture de fichiers uniquement.
"""

from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.audit.cablage import (  # noqa: E402
    auditer_les_modules,
    outils_demarres_par_les_lanceurs,
    portes_ouvertes_par_les_outils,
)

# ⚠️ MEME PERIMETRE QUE tests/test_risk_guards_no_limbo.py -- sinon les chiffres ne sont pas
# comparables au plafond, et on reposerait un plafond FAUX.
MOTIFS_CODE = ("src/**/*.py", "hyper_smart_observer/**/*.py", "tests/**/*.py")
MOTIFS_LANCEURS = ("*.cmd", "*.ps1", "*.sh", "tools/**/*.ps1", "tools/**/*.cmd")
MOTIFS_OUTILS = ("tools/**/*.py",)


def _sources(motifs: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for motif in motifs:
        for p in RACINE.glob(motif):
            rel = p.relative_to(RACINE).as_posix()
            if "__pycache__" in rel:
                continue
            try:
                out[rel] = p.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                continue
    return out


def main() -> int:
    code = _sources(MOTIFS_CODE)
    lanceurs = _sources(MOTIFS_LANCEURS)
    outils = _sources(MOTIFS_OUTILS)

    print("perimetre : %d fichiers de code, %d lanceurs, %d outils"
          % (len(code), len(lanceurs), len(outils)))
    print()

    demarres = outils_demarres_par_les_lanceurs(lanceurs)
    print("--- OUTILS reellement demarres par un lanceur (`python tools\\x.py`) : %d ---"
          % len(demarres))
    for c in demarres:
        marque = " " if c in outils else "?"   # '?' = cite par un .cmd mais absent du disque
        print("  %s %s" % (marque, c))
    print()

    graines = portes_ouvertes_par_les_outils(lanceurs, outils)
    print("--- GRAINES : modules hl_observer.* importes par ces outils : %d ---" % len(graines))
    for g in graines[:25]:
        print("    %s" % g)
    if len(graines) > 25:
        print("    ... (+%d)" % (len(graines) - 25))
    print()

    avant = auditer_les_modules(code, lanceurs=lanceurs)
    apres = auditer_les_modules(code, lanceurs=lanceurs, outils=outils)

    print("=================== LE CHIFFRE ===================")
    print("                         AVANT (#597)   APRES")
    print("  testes-non-branches :  %6d          %6d   (plafond actuel 303)"
          % (len(avant.testes_non_branches), len(apres.testes_non_branches)))
    print("  orphelins           :  %6d          %6d   (plafond actuel 104)"
          % (len(avant.orphelins), len(apres.orphelins)))
    print("  OUTILLES (recherche):  %6d          %6d"
          % (len(avant.outilles), len(apres.outilles)))
    print("  fiable              :  %6s          %6s" % (avant.fiable, apres.fiable))
    print()

    cible = "hl_observer.backtesting.scenario_search"
    etat_avant = ("MORT" if cible in set(avant.testes_non_branches) | set(avant.orphelins)
                  else "vivant")
    etat_apres = ("OUTILLE" if cible in apres.outilles
                  else "MORT" if cible in set(apres.testes_non_branches) | set(apres.orphelins)
                  else "vivant")
    print("--- LA PREUVE QUE LE CORRECTIF N'EST PAS COSMETIQUE ---")
    print("  %s : %s  ->  %s" % (cible, etat_avant, etat_apres))
    print()

    print("--- les 3 modules AJOUTES le 13/07 (ceux qui ont fait rougir le cliquet) ---")
    for m in ("hl_observer.backtesting.regime_label",
              "hl_observer.backtesting.regime_wiring",
              "hl_observer.audit.couverture"):
        if m in apres.outilles:
            etat = "OUTILLE (porte de recherche)"
        elif m in apres.testes_non_branches:
            etat = "MORT (teste, non branche)"
        elif m in apres.orphelins:
            etat = "ORPHELIN"
        else:
            etat = "vivant (chemin de production)"
        print("  %-45s %s" % (m.rsplit(".", 1)[-1], etat))
    print()

    # ⚠️ LE POINT QUI EMPECHE CE CORRECTIF D'ETRE UN AFFAIBLISSEMENT :
    # un garde-fou de risk/ (ou paper_trading/ ou exits/) joignable UNIQUEMENT depuis un
    # script d'audit ne protege AUCUNE position. Il doit continuer a compter comme MORT.
    prod = [m for m in apres.outilles
            if m.startswith(("hl_observer.risk.", "hl_observer.paper_trading.",
                             "hl_observer.exits."))]
    print("--- garde-fous de PRODUCTION qui ne survivraient que par un OUTIL : %d ---" % len(prod))
    for m in prod:
        print("  !!! %s" % m)
    if not prod:
        print("  (aucun -- le correctif ne blanchit AUCUN garde-fou du chemin de production)")
    print()

    print("--- NOUVEAUX PLAFONDS A POSER (une seule fois, avec la raison ecrite) ---")
    print("  PLAFOND_MORTS_GLOBAL     = %d" % len(apres.testes_non_branches))
    print("  PLAFOND_ORPHELINS_GLOBAL = %d" % len(apres.orphelins))
    print("  (les OUTILLES ne sont pas plafonnes : ajouter de la CAPACITE DE RECHERCHE qu'on")
    print("   LANCE vraiment est legitime. Ce qui ne doit pas croitre, c'est le code que")
    print("   PERSONNE n'atteint.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
