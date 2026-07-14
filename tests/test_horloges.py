"""#318 / P2-6 — LES HORLOGES : la fraicheur ne doit plus etre FABRIQUEE (2026-07-13).

`signal_age` est **la porte qui autorise les entrees**. Elle mentait de deux facons :

  1. le « maintenant » etait calcule **a partir des donnees** -> l'age du signal le plus recent
     valait **ZERO par construction**, et il **GELAIT** quand le flux de prix calait (ce qui est
     arrive DEUX fois : 02:32 et 04:08) ;
  2. `leader_exchange_ts or observed_at_ms` melangeait **deux horloges** dans un seul champ.

Les tests ci-dessous REPRODUISENT les deux bugs sur des donnees fabriquees, et exigent un REFUS.

Aucun ordre reel.
"""
from __future__ import annotations

import pytest

from hl_observer.freshness.horloges import (
    AGE_OK,
    ECART_HORLOGE_MAX_MS,
    MOTIF_DOMAINES_MELANGES,
    MOTIF_HORLOGE_INCONNUE,
    MOTIF_NOW_ANTERIEUR,
    MOTIF_NOW_DERIVE_DES_DONNEES,
    age,
    age_du_signal,
    ecart_horloges,
    exchange,
    horloges_coherentes,
    inconnu,
    local,
    maintenant_est_derive_des_donnees,
)


# ============================================================ le cas nominal


def test_un_age_dans_UN_SEUL_domaine_se_calcule_normalement():
    a = age(local(1_000_000), local(1_003_500))
    assert a.connu is True
    assert a.ms == pytest.approx(3_500.0)
    assert a.motif == AGE_OK


# ============================================================ 🔴 BUG 1 : le « maintenant » tautologique


def test_un_MAINTENANT_derive_des_DONNEES_est_REFUSE():
    """🔴 LE BUG EXACT DE `fusion_runtime` :

        context_now_ms = max(... + [v.observed_at_ms for v in leader_votes])
        signal_age_ms  = context_now_ms - last_vote_ms

    Si le vote gagnant est le plus recent, `context_now == last_vote` -> **age = 0**.
    Le signal definit lui-meme l'instant present. *Ce n'est pas une mesure, c'est une tautologie.*
    """
    votes = [1_000_000, 1_005_000, 1_009_000]      # le plus recent gagne
    faux_maintenant = max(votes)                    # <-- exactement ce que faisait le code
    a = age_du_signal(
        observe_a_ms=1_009_000,
        maintenant_local_ms=faux_maintenant,
        horodatages_du_lot=votes,
    )
    assert a.connu is False, (
        "l'age a ete calcule sur un « maintenant » qui vient des donnees : il vaut 0 par "
        "construction, et il autorise l'entree."
    )
    assert a.motif == MOTIF_NOW_DERIVE_DES_DONNEES


def test_une_VRAIE_horloge_est_STRICTEMENT_posterieure_donc_acceptee():
    """Une horloge reelle est toujours au moins un peu apres la derniere donnee (ne serait-ce que
    du temps de traitement). C'est ce qui la distingue d'un `max()` sur les donnees."""
    votes = [1_000_000, 1_009_000]
    a = age_du_signal(
        observe_a_ms=1_009_000,
        maintenant_local_ms=1_009_042,             # une vraie montre : +42 ms
        horodatages_du_lot=votes,
    )
    assert a.connu is True
    assert a.ms == pytest.approx(42.0)


