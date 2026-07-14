"""#591 — LE GARDE-FOU AFFAME : on ne peut pas juger un marche qu'on n'a jamais regarde.

LA CHAINE, ET SON FIL COUPE
---------------------------
    NOURRISSEUR   paper_trading/vol_adjusted_barriers.py  -> MidVolEstimator.record(coin, mid)
    CONSOMMATEUR  signals/v26_entry_vetos.py:228          -> range_bps(window_s=900, min_obs=5)
                  signals/market_quality_score.py         -> quality_score(range_bps=...)
    VETO          MarketQualityBook.allowed(coin) is False -> REASON_MQ  (refus d'entree)

Le nourrisseur etait place **sous un `return` anticipe** (`if config is None or not positions`).
Autrement dit : l'estimateur n'etait alimente **que lorsqu'une position etait deja ouverte**.

Mais le consommateur pose sa question **au moment de decider une ENTREE** -- c'est-a-dire quand,
le plus souvent, il n'y a AUCUNE position. Il recevait `None`.

Et `None` ne casse rien. `quality_score()` **saute simplement** le terme de volatilite -- qui pese
+-30/35/+15 points, le plus lourd des trois. Le veto continuait donc de trancher, en classant
l'univers top-K sur la **liquidite seule**, sans jamais signaler qu'il lui manquait la moitie de
son information.

> *Un garde-fou qu'on n'alimente pas ne se tait pas : il repond quand meme, avec ce qu'il a.*

Ce fichier verrouille la seule regle qui compte ici : **on OBSERVE toujours, on DECIDE ensuite.**
Enregistrer un mark n'est pas passer un ordre. (Meme lecon que le carnet L2, #330 :
le deny-by-default protege les ORDRES, pas les OCTETS.)

Paper-only. Aucun ordre reel.
"""

from __future__ import annotations

import pytest

from hl_observer.paper_trading.vol_adjusted_barriers import (
    MidVolEstimator,
    apply_sltp_exits_vol_adjusted,
)
from hl_observer.signals.market_quality_score import quality_score


@pytest.fixture
def estimateur() -> MidVolEstimator:
    return MidVolEstimator()


def _marks(t: float) -> dict[str, float]:
    """Des marks REELS tels que le poller les fournit : tous les coins, a chaque tick."""
    return {"BTC": 100_000.0 + t, "ETH": 3_000.0 + t, "HYPE": 40.0}


# ====================================================== 1. L'INVARIANT : on observe TOUJOURS


def test_les_marks_sont_enregistres_MEME_SANS_AUCUNE_POSITION(estimateur):
    """🔴 LE TEST QUI AURAIT ATTRAPE #591.

    Zero position -- l'etat NORMAL du bot, et precisement celui dans lequel il envisage sa
    PREMIERE entree. Si l'observation s'arrete la, le veto d'entree juge a l'aveugle.
    """
    for i in range(6):
        apply_sltp_exits_vol_adjusted(
            {},                       # AUCUNE position ouverte
            [],
            _marks(float(i)),
            now_ms=(1_000 + i) * 1000,
            config=None,              # et SL/TP meme desactive : on observe quand meme
            estimator=estimateur,
        )

    rng = estimateur.range_bps("BTC", window_s=900.0, min_obs=5, now=1_006.0)
    assert rng is not None, (
        "l'estimateur de volatilite est VIDE apres 6 ticks de marks reels, uniquement parce "
        "qu'aucune position n'etait ouverte. C'est #591 : le consommateur (v26_entry_vetos) "
        "demande cette valeur au moment de decider une ENTREE -- soit, justement, a 0 position."
    )
    assert rng > 0.0


def test_l_observation_ne_depend_PAS_du_flag_de_barrieres(estimateur):
    """Le flag V26 pilote le CALCUL des barrieres, pas le DROIT de regarder le marche.

    Les confondre, c'est eteindre la collecte en croyant eteindre une strategie.
    """
    for i in range(6):
        apply_sltp_exits_vol_adjusted(
            {}, [], _marks(float(i)),
            now_ms=(2_000 + i) * 1000,
            config=None,
            env={},                   # flag ABSENT -> OFF
            estimator=estimateur,
        )
    assert estimateur.range_bps("ETH", window_s=900.0, min_obs=5, now=2_006.0) is not None


def test_un_mark_ABSURDE_n_entre_jamais_dans_l_estimateur(estimateur):
    """Observer plus n'est pas observer n'importe quoi. Un prix <= 0 ou NaN reste refuse."""
    for i in range(8):
        apply_sltp_exits_vol_adjusted(
            {}, [], {"BAD": 0.0, "NAN": float("nan"), "NEG": -5.0},
            now_ms=(3_000 + i) * 1000, config=None, estimator=estimateur,
        )
    for coin in ("BAD", "NAN", "NEG"):
        assert estimateur.range_bps(coin, window_s=900.0, min_obs=1, now=3_008.0) is None


# ====================================================== 2. POURQUOI CA COMPTAIT VRAIMENT


def test_un_range_ABSENT_ampute_SILENCIEUSEMENT_le_score_de_qualite():
    """🚩 LA RAISON POUR LAQUELLE PERSONNE N'A RALE PENDANT DES SEMAINES.

    `range_bps=None` ne leve pas, ne loggue pas, ne refuse pas. Il **saute** le terme de
    volatilite -- le plus lourd du score. Le veto REASON_MQ tranchait donc sur la liquidite seule,
    et le classement top-K etait fausse **sans le moindre signe exterieur**.
    """
    liq = 0.9
    # regime sain : +15
    sain = quality_score(range_bps=60.0, liquidity_score=liq, market_pnl_usd=None)
    # terme de volatilite SAUTE -- sans erreur, sans log, sans refus
    affame = quality_score(range_bps=None, liquidity_score=liq, market_pnl_usd=None)

    assert affame != sain, (
        "si les deux scores sont egaux, ce test ne prouve rien -- or c'est justement l'ecart "
        "silencieux entre eux qui faussait le classement top-K de l'univers"
    )
    assert sain - affame == pytest.approx(15.0), "le terme de volatilite vaut +15 en regime sain"

    # et dans un marche MORT (range trop faible), l'ecart est encore plus violent : -30 points
    mort = quality_score(range_bps=0.5, liquidity_score=liq, market_pnl_usd=None)
    assert affame - mort == pytest.approx(30.0), (
        "un marche MORT et un marche INCONNU recevaient des notes distantes de 30 points. "
        "Affame, le veto ne pouvait tout simplement pas voir la difference."
    )
