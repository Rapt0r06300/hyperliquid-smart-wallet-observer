"""IMPROVE-20 (#127) — le régime, sans lire le futur.

Le test central est un **test DIFFÉRENTIEL** (méthode H-157) : il ne lit pas le code, il change
le FUTUR et vérifie que le PASSÉ ne bouge pas. C'est le seul contrôle qu'une implémentation
astucieuse ne peut pas contourner par du commentaire rassurant.

C'est ainsi qu'on a démasqué `garch11_variance` : elle ÉCHOUE ce test.
"""

from __future__ import annotations

import pytest

from hl_observer.backtesting.regime_detection import (
    garch11_variance,
    garch11_variance_causale,
)
from hl_observer.backtesting.regime_label import (
    BASSE_VOL,
    HAUTE_VOL,
    INCONNU,
    etiqueter,
    seuil_depuis_le_train,
    trades_etiquetes,
    variances_causales,
)
from hl_observer.backtesting.validation_gates import regime_robustness_gate

# Série déterministe : 40 rendements calmes, puis 40 agités. Aucun hasard, aucun seed à trahir.
CALME = [0.001, -0.001] * 20
AGITE = [0.05, -0.05] * 20
SERIE = CALME + AGITE


def test_LA_VERSION_HISTORIQUE_DE_GARCH_LIT_LE_FUTUR():
    """🔴 LE TEST QUI A TOUT DÉCLENCHÉ.

    On change UNIQUEMENT le futur (les 10 derniers rendements). Si une valeur PASSÉE bouge,
    c'est que la fonction a regardé devant elle. `garch11_variance` bouge — parce qu'elle
    s'amorce sur la variance de TOUTE la série.

    Ce test ne dénonce pas un détail théorique : brancher cette fonction sur le gate anti-overfit
    aurait injecté du lookahead DANS le garde-fou anti-lookahead.
    """
    futur_a = SERIE[:]
    futur_b = SERIE[:-10] + [0.30] * 10  # on ne touche QUE la fin

    a = garch11_variance(futur_a)
    b = garch11_variance(futur_b)

    assert a[:70] != b[:70], (
        "garch11_variance serait causale ? Alors la docstring qui l'interdit sur le chemin de "
        "décision est fausse, et il faut la corriger — pas ignorer ce test."
    )


def test_LA_VERSION_CAUSALE_NE_LIT_PAS_LE_FUTUR():
    """Le même test différentiel, sur la version causale. Le passé DOIT être identique.

    Un garde-fou qui ne peut pas échouer ne garde rien : le test précédent prouve que ce
    contrôle SAIT dire non.
    """
    a = garch11_variance_causale(SERIE)
    b = garch11_variance_causale(SERIE[:-10] + [0.30] * 10)

    assert a[:70] == b[:70], (
        "une variance passée a changé alors que seul le FUTUR a été modifié : la fonction "
        "regarde devant elle."
    )


def test_les_valeurs_de_warmup_sont_None_et_pas_un_chiffre_invente():
    """Avant d'avoir de l'historique, on ne SAIT pas. `None` dit « je ne sais pas ».

    Un chiffre inventé aurait passé les gates en silence — c'est exactement la maladie qu'on
    traque depuis une semaine.
    """
    v = variances_causales(SERIE, warmup=20)
    assert v[:20] == [None] * 20
    assert all(x is not None for x in v[20:])


def test_le_SEUIL_ne_regarde_que_le_TRAIN():
    """Un seuil calculé sur train+test connaîtrait le futur — lookahead discret, mais réel.

    On vérifie que le seuil ne dépend PAS de ce qu'on met après le train.
    """
    train = SERIE[:60]
    s1 = seuil_depuis_le_train(train)
    s2 = seuil_depuis_le_train(train)  # même train -> même seuil, forcément
    assert s1 is not None and s1.seuil == s2.seuil
    assert s1.n_train == len(train) - 20  # les 20 du warmup ne comptent pas

    # Un train trop court ne produit PAS un seuil bancal : il produit None.
    assert seuil_depuis_le_train(SERIE[:25]) is None


def test_les_labels_separent_vraiment_le_CALME_de_l_AGITE():
    """Le module doit MESURER quelque chose de réel, pas juste être causal et vide."""
    seuil = seuil_depuis_le_train(SERIE[:60])
    labels = etiqueter(SERIE, seuil)

    assert labels[:20] == [INCONNU] * 20, "pas d'historique = pas de label"
    fin = labels[-20:]
    assert all(x == HAUTE_VOL for x in fin), "la phase agitée doit être vue comme HAUTE_VOL"
    assert BASSE_VOL in labels[20:60], "la phase calme doit être vue comme BASSE_VOL"


def test_sans_seuil_fiable_on_repond_INCONNU_PARTOUT():
    """Deny-by-default : pas de seuil crédible -> aucun label. On ne devine pas."""
    assert etiqueter(SERIE, None) == [INCONNU] * len(SERIE)


def test_on_ne_peut_PAS_coller_le_regime_d_un_trade_sur_un_autre():
    """Un désalignement silencieux entre trades et labels donnerait un régime FAUX à chaque trade."""
    with pytest.raises(ValueError):
        trades_etiquetes([{"pnl": 1.0}, {"pnl": 2.0}], [HAUTE_VOL])


def test_le_GATE_DECLARE_desormais_sa_degradation():
    """🚩 LE CŒUR DE #127.

    `regime_robustness_gate` cherchait un champ `regime` que PERSONNE n'écrivait. Il retombait
    donc TOUJOURS sur des tranches de temps — en s'appelant « regime_robustness ». Un nom qui
    promet un contrôle que le code ne fait pas est pire qu'un contrôle absent : il rassure.

    Le comportement pass/fail est inchangé. Ce qui change : le gate DIT dans quel mode il tourne.
    """
    pnls = [1.0, -0.5, 2.0, 0.5, 1.5, -1.0, 0.8, 1.2]

    # Ce que faisait TOUT le projet jusqu'ici : des floats -> aucun label possible.
    sans = regime_robustness_gate(pnls, pnls)
    assert sans["regime_labels_presents"] is False
    assert sans["mode"] == "tranches_temporelles_FAUTE_DE_LABEL"

    # Avec des trades étiquetés, le gate bascule VRAIMENT en mode régime.
    trades = [{"net_pnl_usdc": p} for p in pnls]
    labels = [HAUTE_VOL, BASSE_VOL] * 4
    avec = regime_robustness_gate(trades_etiquetes(trades, labels), pnls)
    assert avec["regime_labels_presents"] is True
    assert avec["mode"] == "regime"
    assert avec["slices"] == 2, "deux régimes -> deux tranches, pas quatre chunks de temps"
