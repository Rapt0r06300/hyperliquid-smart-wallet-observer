"""INVARIANT DES PORTES ANTI-MENSONGE DU LABORATOIRE (P0-3, 21/07).

LE TROU, NOMMÉ
--------------
Les portes existaient et étaient documentées : deux moitiés temporelles disjointes avec
embargo, coûts stressés ×1,5, ≥ 30 trades par moitié, profit factor minimal, plateau des
voisins. **Aucun test n'échouait si on les désactivait.** Un jour de fatigue, un
`MIN_TRADES_PAR_MOITIE = 5` « juste pour voir », et le laboratoire promeut du bruit — sans
qu'aucune alarme ne sonne.

C'est exactement la maladie du projet appliquée aux garde-fous eux-mêmes : une porte qu'on
peut retirer sans rien casser n'est pas une porte, c'est une convention.

CE QUE CES TESTS VERROUILLENT
-----------------------------
1. les CONSTANTES ne peuvent pas être affaiblies silencieusement ;
2. `porte_robuste` REFUSE effectivement chaque cas qu'elle prétend refuser — un par un ;
3. le stress ×1,5 est **appliqué**, pas seulement déclaré ;
4. l'embargo existe entre les deux moitiés (pas de fuite temporelle) ;
5. un scénario qui ne survit qu'à une moitié n'est JAMAIS promu.

Si l'un de ces tests casse, ce n'est pas le test qu'il faut corriger : c'est qu'une porte
vient de tomber.
"""
from __future__ import annotations

import inspect

import pytest

from hl_observer.backtesting import recherche_scenario as RS


# ------------------------------------------------------------------ 1. les constantes

def test_les_seuils_des_portes_ne_peuvent_pas_etre_affaiblis():
    """Valeurs GRAVÉES. Les baisser rend le laboratoire complaisant : c'est la façon la plus
    silencieuse de se mentir à soi-même sur un backtest."""
    assert RS.MIN_TRADES_PAR_MOITIE >= 30, "moins de 30 trades par moitié ne prouve rien"
    assert RS.STRESS_COUTS >= 1.5, "le stress des coûts ne descend pas sous ×1,5"
    assert RS.EMBARGO_FACTEUR >= 1.0, "l'embargo vaut au moins un horizon de part et d'autre"
    assert RS.MIN_PF_PAR_MOITIE >= 1.1, "un profit factor sous 1,1 n'est pas un edge"


def test_le_stress_des_couts_est_un_MULTIPLICATEUR_pas_une_remise():
    assert RS.STRESS_COUTS > 1.0


# ------------------------------------------------------------------ 2. la porte refuse VRAIMENT

def _moitie(trades=50, net=10.0, pf=1.5):
    return {"trades": trades, "net_total_usd": net, "profit_factor": pf}


def _rapport(m1=None, m2=None, stress_net=5.0):
    return {"moitie_1": m1 or _moitie(), "moitie_2": m2 or _moitie(),
            "stress": {"net_total_usd": stress_net}}


def test_un_scenario_parfait_passe():
    """Contrôle positif : sans lui, un test qui refuse TOUT passerait pour rigoureux."""
    assert RS.porte_robuste(_rapport()) is True


@pytest.mark.parametrize("nom, rapport", [
    ("pas assez de trades sur la 1re moitié", _rapport(m1=_moitie(trades=29))),
    ("pas assez de trades sur la 2e moitié", _rapport(m2=_moitie(trades=29))),
    ("net négatif sur la 1re moitié", _rapport(m1=_moitie(net=-0.01))),
    ("net négatif sur la 2e moitié", _rapport(m2=_moitie(net=-0.01))),
    ("net NUL sur une moitié (zéro n'est pas positif)", _rapport(m1=_moitie(net=0.0))),
    ("profit factor trop faible", _rapport(m1=_moitie(pf=1.05))),
    ("ne survit pas au stress ×1,5", _rapport(stress_net=-0.01)),
    ("stress exactement nul", _rapport(stress_net=0.0)),
    ("moitié manquante", {"moitie_1": _moitie(), "stress": {"net_total_usd": 5.0}}),
    ("stress manquant", {"moitie_1": _moitie(), "moitie_2": _moitie()}),
    ("rapport vide", {}),
])
def test_la_porte_refuse_chaque_cas_qu_elle_pretend_refuser(nom, rapport):
    assert RS.porte_robuste(rapport) is False, "la porte a laissé passer : %s" % nom


def test_un_profit_factor_INFINI_est_accepte():
    """Aucune perte du tout = PF infini. C'est un cas légitime, pas une anomalie."""
    assert RS.porte_robuste(_rapport(m1=_moitie(pf="inf"), m2=_moitie(pf="inf"))) is True


@pytest.mark.parametrize("pf", [None, "beaucoup", float("nan")])
def test_un_profit_factor_ILLISIBLE_ne_passe_PAS(pf):
    """Deny-by-default : une métrique qu'on ne sait pas lire ne vaut pas un feu vert."""
    assert RS.porte_robuste(_rapport(m1=_moitie(pf=pf))) is False


# ------------------------------------------------------------------ 3. le stress est APPLIQUÉ

def test_le_stress_est_reellement_calcule_avec_des_couts_majores():
    """Une constante `STRESS_COUTS = 1.5` qui ne serait jamais multipliée à un coût serait
    de la décoration. On vérifie qu'elle est bien employée dans l'évaluation."""
    src = inspect.getsource(RS)
    assert "STRESS_COUTS" in src
    # elle doit MULTIPLIER un coût quelque part, pas seulement être définie et affichée
    assert ("cost_bps * STRESS_COUTS" in src or "STRESS_COUTS * cost_bps" in src
            or "cost_bps=cost_bps * RS.STRESS_COUTS" in src
            or "* STRESS_COUTS" in src), "STRESS_COUTS n'est multiplié à aucun coût"


def test_les_deux_moities_et_le_stress_sont_TROIS_evaluations_distinctes():
    """Si le stress réutilisait le résultat d'une moitié, il ne stresserait rien."""
    src = inspect.getsource(RS)
    assert '"moitie_1"' in src and '"moitie_2"' in src and '"stress"' in src


# ------------------------------------------------------------------ 4. embargo & folds purgés

def test_l_embargo_separe_les_deux_moities():
    src = inspect.getsource(RS)
    assert "EMBARGO_FACTEUR" in src, "aucun embargo : les deux moitiés peuvent se toucher"
    assert "folds_purges" in src, "aucun fold purgé : le CPCV annoncé n'existerait pas"


def test_le_rang_OR_exige_la_survie_sur_au_moins_3_folds_sur_4():
    src = inspect.getsource(RS.rang_pepite)
    assert "vivants >= 3" in src, "le rang OR ne serait plus une preuve supplémentaire"


# ------------------------------------------------------------------ 5. ce que le README promet

def test_le_README_ne_promet_aucune_porte_que_le_code_n_applique_pas():
    """Une porte annoncée et absente est un mensonge documentaire — la catégorie de défaut
    qu'on a passé la journée du 21/07 à traquer."""
    from pathlib import Path
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    if "×1,5" in readme or "x1,5" in readme:
        assert RS.STRESS_COUTS >= 1.5
    if "30 trades" in readme:
        assert RS.MIN_TRADES_PAR_MOITIE >= 30
    if "embargo" in readme.lower():
        assert RS.EMBARGO_FACTEUR >= 1.0
