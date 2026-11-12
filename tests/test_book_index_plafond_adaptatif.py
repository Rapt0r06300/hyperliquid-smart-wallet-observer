"""M1 — le cache d'index de carnets rétrécit avec la RAM, et n'efface plus tout d'un coup.

Deux défauts corrigés le 12/11 :

1. ``MAX_LISTES`` bornait un NOMBRE de listes, pas un VOLUME : 1024 listes de centaines de milliers de
   carnets ne sont pas bornées en octets. Le plafond suit donc maintenant la pression mémoire.
2. au plafond, le cache faisait ``clear()`` — il jetait aussi les entrées chaudes, créant une falaise
   de performance juste après. Il ÉVINCE désormais les plus anciennes jusqu'à repasser sous le plafond.

Contrainte de performance verrouillée ici aussi : ``index_des_carnets`` est sur le chemin chaud (une
fois par décision rejouée), donc la pression mémoire ne doit être lue QUE sur le chemin froid.

Et la garantie du module reste intacte : évincer ne change JAMAIS un résultat.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_book_index as INDEX  # noqa: E402


def _carnets(n: int, depart: int = 1) -> list[dict]:
    return [{"ts_ms": depart + i} for i in range(n)]


class _Gouverneur:
    """Gouverneur injectable : niveau fixé, et on compte les lectures de pression."""

    def __init__(self, niveau="VERT", facteur=1.0):
        self._niveau, self._facteur = niveau, facteur
        self.lectures = 0

    def niveau_pression(self, **_k):
        self.lectures += 1
        return self._niveau

    def facteur_d_ampleur(self, _niveau):
        return self._facteur


class _GouverneurCasse:
    def niveau_pression(self, **_k):
        raise RuntimeError("casse")

    def facteur_d_ampleur(self, _n):
        raise RuntimeError("casse")


# ------------------------------------------------------------------ plafond adaptatif

def test_le_plafond_suit_la_pression_memoire():
    assert INDEX.plafond_listes(gouverneur=_Gouverneur("VERT", 1.0)) == INDEX.MAX_LISTES
    assert INDEX.plafond_listes(gouverneur=_Gouverneur("ORANGE", 0.5)) == INDEX.MAX_LISTES // 2
    assert INDEX.plafond_listes(gouverneur=_Gouverneur("ROUGE", 0.25)) == INDEX.MAX_LISTES // 4


def test_le_plafond_ne_descend_jamais_sous_le_plancher(monkeypatch):
    """Même sous forte pression, on garde un cache utile : un cache à zéro ferait exploser le temps
    de replay (c'est ce cache qui a sauvé le labo le 11/11)."""
    monkeypatch.setattr(INDEX, "MAX_LISTES", 10)
    assert INDEX.plafond_listes(gouverneur=_Gouverneur("ROUGE", 0.01)) == INDEX.PLAFOND_MINI_LISTES


def test_sans_gouverneur_le_plafond_reste_nominal():
    assert INDEX.plafond_listes(gouverneur=None) == INDEX.MAX_LISTES


def test_un_gouverneur_casse_ne_fait_jamais_lever_et_garde_le_plafond():
    assert INDEX.plafond_listes(gouverneur=_GouverneurCasse()) == INDEX.MAX_LISTES


def test_un_facteur_absurde_est_ignore():
    assert INDEX.plafond_listes(gouverneur=_Gouverneur("?", 0.0)) == INDEX.MAX_LISTES
    assert INDEX.plafond_listes(gouverneur=_Gouverneur("?", 3.0)) == INDEX.MAX_LISTES
    assert INDEX.plafond_listes(gouverneur=_Gouverneur("?", -1.0)) == INDEX.MAX_LISTES


# ------------------------------------------------------------------ éviction bornée

def test_l_eviction_garde_les_plus_recentes_et_ne_vide_pas_tout(monkeypatch):
    INDEX.oublier_les_index()
    monkeypatch.setattr(INDEX, "SEUIL_INDEX", 4)
    listes = [_carnets(5, depart=1 + 100 * i) for i in range(6)]      # gardées vivantes ici
    for liste in listes:
        INDEX.index_des_carnets(liste)
    assert len(INDEX._INDEX) == 6

    evincees = INDEX._evincer_les_plus_anciennes(3)
    assert evincees == 4                                              # on descend SOUS 3
    assert len(INDEX._INDEX) == 2
    # ce sont bien les DERNIÈRES qui restent (ordre d'insertion), pas un vidage complet
    assert id(listes[-1]) in INDEX._INDEX and id(listes[-2]) in INDEX._INDEX
    assert id(listes[0]) not in INDEX._INDEX
    INDEX.oublier_les_index()


def test_au_plafond_on_evince_au_lieu_de_tout_effacer(monkeypatch):
    INDEX.oublier_les_index()
    monkeypatch.setattr(INDEX, "SEUIL_INDEX", 4)
    monkeypatch.setattr(INDEX, "MAX_LISTES", 4)
    monkeypatch.setattr(INDEX, "PLAFOND_MINI_LISTES", 2)
    monkeypatch.setattr(INDEX, "_plafond_courant", 4)
    listes = [_carnets(5, depart=1 + 100 * i) for i in range(8)]
    for liste in listes:
        INDEX.index_des_carnets(liste)
    # l'ancien comportement (clear) laissait 1 entrée ; ici on reste rempli juste sous le plafond
    assert 1 < len(INDEX._INDEX) <= 4
    assert id(listes[-1]) in INDEX._INDEX                             # la plus récente est gardée
    INDEX.oublier_les_index()


def test_oublier_les_index_remet_le_plafond_nominal(monkeypatch):
    monkeypatch.setattr(INDEX, "_plafond_courant", 2)
    INDEX.oublier_les_index()
    assert INDEX._plafond_courant == INDEX.MAX_LISTES
    assert INDEX._INDEX == {}


# ------------------------------------------------------------------ la garantie reste intacte

def test_evincer_ne_change_jamais_un_resultat(monkeypatch):
    """Garantie centrale du module : l'index est une mémorisation, pas une source de vérité."""
    INDEX.oublier_les_index()
    monkeypatch.setattr(INDEX, "SEUIL_INDEX", 4)
    liste = _carnets(6)
    avant = INDEX.index_des_carnets(liste)
    attendu = (avant.horodatages_exacts(), avant.continus()[1], avant.horodatages_de_reference())

    INDEX._evincer_les_plus_anciennes(1)                              # on jette son index
    assert id(liste) not in INDEX._INDEX

    apres = INDEX.index_des_carnets(liste)                            # recalculé depuis zéro
    assert apres is not avant
    assert (apres.horodatages_exacts(), apres.continus()[1], apres.horodatages_de_reference()) == attendu
    INDEX.oublier_les_index()


def test_la_pression_n_est_PAS_lue_sur_le_chemin_chaud(monkeypatch):
    """Point de performance non négociable : `index_des_carnets` est appelé une fois par décision
    rejouée. Lire la RAM à chaque appel coûterait plus que le cache ne fait gagner."""
    INDEX.oublier_les_index()
    monkeypatch.setattr(INDEX, "SEUIL_INDEX", 4)
    monkeypatch.setattr(INDEX, "_plafond_courant", 10_000)            # plafond loin : chemin chaud
    gouv = _Gouverneur("VERT", 1.0)
    monkeypatch.setattr(INDEX, "_gouverneur", lambda: gouv)

    liste = _carnets(5)
    for _ in range(200):
        INDEX.index_des_carnets(liste)
    assert gouv.lectures == 0, "aucune lecture de pression tant que le plafond n'est pas atteint"
    INDEX.oublier_les_index()


def test_la_pression_est_lue_quand_on_atteint_le_plafond(monkeypatch):
    INDEX.oublier_les_index()
    monkeypatch.setattr(INDEX, "SEUIL_INDEX", 4)
    monkeypatch.setattr(INDEX, "MAX_LISTES", 4)
    monkeypatch.setattr(INDEX, "PLAFOND_MINI_LISTES", 2)
    monkeypatch.setattr(INDEX, "_plafond_courant", 2)
    gouv = _Gouverneur("ROUGE", 0.25)
    monkeypatch.setattr(INDEX, "_gouverneur", lambda: gouv)

    listes = [_carnets(5, depart=1 + 100 * i) for i in range(4)]
    for liste in listes:
        INDEX.index_des_carnets(liste)
    assert gouv.lectures >= 1, "au plafond, la pression DOIT etre consultee"
    INDEX.oublier_les_index()
