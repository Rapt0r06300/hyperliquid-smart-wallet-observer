"""[LAB α item 15] Rafraîchissement périodique du dashboard, même pendant une opération bloquante.
Boucle PURE testée sans temps réel + contexte thread réel (borné). 0 réseau.
"""
from __future__ import annotations

import threading
import time

from hl_observer.ops.rafraichisseur import boucler_rafraichissement, RafraichisseurPeriodique


def test_boucle_pure_appelle_le_callback_a_chaque_passe():
    appels = []
    arret = threading.Event()
    n = boucler_rafraichissement(lambda: appels.append(1), arret,
                                 intervalle_s=0.0, dormir=lambda _s: None, max_passes=5)
    assert n == 5 and len(appels) == 5


def test_boucle_s_arrete_quand_l_evenement_est_set():
    appels = []
    arret = threading.Event()

    def _dormir(_s):
        if len(appels) >= 3:
            arret.set()            # simule un arrêt demandé après 3 passes

    n = boucler_rafraichissement(lambda: appels.append(1), arret, intervalle_s=0.0, dormir=_dormir)
    assert n == 3


def test_contexte_rafraichit_pendant_une_operation_bloquante():
    # le thread de fond doit rafraîchir MÊME si la boucle principale est bloquée dans un sleep.
    compteur = {"n": 0}
    with RafraichisseurPeriodique(lambda: compteur.__setitem__("n", compteur["n"] + 1),
                                  intervalle_s=0.05):
        time.sleep(0.35)           # opération "bloquante" ~0.35 s -> ~6 rafraîchissements attendus
    assert compteur["n"] >= 3      # au moins quelques passes pendant le blocage (marge anti-flottement)


def test_contexte_s_arrete_proprement_en_sortie():
    compteur = {"n": 0}
    r = RafraichisseurPeriodique(lambda: compteur.__setitem__("n", compteur["n"] + 1), intervalle_s=0.02)
    with r:
        time.sleep(0.1)
    fige = compteur["n"]
    time.sleep(0.1)                # après le with, plus AUCun rafraîchissement
    assert compteur["n"] == fige and r._th is None
