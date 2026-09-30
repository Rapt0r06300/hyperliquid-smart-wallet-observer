"""AUCUNE ENTRÉE SANS PREUVE COMPLÈTE (2026-07-11) — Phase 6 du brief.

CE QUE LES LOGS DISAIENT :

    "Entree virtuelle acceptee en simulation locale apres controles edge/couts/risque."

CE QUE LE LEDGER CONTENAIT AU MEME MOMENT :

    signal_age_ms = null   edge_remaining_bps = null   spread_bps = null
    liquidity_score = null   v9_decision = null   strategy_mode = null

**Le systeme AFFIRMAIT que les controles avaient reussi, alors que les preuves correspondantes
etaient absentes.** Ce n'est pas un detail de journalisation : un controle sans trace n'est pas un
controle, c'est une croyance. Et c'est precisement ce silence qui a permis a un edge FABRIQUE
(`dominance x 45`) et a un carnet IMAGINAIRE (spread constant de 6 bps) de passer, des mois durant,
pour de la rigueur.

CE MODULE POSE LE CONTRAT :

    Un champ obligatoire manquant  ->  NO_TRADE / NO_TRADE_DATA_GAP.

Et il INTERDIT la substitution silencieuse : remplacer une donnee absente par zero, par le prix du
leader, par un vieux mid, par un carnet perime ou par "une valeur raisonnable" revient a FABRIQUER
la donnee. Un repli est autorise -- mais il doit etre **DECLARE**, et il degrade la qualite.

PUR, sans I/O. Aucun ordre reel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

# --------------------------------------------------------------------------------------------
# LE CONTRAT. Chaque champ existe parce que son ABSENCE a deja coute de l'argent.
CHAMPS_OBLIGATOIRES: tuple[str, ...] = (
    # qui decide, et selon quelle regle
    "strategy_mode",
    "strategy_id",
    # d'ou vient le signal, et QUAND
    "signal_id",
    "source_type",
    "source_event_time_ms",
    "local_receive_time_ms",
    "signal_age_ms",             # <- etait `null` sur les 21 entrees de la session analysee
    # sur quoi on trade
    "coin",
    "side",
    "current_mid",
    # ce que coute le trade -- LE VRAI CARNET, pas une constante
    "spread_bps",
    "slippage_estimate_bps",
    "fees_bps",
    "liquidity_score",
    # ce qu'on espere en tirer, et D'OU VIENT CE CHIFFRE
    "gross_expected_edge_bps",
    "edge_remaining_bps",        # <- etait `null` : on ouvrait sans savoir
    "edge_is_empirical",         # <- LE champ qui aurait tout revele plus tot
    # la tracabilite
    "data_quality_status",
    "decision",
    "reason_codes",
)

# Un champ peut etre legitimement None SI et seulement SI le contexte le justifie
# (ex: pas de funding connu pour ce coin). Ces champs-la sont OPTIONNELS, mais leur absence
# doit rester VISIBLE -- jamais remplacee par 0.
CHAMPS_OPTIONNELS: tuple[str, ...] = (
    "funding_cost_bps",
    "latency_degradation_bps",
    "leg_risk_bps",             # arbitrage uniquement
    "depth_bid_usdc",
    "depth_ask_usdc",
    "volatility_context",
    "feature_hash",
    "evidence_hash",
)

REFUS_DONNEE_MANQUANTE = "NO_TRADE_DATA_GAP"

# Substitutions INTERDITES : une donnee absente remplacee par une valeur FAVORABLE.
# (le prix du leader comme notre prix d'entree, c'etait exactement ca -- et dans 8 cas sur 20
#  le bot entrait a un prix MEILLEUR que le marche, ce qui est physiquement impossible.)
QUALITE_LIVE = "LIVE"
QUALITE_DEGRADEE = "DEGRADED_FALLBACK"
QUALITE_INSUFFISANTE = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class VerdictContrat:
    complet: bool
    champs_manquants: tuple[str, ...]
    decision: str
    reason_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "contrat_complet": self.complet,
            "champs_manquants": list(self.champs_manquants),
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
        }


def _manquant(valeur: Any) -> bool:
    """Une valeur ABSENTE. Attention : `False` et `0.0` sont des valeurs VALIDES."""
    if valeur is None:
        return True
    if isinstance(valeur, str) and not valeur.strip():
        return True
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return True          # NaN / inf : une non-mesure deguisee en nombre
    return False


def verifier_contrat(preuve: Mapping[str, Any] | None) -> VerdictContrat:
    """Le contrat est-il rempli ? Sinon : NO_TRADE. **Deny-by-default.**

    On ne demande pas au systeme d'etre parfait -- on lui demande de DIRE ce qu'il ne sait pas.
    """
    if not isinstance(preuve, Mapping):
        return VerdictContrat(
            complet=False,
            champs_manquants=CHAMPS_OBLIGATOIRES,
            decision="NO_TRADE",
            reason_codes=(REFUS_DONNEE_MANQUANTE,),
        )

    manquants = tuple(c for c in CHAMPS_OBLIGATOIRES if _manquant(preuve.get(c)))
    if manquants:
        return VerdictContrat(
            complet=False,
            champs_manquants=manquants,
            decision="NO_TRADE",
            reason_codes=(REFUS_DONNEE_MANQUANTE,) + tuple(f"MISSING_{c.upper()}" for c in manquants),
        )

    codes: list[str] = []

    # Un edge NON EMPIRIQUE remplit le contrat au sens des champs... mais reste un chiffre invente.
    # Le contrat de DONNEES ne le refuse pas ici (c'est le role du gate d'empiricite) -- il le
    # SIGNALE, pour qu'aucun rapport ne puisse le presenter comme une mesure.
    if preuve.get("edge_is_empirical") is not True:
        codes.append("EDGE_NOT_EMPIRICAL")

    qualite = str(preuve.get("data_quality_status") or "")
    if qualite.upper().startswith("DEGRADED") or "FALLBACK" in qualite.upper():
        codes.append("DEGRADED_INPUTS_FALLBACK_USED")

    return VerdictContrat(
        complet=True,
        champs_manquants=(),
        decision=str(preuve.get("decision") or "PENDING"),
        reason_codes=tuple(codes),
    )


def contract_refusal(preuve: Mapping[str, Any] | None) -> str:
    """"" = le contrat est rempli. Sinon : le motif de refus (utilisable comme gate)."""
    v = verifier_contrat(preuve)
    return "" if v.complet else REFUS_DONNEE_MANQUANTE


__all__ = [
    "CHAMPS_OBLIGATOIRES",
    "CHAMPS_OPTIONNELS",
    "QUALITE_DEGRADEE",
    "QUALITE_INSUFFISANTE",
    "QUALITE_LIVE",
    "REFUS_DONNEE_MANQUANTE",
    "VerdictContrat",
    "contract_refusal",
    "verifier_contrat",
]
