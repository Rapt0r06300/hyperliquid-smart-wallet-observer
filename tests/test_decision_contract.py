"""AUCUNE ENTRÉE SANS PREUVE COMPLÈTE (2026-07-11) — Phase 6 du brief.

CE QUE LES LOGS DISAIENT :

    « Entrée virtuelle acceptée en simulation locale après contrôles edge/coûts/risque. »

CE QUE LE LEDGER CONTENAIT AU MÊME MOMENT :

    signal_age_ms = null   edge_remaining_bps = null   spread_bps = null   v9_decision = null

**Le système affirmait que les contrôles avaient réussi, alors que les preuves étaient absentes.**

Ce n'est pas un défaut de journalisation. C'est ce silence qui a permis à un edge **fabriqué**
(`dominance × 45`) et à un carnet **imaginaire** (spread constant de 6 bps) de passer, des mois
durant, pour de la rigueur.

Règle : **un champ obligatoire manquant → NO_TRADE.** Et interdiction absolue de remplacer une
donnée absente par une valeur favorable.

Aucun ordre réel.
"""
from __future__ import annotations

from hl_observer.signals.decision_contract import (
    CHAMPS_OBLIGATOIRES,
    REFUS_DONNEE_MANQUANTE,
    contract_refusal,
    verifier_contrat,
)


def _preuve_complete(**surcharges) -> dict:
    base = {
        "strategy_mode": "SNIPER", "strategy_id": "copy_consensus",
        "signal_id": "sig-1", "source_type": "userFills",
        "source_event_time_ms": 1_800_000_000_000, "local_receive_time_ms": 1_800_000_000_500,
        "signal_age_ms": 500,
        "coin": "BTC", "side": "LONG", "current_mid": 100.0,
        "spread_bps": 1.2, "slippage_estimate_bps": 2.0, "fees_bps": 4.5,
        "liquidity_score": 0.9,
        "gross_expected_edge_bps": 30.0, "edge_remaining_bps": 22.3,
        "edge_is_empirical": True,
        "data_quality_status": "LIVE_BOOK",
        "decision": "ACCEPT", "reason_codes": [],
    }
    base.update(surcharges)
    return base


# ------------------------------------------------------------------ le cas réel qui a coûté cher

def test_the_ACTUAL_ledger_entry_of_the_losing_session_is_REFUSED():
    """LA VRAIE ENTRÉE. Elle affirmait « contrôles réussis » avec TOUTES les preuves à null.
    Elle doit être refusée — et le motif doit nommer CHAQUE champ manquant."""
    entree_reelle = {
        "coin": "HYPE", "side": "SHORT", "decision": "ACCEPT",
        "signal_age_ms": None, "edge_remaining_bps": None, "spread_bps": None,
        "liquidity_score": None, "strategy_mode": None,
    }
    v = verifier_contrat(entree_reelle)
    assert v.complet is False
    assert v.decision == "NO_TRADE"
    assert REFUS_DONNEE_MANQUANTE in v.reason_codes
    assert "signal_age_ms" in v.champs_manquants
    assert "edge_remaining_bps" in v.champs_manquants
    assert "MISSING_SIGNAL_AGE_MS" in v.reason_codes


def test_a_complete_proof_passes():
    v = verifier_contrat(_preuve_complete())
    assert v.complet is True
    assert v.champs_manquants == ()


# ------------------------------------------------------------------ deny-by-default

def test_no_proof_at_all_means_no_trade():
    for rien in (None, {}, "pas un dict", 42):
        v = verifier_contrat(rien)  # type: ignore[arg-type]
        assert v.complet is False
        assert v.decision == "NO_TRADE"


def test_every_single_mandatory_field_is_actually_enforced():
    """On retire les champs UN PAR UN : chacun doit, à lui seul, provoquer un NO_TRADE.
    Un champ « obligatoire » qui n'est jamais vérifié n'est pas obligatoire."""
    for champ in CHAMPS_OBLIGATOIRES:
        preuve = _preuve_complete()
        preuve[champ] = None
        v = verifier_contrat(preuve)
        assert v.complet is False, f"le champ obligatoire « {champ} » n'est pas contrôlé"
        assert champ in v.champs_manquants


# ------------------------------------------------------------------ les valeurs valides ne sont pas des trous

def test_zero_and_false_are_VALID_values_not_missing_ones():
    """PIÈGE CLASSIQUE : `if not valeur` traiterait un spread de 0 bps ou un edge de 0
    comme une donnée absente. Un zéro MESURÉ est une information."""
    v = verifier_contrat(_preuve_complete(spread_bps=0.0, edge_remaining_bps=0.0,
                                          signal_age_ms=0))
    assert v.complet is True, "un zéro mesuré a été pris pour une donnée manquante"


def test_a_NaN_is_a_missing_value_not_a_number():
    """NaN, c'est une non-mesure déguisée en nombre. Il ne doit tromper personne."""
    v = verifier_contrat(_preuve_complete(edge_remaining_bps=float("nan")))
    assert v.complet is False
    assert "edge_remaining_bps" in v.champs_manquants


def test_an_empty_string_is_a_missing_value():
    v = verifier_contrat(_preuve_complete(strategy_mode="   "))
    assert v.complet is False


# ------------------------------------------------------------------ ce qui est signalé, sans bloquer

def test_a_fabricated_edge_is_FLAGGED_even_when_the_fields_are_all_present():
    """Le contrat de DONNÉES ne juge pas la qualité de l'edge (c'est le rôle du gate
    d'empiricité) — mais il le SIGNALE, pour qu'aucun rapport ne le présente comme une mesure."""
    v = verifier_contrat(_preuve_complete(edge_is_empirical=False))
    assert v.complet is True                       # les champs sont là...
    assert "EDGE_NOT_EMPIRICAL" in v.reason_codes  # ...mais on ne s'y trompe pas


def test_a_degraded_fallback_is_named():
    """Un repli est autorisé — jamais silencieux."""
    v = verifier_contrat(_preuve_complete(data_quality_status="DEGRADED_CONSTANT_COSTS_FALLBACK"))
    assert v.complet is True
    assert "DEGRADED_INPUTS_FALLBACK_USED" in v.reason_codes


# ------------------------------------------------------------------ le gate

def test_the_gate_refuses_an_incomplete_proof():
    assert contract_refusal({"coin": "BTC"}) == REFUS_DONNEE_MANQUANTE
    assert contract_refusal(_preuve_complete()) == ""
