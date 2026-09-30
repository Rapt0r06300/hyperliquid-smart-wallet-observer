"""LE BIAIS DIRECTIONNEL V9 : ce qu'il a le droit de faire, et ce qu'il n'a PLUS le droit de faire.

REECRIT LE 2026-07-13 (#594). Ce fichier affirmait : « un biais positif AUGMENTE l'edge ».
C'etait vrai, et c'etait le probleme. Le biais est un terme ADDITIF INVENTE (borne a +-10 bps,
issu d'un modele de tendance) : sur un edge **MESURE**, l'ajouter revient a fabriquer du
rendement par-dessus une mesure -- exactement le mecanisme des 3 edges fabriques.

Depuis #594, la regle est absolue :

    edge MESURE  ->  edge_net = edge_mesure - couts.  RIEN d'autre.
                     Pas de fraicheur, pas de consensus, pas de biais, pas de bonus.
    edge FABRIQUE ->  mode A/B EXPLICITE (HYPERSMART_EDGE_SOURCE=formule), estampille
                     `fabrique=True`, ou l'ancienne ponderation survit A L'IDENTIQUE pour que
                     la comparaison reste valable.

Ce fichier teste donc les DEUX mondes -- et surtout, il verrouille le fait que dans le monde
normal, le biais **n'a aucun pouvoir**. Tester le biais uniquement dans le monde ou il est
neutralise ne prouverait rien : *un garde-fou qui ne peut pas echouer ne garde rien.*

Paper-only. Aucun ordre reel.
"""

import pytest

from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)
from hl_observer.edge.bias_model import bias_from_closes
from hl_observer.features.direction import multi_tf_direction


def _input(**over):
    base = dict(
        action_type="ADD",
        direction="LONG",
        leader_expected_edge_bps=60.0,
        leader_consistency_factor=1.0,
        signal_age_ms=2000,
        consensus_wallets=3,
        liquidity_score=0.9,
        leader_score=80.0,
        leader_reference_price=100.0,
        current_mid=100.0,
        leader_notional_usdt=50.0,
        current_open_exposure_usdt=0.0,
        current_open_positions=0,
        max_open_positions=6,
    )
    base.update(over)
    return RealtimeCopyScoreInput(**base)


_CFG = RealtimeCopyRiskConfig(
    min_edge_required_bps=10.0, max_signal_age_ms=30_000, max_copy_degradation_bps=40.0
)


@pytest.fixture
def mode_formule(monkeypatch):
    """Le mode A/B EXPLICITE. Tout ce qui en sort est estampille `fabrique=True`."""
    monkeypatch.setenv("HYPERSMART_EDGE_SOURCE", "formule")
    return True


# ====================================================== 1. LE MONDE NORMAL (edge MESURE)


def test_default_bias_is_neutral():
    s0 = score_realtime_copy_candidate(_input(), config=_CFG)
    sb = score_realtime_copy_candidate(_input(directional_bias_bps=0.0), config=_CFG)
    assert s0.edge_remaining_bps == sb.edge_remaining_bps


def test_LE_BIAIS_N_A_AUCUN_POUVOIR_SUR_UN_EDGE_MESURE():
    """🔴 LE VERROU DE #594, DANS SON CAS LE PLUS TENTANT.

    Un biais de +10 bps (le maximum) ne doit PAS pouvoir remonter un edge mesure. Sinon il
    suffirait d'un modele de tendance optimiste pour s'autoriser une entree que la MESURE
    refuse -- c'est-a-dire pour fabriquer un edge, une 4e fois.
    """
    sans = score_realtime_copy_candidate(_input(directional_bias_bps=0.0), config=_CFG)
    avec = score_realtime_copy_candidate(_input(directional_bias_bps=10.0), config=_CFG)
    contre = score_realtime_copy_candidate(_input(directional_bias_bps=-10.0), config=_CFG)

    assert avec.edge_remaining_bps == sans.edge_remaining_bps == contre.edge_remaining_bps, (
        "le biais directionnel deplace encore un edge MESURE. Un terme INVENTE (+-10 bps, issu "
        "d'un modele de tendance) s'ajoute a une mesure : c'est le mecanisme meme des edges "
        "fabriques. Sur un edge mesure, on ne fait qu'UNE chose : soustraire les couts."
    )


def test_meme_un_biais_ABSURDE_ne_deplace_pas_un_edge_MESURE():
    """Ceinture et bretelles : 10 000 bps de biais, et l'edge mesure ne bouge pas d'un poil."""
    normal = score_realtime_copy_candidate(_input(directional_bias_bps=0.0), config=_CFG)
    absurde = score_realtime_copy_candidate(_input(directional_bias_bps=10_000.0), config=_CFG)
    assert absurde.edge_remaining_bps == normal.edge_remaining_bps


# ====================================================== 2. LE MODE A/B (edge FABRIQUE, declare)


def test_en_mode_FORMULE_le_biais_reste_additif_borne_et_exact(mode_formule):
    """La comparaison A/B n'a de sens que si l'ancien chemin se comporte EXACTEMENT comme avant.

    C'est ici -- et NULLE PART AILLEURS -- que le biais garde son pouvoir. Chaque decision issue
    de ce mode porte `fabrique=True` / EDGE_FABRIQUE_FORMULE dans son contexte, ses logs et le
    dashboard. On peut mentir a la machine ; on ne se ment plus a soi-meme.
    """
    neg = score_realtime_copy_candidate(_input(directional_bias_bps=-8.0), config=_CFG)
    zero = score_realtime_copy_candidate(_input(directional_bias_bps=0.0), config=_CFG)
    pos = score_realtime_copy_candidate(_input(directional_bias_bps=8.0), config=_CFG)

    assert neg.edge_remaining_bps < zero.edge_remaining_bps < pos.edge_remaining_bps
    # additif et exact (le biais n'est PAS multiplie par la fraicheur)
    assert round(pos.edge_remaining_bps - zero.edge_remaining_bps, 6) == 8.0


def test_en_mode_FORMULE_le_biais_reste_BORNE_a_10_bps(mode_formule):
    huge = score_realtime_copy_candidate(_input(directional_bias_bps=10_000.0), config=_CFG)
    bounded = score_realtime_copy_candidate(_input(directional_bias_bps=10.0), config=_CFG)
    assert huge.edge_remaining_bps == bounded.edge_remaining_bps  # clampe a +10


def test_end_to_end_trend_aligned_bias_helps(mode_formule):
    """Le modele de biais lui-meme reste teste de bout en bout -- dans le seul monde ou il agit."""
    up = [float(i) for i in range(1, 60)]
    mtf = multi_tf_direction(up, up)
    bias = bias_from_closes(direction_side="LONG", closes_fast_tf=up, closes_slow_tf=up)
    assert bias.bias_bps > 0 and mtf.combined == "UP"

    aligned = score_realtime_copy_candidate(_input(directional_bias_bps=bias.bias_bps), config=_CFG)
    neutral = score_realtime_copy_candidate(_input(directional_bias_bps=0.0), config=_CFG)
    assert aligned.edge_remaining_bps > neutral.edge_remaining_bps
