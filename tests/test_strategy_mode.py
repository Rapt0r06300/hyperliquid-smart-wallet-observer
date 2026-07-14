"""Attribution du moteur GRINDER / SNIPER (2026-07-11).

CONSTAT DE DEPART : les deux moteurs **n'existaient pas dans le code**. Le mot "sniper"
n'apparaissait que dans une ligne de JavaScript du dashboard, qui devinait le mode cote navigateur.
Aucun champ `strategy_mode` nulle part. Tous les trades passaient par le meme chemin.

Sans attribution fiable, il est IMPOSSIBLE de repondre a "quelle part de la perte vient du
Grinder ?" -- c'est le prerequis de tout le reste.

Aucun ordre reel.
"""
from __future__ import annotations

from hl_observer.strategies.strategy_mode import (
    GRINDER,
    SNIPER,
    UNKNOWN_LEGACY,
    classify,
    classify_event,
    stamp,
)


# ---------------------------------------------------------------- GRINDER

def test_the_mechanical_strategies_are_grinder():
    """Funding, arbitrage, grid, market making : leur rentabilite ne depend d'AUCUNE prediction."""
    for sid in ("funding_delta_neutral_paper", "ext_jack_hl_arbitrage_spread",
                "ws_price_discrepancy_paper", "triangular_paper_detection",
                "grid_market_maker", "ext_hl_drift_funding_spread"):
        assert classify(strategy_id=sid) == GRINDER, f"{sid} devrait etre un GRINDER"


# ---------------------------------------------------------------- SNIPER

def test_the_copy_strategies_are_sniper():
    """Copier un leader = pari directionnel sur un signal rare, qui doit etre FRAIS."""
    for sid in ("copy_conflict_resolved_follow", "ext_rezzecup_whale_mirror_primary",
                "distilled_whale_consensus_paper", "fresh_opportunity_cluster",
                "ext_tony_autonomous_sltp_priority"):
        assert classify(strategy_id=sid) == SNIPER, f"{sid} devrait etre un SNIPER"


def test_an_identified_leader_implies_a_copy():
    """Sans famille reconnaissable, un LEADER identifie signe une copie."""
    assert classify(strategy_id="", leader_wallet="0x" + "a" * 40) == SNIPER


def test_a_placeholder_wallet_is_not_a_leader():
    for faux in ("", "0x", "__consensus__", "none", None):
        assert classify(strategy_id="", leader_wallet=faux) == UNKNOWN_LEGACY


# ---------------------------------------------------------------- l'honnetete du classement

def test_what_we_cannot_know_is_marked_unknown_not_guessed():
    """REGLE DE VERITE : on ne devine JAMAIS en silence. L'inconnu est etiquete comme tel."""
    assert classify() == UNKNOWN_LEGACY
    assert classify(strategy_id="mystere_42") == UNKNOWN_LEGACY
    assert classify(strategy_id=None, source=None, position_mode=None) == UNKNOWN_LEGACY


def test_a_mechanical_strategy_triggered_by_a_leader_stays_a_grinder():
    """Un funding-arb declenche par un signal de copie reste un GRINDER : son edge est structurel."""
    assert classify(strategy_id="funding_arb_from_whale_copy") == GRINDER


def test_the_signal_age_never_decides_the_engine():
    """Un signal VIEUX reste un signal de copie -- c'est meme le probleme du Sniper.

    L'age sert a JUGER un trade, jamais a l'ETIQUETER. Confondre les deux masquerait
    precisement ce qu'on cherche a mesurer.
    """
    for age in (0, 1_000, 60_000, 3_600_000):
        assert classify(strategy_id="copy_conflict_resolved_follow", signal_age_ms=age) == SNIPER
        assert classify(strategy_id="funding_delta_neutral_paper", signal_age_ms=age) == GRINDER


# ---------------------------------------------------------------- sur les evenements du ledger

def test_a_real_ledger_event_is_classified():
    entree = {
        "coin": "HYPE", "leader_side": "SHORT",
        "bot_replay_action": "FUSION_PAPER_ENTRY",
        "reason": "EXTERNAL_GITHUB_FUSION_ACCEPTED_PAPER_ONLY",
        "wallet_address": "0x7b7f72a28fe109fa703eeed7984f2a8a68fedee2",
    }
    # aucune famille dans le texte, mais un vrai leader -> copie
    assert classify_event(entree) == SNIPER


def test_an_already_stamped_mode_is_authoritative():
    """Un mode DEJA POSE fait foi : on ne re-devine jamais par-dessus un fait etabli."""
    e = {"strategy_mode": GRINDER, "strategy_id": "copy_whale_mirror"}   # texte "copy" ignore
    assert classify_event(e) == GRINDER


def test_stamp_writes_the_mode_in_place():
    e = {"strategy_id": "funding_delta_neutral_paper"}
    stamp(e)
    assert e["strategy_mode"] == GRINDER
    e2 = {"strategy_id": "copy_conflict_resolved_follow"}
    stamp(e2)
    assert e2["strategy_mode"] == SNIPER


def test_classify_never_crashes_on_garbage():
    for bad in (None, "", [], 42, {"x": object()}):
        assert classify_event(bad) in {GRINDER, SNIPER, UNKNOWN_LEGACY}  # type: ignore[arg-type]
