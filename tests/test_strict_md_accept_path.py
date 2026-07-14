"""Proof that the STRICT MD thresholds (6000ms / 35bps / 12bps / 0.5) still ACCEPT
a genuinely clean real signal — so the flat equity is 'no clean signal yet', not a
broken gate. Pure function, no network. Read-only, simulation-only.
"""

from __future__ import annotations

from pathlib import Path

from hl_observer.copying.realtime_magic_score import (
    RealtimeCopyRiskConfig,
    RealtimeCopyScoreInput,
    score_realtime_copy_candidate,
)
from hl_observer.edge.edge_source import ENV_CHEMIN_TABLE, vider_le_cache
from hl_observer.edge.measured_edge_table import Features, Observation, construire

# Exactly the launcher / MD thresholds.
STRICT_MD = RealtimeCopyRiskConfig(
    min_edge_required_bps=35.0,
    max_signal_age_ms=6000,
    max_copy_degradation_bps=12.0,
    min_liquidity_score=0.5,
)


def _table_qui_mesure(edge_bps: float, tmp_path: Path, monkeypatch) -> Path:
    """Pose une table MESUREE (porte Q1) qui dit `edge_bps`, et branche le scoreur dessus.

    ⚠️ 2e REECRITURE, LE 2026-07-13 -- ET C'EST LA MEME LECON, DEUX FOIS DE SUITE.
    La 1re version (12/07) posait `leader_expected_edge_bps=10` : un levier deja debranche.
    Le correctif d'alors a ecrit une table... dans `HYPERSMART_EDGE_CALIBRATION_PATH`, c'est-a-dire
    dans la DEUXIEME table (`edge.empirical_edge`) -- celle que #594 vient de retirer du chemin de
    decision. Le test tirait donc, une fois de plus, sur un levier debranche : il « passait » sans
    rien prouver, jusqu'a ce que #594 le rende rouge.

    Une seule porte existe maintenant : `edge.edge_source` -> `HYPERSMART_EDGE_TABLE_PATH`.
    C'est elle qu'on pilote ici. *Un test qui tire sur un levier debranche ne prouve rien --
    et il est pire qu'absent, car il rassure.*
    """
    obs = [
        Observation(
            features=Features(
                strategie="COPY", coin="BTC", direction="LONG",
                signal_age_ms=200.0, leader_score=90.0, consensus_wallets=3.0,
            ),
            markout_bps=edge_bps,
            signal_ms=0.0,
        )
        for _ in range(200)
    ]
    table = construire(obs, horizon_ms=30_000, min_echantillons=30, source="TEST_FIXTURE")
    p = tmp_path / "table_edge_TEST_FIXTURE.json"
    p.write_text(table.vers_json(), encoding="utf-8")
    monkeypatch.setenv(ENV_CHEMIN_TABLE, str(p))
    vider_le_cache()
    return p


def _signal(**over):
    base = dict(
        action_type="OPEN_LONG", direction="LONG",
        leader_expected_edge_bps=120.0, leader_consistency_factor=1.0,
        signal_age_ms=200, consensus_wallets=3, liquidity_score=0.95,
        leader_score=90.0, leader_reference_price=100.0, current_mid=100.0,
        leader_notional_usdt=50.0, current_open_exposure_usdt=0.0,
        current_open_positions=0, max_open_positions=5,
    )
    base.update(over)
    return RealtimeCopyScoreInput(**base)


def test_clean_signal_is_accepted_under_strict_md():
    score = score_realtime_copy_candidate(_signal(), config=STRICT_MD)
    assert score.accepted is True, f"clean signal rejected: {score.refusal_reasons}"
    assert score.decision == "ACCEPT_LOCAL_SIMULATION"
    assert score.edge_remaining_bps >= 35.0
    assert score.copy_degradation_bps <= 12.0


def test_stale_signal_rejected_exactly_like_dashboard():
    score = score_realtime_copy_candidate(_signal(signal_age_ms=10_000), config=STRICT_MD)
    assert score.accepted is False
    assert "STALE_SIGNAL" in score.refusal_reasons


def test_low_edge_rejected_like_dashboard(tmp_path, monkeypatch):
    """UN EDGE FAIBLE DOIT ETRE REFUSE -- et on le pilote la ou l'edge VIT (la table Q1)."""
    _table_qui_mesure(10.0, tmp_path, monkeypatch)

    score = score_realtime_copy_candidate(_signal(coin="BTC"), config=STRICT_MD)
    assert score.accepted is False, (
        "un edge MESURE de 10 bps ne couvre pas un seuil de 35 bps : le refus est obligatoire"
    )
    assert "EDGE_REMAINING_TOO_LOW" in score.refusal_reasons


def test_l_edge_porte_par_le_SIGNAL_n_a_plus_aucun_pouvoir(tmp_path, monkeypatch):
    """LE CLIQUET DE Q1 : meme un edge de 5 000 bps sur le signal ne doit rien ouvrir
    si la table mesure 10 bps. Si ce test tombe, la formule a repris la main -- et avec
    elle, la possibilite de fabriquer un edge pour s'autoriser une entree.
    """
    _table_qui_mesure(10.0, tmp_path, monkeypatch)

    score = score_realtime_copy_candidate(
        _signal(coin="BTC", leader_expected_edge_bps=5_000.0), config=STRICT_MD
    )
    assert score.accepted is False, (
        "un signal s'est declare 5 000 bps d'edge et a ete cru. La table dit 10 bps. "
        "C'est exactement le mecanisme des 3 edges fabriques qu'on a passe des semaines a tuer."
    )


def test_illiquid_rejected_like_dashboard():
    score = score_realtime_copy_candidate(_signal(liquidity_score=0.1), config=STRICT_MD)
    assert score.accepted is False
    assert "LIQUIDITY_TOO_LOW" in score.refusal_reasons
