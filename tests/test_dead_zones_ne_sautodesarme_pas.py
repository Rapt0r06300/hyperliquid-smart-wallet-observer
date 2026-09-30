"""LE REGISTRE DES ZONES MORTES NE DOIT PAS S'AUTO-DESARMER (2026-07-12).

LE BUG
------
    def refus(self, proposition):
        touches = self.consulter(proposition)
        if not touches: return ""
        if self.voie_de_reouverture(proposition):   # <-- N'IMPORTE QUELLE zone du registre !
            return ""

`voie_de_reouverture()` scanne TOUT le registre. Donc une proposition de COPY-TRADING (zone
morte : -7,97 bps sur 24 133 obs) qui prononce le mot « spot » etait BLANCHIE par la voie de
reouverture du FUNDING (dont les mots de reouverture sont spot/hedge/couverture/basis).

Une zone morte pouvait annuler le refus d'une AUTRE. Le cimetiere s'ouvrait tout seul.

L'INVARIANT DEFENDU
-------------------
    Seule la voie de reouverture des zones REELLEMENT TOUCHEES peut lever un refus.
    Chaque zone garde son issue de secours -- et celle des autres ne la concerne pas.

Aucun reseau, aucun ordre reel : ce sont des zones synthetiques.
"""
from __future__ import annotations

import pytest

from hl_observer.agent.dead_zones import RegistreZonesMortes, creer_zone_morte


def _zone_copie() -> object:
    return creer_zone_morte(
        id="COPIE_MORTE",
        hypothese="Copier les leaders rapporte.",
        verdict="Aucun edge, a aucun horizon.",
        mesure="edge net median hors echantillon",
        valeur=-7.97, unite="bps", echantillon=24133, date="2026-07-11",
        lecon="Un score de wallet n'est pas un edge en bps.",
        condition_de_reouverture="un signal qui n'est PAS le fill public d'un leader",
        entree_mesuree="fill_public_leader",
        mots_cles=("copy", "copier", "leader", "scanner", "wallets"),
        mots_cles_reouverture=("prive", "prefill"),
        source="test",
    )


def _zone_funding() -> object:
    return creer_zone_morte(
        id="FUNDING_NU_MORT",
        hypothese="Encaisser le funding sur une jambe nue rapporte.",
        verdict="Le prix noie le funding d'un facteur 281.",
        mesure="ratio funding / bruit de prix",
        valeur=0.0036, unite="ratio", echantillon=9512, date="2026-07-11",
        lecon="Monter le seuil de funding CONCENTRE le risque au lieu de le filtrer.",
        condition_de_reouverture="une VRAIE jambe de couverture spot",
        entree_mesuree="funding_seul",
        mots_cles=("funding", "carry"),
        mots_cles_reouverture=("spot", "hedge", "couverture", "basis"),
        source="test",
    )


def _registre() -> RegistreZonesMortes:
    return RegistreZonesMortes(zones=[_zone_copie(), _zone_funding()])


def test_une_zone_morte_ne_peut_PAS_annuler_le_refus_dune_AUTRE() -> None:
    """LE test du bug. Le mot « spot » appartient a la reouverture du FUNDING, pas de la COPIE."""
    reg = _registre()
    proposition = (
        "Scanner plus de wallets et copier les fills des leaders, en couvrant avec du spot"
    )
    motif = reg.refus(proposition)

    assert motif, (
        "REGRESSION : le registre s'est AUTO-DESARME. Une proposition de copy-trading a ete "
        "blanchie parce qu'elle prononcait un mot appartenant a la voie de reouverture d'une "
        "AUTRE zone morte (le funding). Le cimetiere ne doit jamais s'ouvrir tout seul."
    )
    assert "COPIE_MORTE" in motif, "Le refus doit etre prononce au nom de la zone REELLEMENT touchee."


def test_la_VRAIE_voie_de_reouverture_dune_zone_leve_bien_son_refus() -> None:
    """Le contraire d'un dogme : une zone morte dit elle-meme ce qui la rouvrirait."""
    reg = _registre()
    motif = reg.refus("Carry de funding avec une vraie jambe spot de couverture (hedge)")
    assert motif == "", (
        "La proposition emprunte EXACTEMENT la voie de reouverture du funding "
        "(spot + couverture). La refuser ferait du registre un DOGME, pas une memoire."
    )


def test_le_scanner_de_wallets_est_bien_du_copy_trading_deguise() -> None:
    """« Ameliorer le scanner » n'est pas un probleme d'infra : c'est le signal mort, plus vite."""
    reg = _registre()
    motif = reg.refus(
        "Scanner beaucoup plus de wallets, les classer, suivre les meilleurs pour copier leurs fills"
    )
    assert motif, (
        "Une zone morte doit attraper l'IDEE, pas seulement son vocabulaire. Ameliorer le "
        "scanner ne cree aucun edge : ca alimente plus vite un signal mesure a -7,97 bps."
    )
    assert "COPIE_MORTE" in motif


def test_une_proposition_libre_reste_libre() -> None:
    """Le registre ne doit pas devenir un mur : ce qui n'a pas ete mesure passe."""
    reg = _registre()
    assert reg.refus("Construire un moteur de carnet local en Rust pour reduire la latence") == ""
