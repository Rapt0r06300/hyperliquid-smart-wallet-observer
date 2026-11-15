"""Le livre transversal INVERSE — le seul sens qui mesure positif.

CONTEXTE MESURE LE 14/11 (211 jours, 90 coins, prix compris) :
* le sens de `carry_ranking` (long funding bas) : **-41,3 %/an, 8 detentions positives sur 25** —
  le funding rapportait +1,635 % mais le prix reprenait -4,901 %, trois fois plus ;
* le sens INVERSE : positif sur les trois tiers de l'histoire ;
* le momentum DIRECT : **-44,2 %**, negatif a tous les k -> le funding ne mesure donc pas la
  performance passee mais **l'ENCOMBREMENT DU POSITIONNEMENT**.

Ces tests verrouillent la causalite, le sens, et les deux refus qui empechent de proposer un livre
qui n'existera pas.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.strategies.carry_transversal_inverse import (  # noqa: E402
    MOTIF_PAS_ASSEZ,
    MOTIF_SOUS_MINIMUM,
    NOTIONNEL_MINIMUM_USD,
    CarryTransversalInverse,
    Refus,
    moyenne_anterieure,
)
from hl_observer.strategies.models import IntentSide  # noqa: E402


def _univers(n=12, base=0.0001):
    """n coins de funding croissant : C0 le plus bas, C11 le plus haut."""
    return {f"C{i}": {h: base * (i + 1) for h in range(0, 400)} for i in range(n)}


# ---------------------------------------------------------------- CAUSALITE

def test_la_fenetre_EXCLUT_l_heure_de_decision():
    """LE test qui compte : inclure l'heure de decision ferait entrer une information qu'on
    n'avait pas. C'est la frontiere exacte entre une mesure et un lookahead."""
    serie = {10: 1.0, 11: 1.0, 12: 999.0}      # 12 = l'heure de decision, valeur aberrante
    assert moyenne_anterieure(serie, fin_exclue=12, fenetre_h=5) == 1.0


def test_une_fenetre_vide_rend_None_et_pas_zero():
    """Zero serait un classement (« funding nul ») ; None est l'absence de classement."""
    assert moyenne_anterieure({50: 1.0}, fin_exclue=10, fenetre_h=5) is None


# ---------------------------------------------------------------- LE SENS

def test_on_LONGE_le_funding_HAUT_et_on_SHORTE_le_BAS():
    """Le sens inverse de `carry_ranking`, qui est le sens refute (-41,3 %/an)."""
    s = CarryTransversalInverse.default()
    longs, shorts = s.classer(_univers(), instant_h=200, fenetre_h=168, k=3)
    assert longs == ["C11", "C10", "C9"]           # funding le plus haut -> LONG
    assert set(shorts) == {"C0", "C1", "C2"}       # le plus bas -> SHORT


def test_les_intentions_portent_les_DEUX_cotes_a_parts_egales():
    """Le livre est dollar-neutre : la jambe longue perd -9,2 %/an seule mais divise le repli
    par 3,5. Elle se paie en RISQUE."""
    s = CarryTransversalInverse.default()
    out = s.proposer(_univers(), instant_h=200, notionnel_total_usd=600.0)
    assert not isinstance(out, Refus)
    assert len(out) == 6
    longs = [i for i in out if i.side is IntentSide.LONG]
    shorts = [i for i in out if i.side is IntentSide.SHORT]
    assert len(longs) == len(shorts) == 3
    assert all(abs(i.target_notional_usdt - 100.0) < 1e-9 for i in out)


def test_la_confiance_ne_surjoue_PAS_le_taux_de_reussite():
    """58 % des detentions mesurees sont positives : l'edge vient de l'ASYMETRIE, pas de la
    frequence. Une confiance de 0,9 serait un mensonge."""
    s = CarryTransversalInverse.default()
    out = s.proposer(_univers(), instant_h=200, notionnel_total_usd=600.0)
    assert all(abs(i.confidence - 0.58) < 1e-9 for i in out)


# ---------------------------------------------------------------- LES REFUS

def test_pas_assez_de_coins_REFUSE_au_lieu_de_reduire_le_livre():
    """Construire un livre plus petit en silence changerait la strategie sans le dire."""
    s = CarryTransversalInverse.default()
    out = s.proposer(_univers(n=4), instant_h=200, notionnel_total_usd=600.0)
    assert isinstance(out, Refus)
    assert out.motif == MOTIF_PAS_ASSEZ


def test_une_jambe_sous_le_minimum_de_la_venue_est_REFUSEE():
    """Un ordre de 4 USD n'est pas une petite position, c'est un ordre REJETE. Proposer un livre
    non placable serait proposer un livre qui n'existera pas."""
    s = CarryTransversalInverse.default()
    out = s.proposer(_univers(), instant_h=200, notionnel_total_usd=30.0)   # 5 USD/jambe
    assert isinstance(out, Refus)
    assert out.motif == MOTIF_SOUS_MINIMUM
    assert "minimum" in out.detail
    # et le detail dit le notionnel requis, pour que l'operateur sache quoi corriger
    assert "60" in out.detail                       # 6 jambes x 10 USD


def test_exactement_au_minimum_ca_PASSE():
    s = CarryTransversalInverse.default()
    out = s.proposer(_univers(), instant_h=200,
                     notionnel_total_usd=6 * NOTIONNEL_MINIMUM_USD)
    assert not isinstance(out, Refus)
    assert len(out) == 6


# ---------------------------------------------------------------- LE CONTRAT DU MOTEUR

def test_la_strategie_est_PAPER_et_lecture_seule_par_construction():
    s = CarryTransversalInverse.default()
    assert s.definition.read_only is True
    assert s.strategy_id == "carry_transversal_inverse"


def test_rien_dans_ce_module_n_execute():
    """Le contrat de `strategies/` : il PROPOSE, le noyau dispose. Aucune surface d'execution."""
    import hl_observer.strategies.carry_transversal_inverse as mod
    source = Path(mod.__file__).read_text(encoding="utf-8")
    for interdit in ("requests.", "urlopen", "post(", "sign", "private_key", "order("):
        assert interdit not in source, f"surface d'execution suspecte : {interdit}"