def test_le_FLUX_QUI_CALE_ne_doit_PAS_geler_l_age():
    """🔴 LE SCENARIO QUI NOUS EST ARRIVE DEUX FOIS (stalls 02:32 et 04:08).

    Le flux de prix s'arrete. L'ancien code prenait `max(donnees)` comme « maintenant » :
    **le maintenant GELE avec les donnees**, et un signal vieux de 10 minutes reste
    eternellement « frais ». Le bot entrait.

    Avec une vraie horloge, l'age **GRANDIT** -- et le gate de fraicheur refuse.
    """
    dernier_signal = 1_000_000
    donnees_gelees = [dernier_signal]               # plus rien n'arrive

    # ANCIEN comportement (reproduit) : maintenant = max(donnees) -> age 0, pour toujours.
    assert maintenant_est_derive_des_donnees(max(donnees_gelees), donnees_gelees) is True

    # NOUVEAU : la vraie montre avance, meme si les donnees ne bougent plus.
    dix_minutes_plus_tard = dernier_signal + 600_000
    a = age_du_signal(
        observe_a_ms=dernier_signal,
        maintenant_local_ms=dix_minutes_plus_tard,
        horodatages_du_lot=donnees_gelees,
    )
    assert a.connu is True
    assert a.ms == pytest.approx(600_000.0), "l'age doit GRANDIR quand le flux cale"


# ============================================================ 🔴 BUG 2 : deux horloges melangees


def test_un_age_entre_DEUX_HORLOGES_DIFFERENTES_est_REFUSE():
    """🔴 `source_ts_ms = leader_exchange_ts or observed_at_ms`.

    Ce champ contient **soit** l'heure de Hyperliquid, **soit** la notre. En soustraire une de
    l'autre donne un nombre... qui ne veut rien dire. Et ce nombre autorisait des entrees.
    """
    a = age(exchange(1_000_000), local(1_003_000))
    assert a.connu is False
    assert a.motif == MOTIF_DOMAINES_MELANGES


def test_un_horodatage_de_DOMAINE_INCONNU_est_REFUSE():
    """Le `or` produisait exactement ca : un horodatage orphelin de son referentiel."""
    a = age(inconnu(1_000_000), local(1_003_000))
    assert a.connu is False
    assert a.motif == MOTIF_HORLOGE_INCONNUE


# ============================================================ l'incoherence ne devient PAS « frais »


def test_un_MAINTENANT_ANTERIEUR_a_l_observation_est_REFUSE_pas_ramene_a_zero():
    """🚩 L'ANCIEN CODE FAISAIT `max(0, context_now - last_vote)`.

    Autrement dit : quand les horloges etaient INCOHERENTES (decalage, rejeu de snapshot), il
    transformait l'incoherence en **« parfaitement frais »**. Le pire des deux mondes : un bug
    silencieux qui ouvre la porte au lieu de la fermer.

    *Un `max(0, ...)` sur un temps n'est pas une protection : c'est un tapis sous lequel on
    balaie une contradiction.*
    """
    a = age(local(1_005_000), local(1_000_000))     # « maintenant » AVANT l'observation
    assert a.connu is False, "une incoherence d'horloge a ete transformee en age nul (= frais)"
    assert a.motif == MOTIF_NOW_ANTERIEUR


# ============================================================ l'ecart entre les deux montres


def test_l_ecart_des_horloges_se_MESURE_et_se_REFUSE_au_dela_du_seuil():
    assert ecart_horloges(1_000_500, 1_000_000) == pytest.approx(500.0)
    assert horloges_coherentes(1_000_500, 1_000_000) is True
    assert horloges_coherentes(1_000_000 + int(ECART_HORLOGE_MAX_MS) + 1, 1_000_000) is False


def test_un_age_NON_CONNU_ne_vaut_JAMAIS_zero():
    """DENY-BY-DEFAULT. `None`, jamais un `0.0` rassurant : un age de 0 dit « ultra-frais »,
    et c'est le mensonge le plus dangereux qu'on puisse afficher a la porte d'entree."""
    for a in (
        age(exchange(1), local(2)),
        age(inconnu(1), local(2)),
        age(local(5), local(1)),
        age_du_signal(observe_a_ms=9, maintenant_local_ms=9, horodatages_du_lot=[9]),
    ):
        assert a.ms is None
        assert a.connu is False
