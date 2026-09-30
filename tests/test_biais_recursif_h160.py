"""H-160 / GH-02 — LE BIAIS RECURSIF, sur NOS features de production.

LA QUESTION : la valeur d'une feature a l'instant `t` depend-elle de la quantite d'historique
qu'on lui a donnee AVANT `t` ? Si oui, le **backtest** (qui voit tout) et le **live** (qui garde un
buffer borne) ne calculent pas la meme chose -- et le backtest ment sur ce que le live fera.

Ce fichier ne se contente pas de tester le detecteur : il **verrouille le verdict** sur les quatre
features de production, mesure sur des prix reels (cf. `tools/mesurer_biais_recursif.py`).

    BORNEES (fenetre glissante `r[-n:]`)     -> ecart EXACTEMENT nul
        features/vol_sigma.sigma_fast_slow_blend
        features/volatility.compute_volatility_blend

    RECURSIVES (etat propage sur toute la serie) -> ecart NON nul
        features/direction._ema        (amorce sur `values[0]`, puis toute la serie)
        features/rsi_overheat.rsi      (lissage de Wilder, amorce puis toute la serie)

🚩 **Si les quatre repondaient la meme chose, ce fichier ne prouverait rien.** C'est justement le
contraste entre les deux familles qui montre que la sonde MESURE quelque chose.

Aucun ordre reel.
"""

from __future__ import annotations

import math

import pytest

from hl_observer.backtesting.recursive_bias_probe import series_backtest_et_live, sonder
from hl_observer.features.direction import DirectionConfig, _signed_strength_bps
from hl_observer.features.rsi_overheat import rsi
from hl_observer.features.vol_sigma import sigma_fast_slow_blend
from hl_observer.features.volatility import compute_volatility_blend

H = 200  # le buffer que garde le LIVE


@pytest.fixture(scope="module")
def prix() -> list[float]:
    """Une marche aleatoire DETERMINISTE (seed fixe). Pas de donnee reelle -> pas de faux realisme.

    La mesure sur les VRAIS mids Hyperliquid est faite par `tools/mesurer_biais_recursif.py`
    (rapport : data/reports/biais_recursif.json). Ici on veut un test rapide et reproductible.
    """
    x, out = 100.0, []
    etat = 12345
    for _ in range(900):
        etat = (1103515245 * etat + 12345) % (2**31)     # LCG : deterministe, sans dependance
        x *= 1.0 + ((etat / 2**31) - 0.5) * 0.004
        out.append(x)
    return out


# ====================================================== 1. LES FEATURES BORNEES : ecart NUL


def test_sigma_fast_slow_blend_est_BORNEE_donc_STABLE(prix):
    """`r[-fast_n:]` / `r[-slow_n:]` : la feature ne regarde QUE ses N derniers points."""
    rendements = [math.log(prix[i] / prix[i - 1]) for i in range(1, len(prix))]
    s = sonder(
        "sigma_fast_slow_blend",
        lambda xs: sigma_fast_slow_blend(xs)["sigma_blend"],
        rendements,
        historique_live=H,
    )
    assert s.n_points > 100, "serie trop courte -> le test ne mesure rien"
    assert s.stable is True, (
        "une feature a fenetre glissante a produit un ecart backtest/live de %.3e : "
        "soit elle n'est pas bornee, soit la sonde est fausse" % s.ecart_max
    )
    assert s.ecart_max == 0.0


def test_compute_volatility_blend_est_BORNEE_donc_STABLE(prix):
    s = sonder(
        "volatility_blend_bps",
        lambda xs: (compute_volatility_blend(xs).blend_bps or 0.0),
        prix,
        historique_live=H,
    )
    assert s.n_points > 100
    assert s.stable is True and s.ecart_max == 0.0


# ====================================================== 2. LES FEATURES RECURSIVES : ecart NON nul


def test_l_EMA_de_direction_est_RECURSIVE(prix):
    """🔴 `_ema()` amorce sur `values[0]` puis parcourt TOUTE la serie fournie.

    `period` ne sert qu'a (a) refuser les series courtes et (b) fixer `k`. Il ne BORNE rien.
    Donc l'EMA au meme instant `t` differe selon l'historique qui precede -> backtest != live.
    """
    cfg = DirectionConfig()
    s = sonder(
        "direction.signed_strength_bps",
        lambda xs: _signed_strength_bps(xs, cfg),
        prix,
        historique_live=H,
    )
    assert s.n_points > 100
    assert s.stable is False, (
        "l'EMA aurait ete jugee stable -- or elle est amorcee sur values[0] et parcourt toute la "
        "serie. Si ce test devient vert, c'est que `_ema` a ete BORNEE (tant mieux) : mettre a "
        "jour ce test ET la doc, pas le supprimer."
    )
    assert s.ecart_max > 0.0


def test_le_RSI_est_RECURSIF(prix):
    """🔴 Lissage de Wilder : `avg_gain` est propage sur toute la serie apres l'amorce."""
    s = sonder("rsi_14", lambda xs: rsi(xs, 14), prix, historique_live=H)
    assert s.n_points > 100
    assert s.stable is False
    assert s.ecart_max > 0.0


# ====================================================== 3. LA SONDE ELLE-MEME


def test_la_sonde_compare_bien_les_MEMES_INSTANTS(prix):
    """🚩 Le piege classique : comparer un backtest a un live decale d'un cran.

    Les deux series doivent avoir la MEME longueur et commencer au MEME instant -- sinon on
    mesurerait un decalage temporel et on l'appellerait « biais recursif ».
    """
    complet, borne = series_backtest_et_live(lambda xs: xs[-1], prix, historique_live=H)
    assert len(complet) == len(borne) == len(prix) - H
    # `dernier point` est la feature la plus bornee qui soit : les deux series sont IDENTIQUES
    assert complet == borne


def test_une_serie_TROP_COURTE_est_declaree_telle_et_non_STABLE():
    """Une sonde sans donnee ne doit pas rendre « stable » -- elle doit rendre « je n'ai pas pu »."""
    s = sonder("vide", lambda xs: xs[-1], [1.0, 2.0, 3.0], historique_live=H)
    assert s.stable is False
    assert s.raison == "SERIE_TROP_COURTE"
    assert s.n_points == 0
