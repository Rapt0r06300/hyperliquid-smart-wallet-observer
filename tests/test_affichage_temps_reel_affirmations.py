"""L'écran unique affirmait deux choses qu'il ne sait pas.

MESURE DU 22/11/2026, dans `tools/affichage_temps_reel.py` — l'écran que l'opérateur regarde
PENDANT la collecte, donc celui où une fausse réassurance coûte le plus cher.

**1. « ACTIF » pour un fichier de verrou.**

    sup = (data_dir / "collecteurs.lock").exists()
    print(f"  Superviseur: {_et(sup)}  ...")     # _et(True) -> "ACTIF "

Un verrou PRÉSENT n'est pas un processus VIVANT : un arrêt brutal le laisse derrière lui. Tout
le travail de cette nuit sur le lanceur reposait sur cette distinction (identité vérifiée avant
tout arrêt, et `tools/etat_collecte_reel.py` qui nomme l'état
`PROCESSUS_VIVANTS_MAIS_AUCUNE_DONNEE_FRAICHE`). L'écran, lui, disait « ACTIF » sur l'existence
d'un fichier.

**2. « en attente de données » sans regarder si quelque chose collecte.**

    if vides:
        print(f"    (+ {vides} flux encore vides, en attente de donnees)")

« En attente » promet que la donnée va venir. Si aucun collecteur ne tourne, rien ne viendra —
et c'est exactement l'état du poste quand les collecteurs sont éteints sur consigne.

Les deux corrections ne mesurent RIEN de plus : elles disent seulement ce qui est déjà observé.

⚠️ **CE QUE CES TESTS NE COUVRENT PAS, et il faut le dire.** Ils exercent les deux fonctions
PURES (`_et`, `ligne_flux_vides`). Le CÂBLAGE dans `boucle()` —
`ligne_flux_vides(vides, un_collecteur_au_moins=any((sup, poll, expl)))` — n'est pas couvert :
remplacer cet argument par `True` laisse ces cinq tests verts (injection vérifiée le
22/11/2026). Exercer `boucle()` demanderait un faux terminal et un écran effacé à chaque frame,
pour un gain faible.

Le risque est réduit autrement, par construction plutôt que par test : `sup`, `poll` et `expl`
sont lus UNE fois et servent à la fois à l'en-tête et à cette ligne. Un en-tête disant
« aucun verrou » trois fois à côté d'un « en attente de données » serait donc visible à l'œil
sur l'écran lui-même. C'est une garantie plus faible qu'un test, et c'est pourquoi elle est
écrite ici au lieu d'être passée sous silence.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _chemin in (ROOT / "src", ROOT / "tools"):
    if str(_chemin) not in sys.path:
        sys.path.insert(0, str(_chemin))

import affichage_temps_reel as A  # noqa: E402


def test_un_verrou_present_ne_se_dit_pas_ACTIF() -> None:
    """Ce que la fonction observe est un FICHIER, et l'étiquette doit le dire."""
    presente = A._et(True)
    assert "ACTIF" not in presente.upper(), (
        "un verrou present n'est pas un processus vivant : un arret brutal le laisse derriere lui")
    assert "verrou" in presente.casefold() or "present" in presente.casefold(), presente


def test_un_verrou_absent_reste_lisible() -> None:
    absent = A._et(False)
    assert absent.strip(), "l'absence doit s'afficher, pas se taire"
    assert absent != A._et(True), "les deux etats doivent se distinguer"


def test_sans_aucun_collecteur_les_flux_vides_NATTENDENT_rien() -> None:
    """« En attente » est une promesse : interdite quand rien ne collecte."""
    ligne = A.ligne_flux_vides(3, un_collecteur_au_moins=False)
    assert "attente" not in ligne.casefold(), ligne
    assert "3" in ligne
    assert "aucun" in ligne.casefold() or "rien" in ligne.casefold(), ligne


def test_avec_un_collecteur_lattente_redevient_vraie() -> None:
    ligne = A.ligne_flux_vides(3, un_collecteur_au_moins=True)
    assert "attente" in ligne.casefold(), ligne
    assert "3" in ligne


def test_aucun_flux_vide_ne_produit_aucune_ligne() -> None:
    assert A.ligne_flux_vides(0, un_collecteur_au_moins=True) == ""
    assert A.ligne_flux_vides(0, un_collecteur_au_moins=False) == ""
