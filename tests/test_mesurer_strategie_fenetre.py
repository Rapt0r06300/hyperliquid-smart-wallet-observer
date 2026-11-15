"""LA FENETRE MESURABLE — le garde-fou du defaut le plus grave trouve le 15/11.

CE QUI S'EST PASSE. Les periodes TRAIN / TEST / tiers etaient decoupees sur l'historique du
**FUNDING SEUL**. Or les deux sources n'ont pas la meme profondeur : le funding remonte a
~1 100 jours, les bougies HORAIRES a 208. Pendant que le rattrapage allongeait le funding de 211 a
1 059 jours, **les bornes des periodes se sont deplacees** et le chiffre de reference est passe de
**+3,02 a +1,27 USD/jour** — sans qu'une seule ligne de la strategie ait change, et sans le moindre
avertissement.

**Un labo dont les resultats bougent quand les donnees grandissent ne mesure rien.**

Ces tests verrouillent l'invariant : la fenetre vient de l'INTERSECTION, donc elle ne depend plus
de la source la plus profonde.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))


def _mod():
    spec = importlib.util.spec_from_file_location("mesurer_strategie",
                                                  RACINE / "tools" / "mesurer_strategie.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_la_fenetre_est_l_INTERSECTION_pas_le_funding_seul():
    m = _mod()
    funding = {"BTC": {h: 0.0001 for h in range(0, 1000)}}
    prix = {"BTC": {h: 100.0 for h in range(900, 1200)}}
    h = m.heures_exploitables(funding, prix)
    assert h[0] == 900 and h[-1] == 999          # ni 0, ni 1199
    assert len(h) == 100


def test_ALLONGER_LE_FUNDING_NE_DEPLACE_PAS_LA_FENETRE():
    """LE test qui compte. C'est exactement ce qui a fait passer le chiffre de +3,02 a +1,27 :
    le rattrapage allongeait le funding vers le PASSE, et les bornes suivaient."""
    m = _mod()
    prix = {"BTC": {h: 100.0 for h in range(1000, 1200)}}
    courte = m.heures_exploitables({"BTC": {h: 0.0001 for h in range(900, 1200)}}, prix)
    # le funding remonte 10x plus loin dans le passe — la fenetre doit etre IDENTIQUE
    longue = m.heures_exploitables({"BTC": {h: 0.0001 for h in range(0, 1200)}}, prix)
    assert courte == longue
    assert longue[0] == 1000


def test_sans_recouvrement_la_fenetre_est_VIDE_et_pas_devinee():
    """Pas de recouvrement = rien de mesurable. On ne rabat pas sur la source la plus longue."""
    m = _mod()
    h = m.heures_exploitables({"BTC": {h: 0.0001 for h in range(0, 100)}},
                              {"BTC": {h: 100.0 for h in range(500, 600)}})
    assert h == []


def test_un_SEUL_coin_portant_les_deux_suffit():
    """Exiger que TOUS les coins portent les deux exclurait toute heure ou un seul manque — la
    regle inverse de celle du classement, qui n'a besoin que des coins classables."""
    m = _mod()
    funding = {"BTC": {10: 0.0001}, "ETH": {h: 0.0001 for h in range(0, 100)}}
    prix = {"BTC": {10: 100.0}}                  # ETH n'a aucun prix
    assert m.heures_exploitables(funding, prix) == [10]


def test_la_configuration_gelee_n_est_PAS_reglable_en_ligne_de_commande():
    """Un outil qui laisserait regler `k` ou l'horizon apres avoir vu le resultat transformerait
    la mesure en recherche."""
    source = (RACINE / "tools" / "mesurer_strategie.py").read_text(encoding="utf-8")
    for interdit in ('add_argument("--k"', 'add_argument("--horizon', 'add_argument("--detention',
                     'add_argument("--tranches'):
        assert interdit not in source, f"parametre de strategie reglable : {interdit}"


def test_le_mmr_est_la_valeur_MESUREE_pas_la_supposee():
    """5 % etait le palier alt suppose ; la mesure sur 11 514 jambes donne 12,32 %. Revenir a 5 %
    gonflerait le levier de 45 % sans que rien ne le signale."""
    m = _mod()
    assert m.MMR > 0.10, "le mmr suppose a 5 % est revenu : la mesure dit 12,32 %"
