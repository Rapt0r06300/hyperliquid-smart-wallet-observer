"""Fenetres temporelles causales du Copy-Vault : ancres utiles et fenetre apres signal.

EXTRAIT DE copy_vault_coffre_vers_labo.py LE 21/11/2026. Ce module depassait son plafond
de 800 lignes (809), et l'invariant #13 du depot refuse qu'un fichier grossisse au-dela :
un fichier plus gros que le plafond devient intouchable (il se fait tronquer a l'edition).
La regle du depot est d'EXTRAIRE, jamais de relever le plafond.

Ces deux fonctions forment une feuille : elles ne dependent d'AUCUN autre nom du module
d'origine (mesure avant de deplacer), uniquement de Sequence. Elles repondent toutes deux
a la meme question -- quelle tranche de temps a le droit d'etre lue apres un signal --
donc les regrouper n'invente pas une architecture parallele, elle nomme ce qui existait.
"""
from __future__ import annotations

from collections.abc import Sequence



def _fenetre_apres_signal() -> int:
    """Combien de temps APRES un signal un carnet peut encore servir.

    DEFAUT QUE CECI CORRIGE (18/11/2026). Le replay cherche TROIS carnets par signal :

      * `reference` : le dernier carnet au plus tard AU signal ;
      * `entry`     : le premier carnet a partir de `signal + COPY_DELAY_MS` ;
      * `exit_book` : le premier carnet a partir de `entree + horizon_ms`.

    Ne garder que les carnets des `MAX_BOOK_AGE_MS` PRECEDANT le signal -- ce que faisait la
    premiere version de ce filtre -- jette donc les carnets d'entree et de sortie. Resultat mesure
    sur 4 000 signaux : **zero trade**, avec 3 188 `STALE_OR_MISSING_ENTRY_BOOK` et 724
    `STALE_OR_MISSING_REFERENCE_BOOK`. Les carnets etaient la (703 664 sur 200 coins) ; c'est la
    fenetre qui etait du mauvais cote.

    J'avais ecrit moi-meme, dans le commentaire de `carnets_utiles`, qu'une fenetre trop ETROITE
    ferait disparaitre des signaux sans que personne le voie. Je l'avais calibree sur l'alignement,
    qui ne regarde que le passe, et pas sur le replay, qui regarde aussi l'avenir.
    """
    from hl_observer.backtesting import copy_vault_executable as cv
    from hl_observer.backtesting.copy_vault_local_lab import _PARAMETER_DOMAINS

    horizon = max(dict(_PARAMETER_DOMAINS)["horizon_ms"])
    return int(cv.COPY_DELAY_MS) + int(horizon) + int(cv.MAX_TARGET_LAG_MS)

def ancres_utiles(
    instants: Sequence[int], *, delai_ms: int, horizons_ms: Sequence[int], pas_ms: int
) -> list[int]:
    """Les instants OU un carnet sert vraiment au replay, pour une suite de signaux d'un coin.

    DEFAUT QUE CECI CORRIGE (19/11/2026). La version precedente gardait « les premiers carnets de
    chaque fenetre », avec un plafond de 240 par signal, en expliquant qu'ils etaient « les plus
    proches des instants cibles ». C'etait faux : les premiers d'une fenetre sont les plus proches
    de son DEBUT, donc du carnet de reference -- et le carnet de SORTIE, a une heure de la, etait
    systematiquement jete. Mesure sur la tranche t001 : SOL, TIA, XMR, ZEC et XRP portaient
    exactement 240 carnets couvrant 40,9 minutes d'une fenetre de 240, sur une connexion unique et
    sans la moindre coupure reelle. Le plafond, pose pour la memoire, detruisait la mesure.

    Le replay cherche trois instants par signal : `t` (reference), `t + delai` (entree) et
    `t + delai + horizon` (sortie) -- pour CHACUN des horizons que le labo explore, puisqu'il les
    cherche. On garde donc des carnets autour de ces instants-la, et de nulle part ailleurs.

    `pas_ms` quantifie les ancres : deux instants separes de moins d'un pas n'ont pas besoin de
    deux carnets, puisque le meme carnet repond pour les deux. C'est ce qui empeche le budget de
    croitre avec le nombre de signaux voisins.
    """
    exactes: set[int] = set()
    crans: set[int] = set()
    pas = max(1, int(pas_ms))
    for brut in instants:
        t = int(brut)
        # LA REFERENCE ET L'ENTREE NE SE QUANTIFIENT PAS.
        #
        # Premiere version : tout etait arrondi au cran inferieur. L'ancre de reference tombait
        # donc jusqu'a un pas AVANT le signal, et le carnet garde de son cote passe pouvait se
        # trouver a `pas + fenetre` du signal -- 45 s pour un pas de 15 s. Le replay, qui exige une
        # reference a `max_reference_lag_ms` pres, refusait alors : mesure du 19/11/2026,
        # `STALE_OR_MISSING_REFERENCE_BOOK` sur 418 candidats de VALIDATION sur 418 et 623 sur 636
        # en OOS. Ces deux instants sont connus exactement, et ils decident de l'episode : on les
        # garde tels quels.
        exactes.add(t)
        exactes.add(t + int(delai_ms))
        # Les sorties, elles, se quantifient sans dommage : leur cible depend de l'horizon cherche
        # ET de l'instant d'entree reel, donc elle est deja approximative a quelques secondes.
        # C'est ce qui empeche le budget de croitre avec le nombre de signaux voisins.
        for horizon in horizons_ms:
            crans.add((t + int(delai_ms) + int(horizon)) // pas)
    return sorted(exactes | {cran * pas for cran in crans})
