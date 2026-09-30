"""Tests du REGISTRE DES LOIS MESURÉES (21/07).

Origine : un article sur le « context engineering » envoyé par Flo. Zéro idée de trading
dedans — mais il désigne un vrai trou chez nous : nos verdicts mesurés (copy −7,97 bps,
MM 0/29, lead-lag 0/66…) vivaient uniquement dans la mémoire d'une session. Une autre
session pouvait ré-implémenter une stratégie qu'on avait prouvée perdante.

Ce que ces tests PROUVENT :
  * chaque loi porte un CHIFFRE, une DATE, et la condition de réouverture (pas de prose vague) ;
  * une idée déjà réfutée déclenche le rappel — au moment où elle est proposée ;
  * une loi CONFIRMÉE ne bloque rien (ce n'est pas un interdit de penser) ;
  * `docs/LOIS_MESUREES.md` est GÉNÉRÉ du registre — il ne peut pas diverger silencieusement ;
  * le registre est BRANCHÉ dans `recherche_scenario` et dans le rapport quotidien
    (testé ≠ branché : la maladie du projet).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from hl_observer.research.lois_mesurees import (LOIS, VERDICT_CONFIRME, VERDICT_LIMITE,
                                                VERDICT_REFUTE, Loi, avertissement, chercher,
                                                loi, markdown, par_verdict)

RACINE = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ forme du registre

def test_le_registre_n_est_pas_vide_et_les_cles_sont_uniques():
    assert len(LOIS) >= 10
    cles = [l.cle for l in LOIS]
    assert len(cles) == len(set(cles))


@pytest.mark.parametrize("l", LOIS, ids=[l.cle for l in LOIS])
def test_chaque_loi_porte_un_chiffre_une_date_et_une_sortie(l):
    """Une loi sans nombre est une opinion ; une loi sans date est une croyance ; une loi
    sans condition de réouverture est un dogme. Les trois sont interdits."""
    assert re.search(r"\d", l.chiffre), "pas de nombre dans le verdict de %s" % l.cle
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", l.date), "date mal formée sur %s" % l.cle
    assert len(l.condition_de_reouverture) > 10
    assert l.mots_cles, "sans mots-clés, la loi ne sera jamais retrouvée"
    assert l.titre and l.cle


def test_un_verdict_inconnu_est_refuse():
    with pytest.raises(ValueError):
        Loi(cle="x", titre="x", verdict="PEUT_ETRE", chiffre="1", date="2026-01-01",
            condition_de_reouverture="une donnée neuve quelconque")


def test_les_trois_verdicts_sont_representes():
    assert par_verdict(VERDICT_REFUTE) and par_verdict(VERDICT_CONFIRME)
    assert len(par_verdict(VERDICT_REFUTE)) + len(par_verdict(VERDICT_LIMITE)) \
        + len(par_verdict(VERDICT_CONFIRME)) == len(LOIS)


def test_le_carry_est_la_seule_loi_CONFIRMEE():
    """Le carry est le seul chiffre positif du projet. Si un jour ce test casse, c'est soit
    une vraie bonne nouvelle, soit quelqu'un s'est auto-décerné un verdict."""
    assert [l.cle for l in par_verdict(VERDICT_CONFIRME)] == ["carry_delta_neutre"]


# ------------------------------------------------------------------ la recherche par idée

@pytest.mark.parametrize("idee, cle_attendue", [
    ("ajouter un module de market making dans le spread", "market_making_spread"),
    ("suivre les wallets smart money les plus rentables", "copy_global"),
    ("réduire la latence avec de la colocation", "latence"),
    ("arbitrage de dislocation entre venues", "arbitrage_cross_venue"),
    ("un signal lead-lag BTC vers les alts", "lead_lag"),
    ("sizing par z-score du funding", "zscore_au_plancher"),
])
def test_une_idee_deja_mesuree_retrouve_sa_loi(idee, cle_attendue):
    assert cle_attendue in [l.cle for l in chercher(idee)]


def test_une_idee_neuve_ne_declenche_aucun_faux_rappel():
    """Un registre qui répond à tout devient du bruit et on cesse de le lire."""
    assert avertissement("un module de prédiction météo") is None
    assert avertissement("") is None
    assert avertissement(None) is None


def test_l_avertissement_donne_le_chiffre_ET_la_porte_de_sortie():
    a = avertissement("faire du market making dans le spread")
    assert "0 gagnant sur 29" in a
    assert "Pour rouvrir" in a
    assert "2026-07-13" in a


def test_une_loi_CONFIRMEE_seule_ne_declenche_PAS_d_avertissement():
    """Le carry est confirmé : proposer de l'améliorer ne doit pas afficher un rappel
    décourageant. Une loi n'est pas un interdit de penser."""
    assert chercher("améliorer le carry delta neutre")
    assert avertissement("améliorer le carry delta neutre") is None


def test_le_plus_contraignant_sort_en_premier():
    lois = chercher("copy trading et carry")
    assert lois[0].verdict != VERDICT_CONFIRME


def test_loi_par_cle():
    assert loi("copy_global").verdict == VERDICT_REFUTE
    assert loi("inconnue") is None


# ------------------------------------------------------------------ le doc ne peut pas diverger

def test_le_markdown_contient_chaque_loi_avec_son_chiffre():
    md = markdown()
    for l in LOIS:
        assert l.titre in md and l.cle in md and l.chiffre[:30] in md


def test_le_doc_du_depot_est_bien_GENERE_du_registre():
    """`docs/LOIS_MESUREES.md` est généré. S'il a été édité à la main, il diverge du registre
    testé — et c'est la version fausse que les humains liront."""
    p = RACINE / "docs" / "LOIS_MESUREES.md"
    assert p.exists(), "docs/LOIS_MESUREES.md manquant : régénère-le depuis lois_mesurees.markdown()"
    assert p.read_text(encoding="utf-8").strip() == markdown().strip(), (
        "docs/LOIS_MESUREES.md a divergé du registre — régénère-le, n'édite jamais le .md")


# ------------------------------------------------------------------ testé ≠ branché

def test_le_registre_est_BRANCHE_dans_la_recherche_de_pepites():
    """C'est là qu'une idée est PROPOSÉE, donc là qu'un verdict déjà mesuré doit apparaître."""
    src = (RACINE / "src" / "hl_observer" / "backtesting"
           / "recherche_scenario.py").read_text(encoding="utf-8")
    assert "lois_mesurees" in src
    assert "RAPPEL" in src


def test_le_registre_est_BRANCHE_dans_le_rapport_quotidien():
    src = (RACINE / "tools" / "rapport_quotidien.py").read_text(encoding="utf-8")
    assert "lois_mesurees" in src and "_sec_lois" in src
    assert "secs.append(_sec_lois(racine))" in src


def test_AGENTS_md_pointe_les_lois_et_porte_sa_date():
    """Un AGENTS.md périmé oriente vers la mauvaise cible AVEC AUTORITÉ — c'est le défaut
    qu'on vient de corriger (il avait 13 jours de retard). Il doit se dater lui-même."""
    src = (RACINE / "AGENTS.md").read_text(encoding="utf-8")
    assert "LOIS_MESUREES.md" in src
    assert re.search(r"Dernière mise à jour\s*:\s*\**\d{4}-\d{2}-\d{2}", src)
    assert "src/hl_observer/" in src        # il doit désigner le runtime ACTIF
