from __future__ import annotations
from typing import Any
from hyper_smart_observer.copy_mode.copy_models import NoTradeReason, DeltaAction

FRENCH_REASONS: dict[str, str] = {
    NoTradeReason.STALE_SIGNAL.value: "Signal expiré (retard trop important).",
    NoTradeReason.EDGE_REMAINING_TOO_LOW.value: "Avantage insuffisant après frais et glissement.",
    NoTradeReason.LIQUIDITY_TOO_LOW.value: "Liquidité insuffisante dans le carnet d'ordres.",
    NoTradeReason.UNKNOWN_DELTA.value: "Changement de position ambigu ou non classable.",
    NoTradeReason.NETWORK_READ_DISABLED.value: "Lecture réseau non autorisée (mode local uniquement).",
    NoTradeReason.PNL_CONCENTRATION_TOO_HIGH.value: "Performance trop dépendante d'un seul échange.",
}

FRENCH_ACTIONS: dict[str, str] = {
    DeltaAction.OPEN_LONG.value: "Ouverture Longue",
    DeltaAction.OPEN_SHORT.value: "Ouverture Courte",
    DeltaAction.ADD.value: "Ajout à la Position",
    DeltaAction.INCREASE.value: "Augmentation",
    DeltaAction.REDUCE.value: "Réduction",
    DeltaAction.CLOSE_LONG.value: "Fermeture Longue",
    DeltaAction.CLOSE_SHORT.value: "Fermeture Courte",
    DeltaAction.UNKNOWN.value: "Action Inconnue",
}

def format_french_summary(stats: dict[str, Any]) -> str:
    """Génère un résumé humain en français pour le dashboard ou les rapports CLI."""
    lines = [
        "--- RÉSUMÉ HYPERSMART ---",
        f"État : {'OPÉRATIONNEL' if stats.get('ok') else 'ALERTE'}",
        f"Leaders suivis : {stats.get('leaders_count', 0)}",
        f"Signaux détectés : {stats.get('signals_count', 0)}",
        f"Refus (No-Trade) : {stats.get('refusals_count', 0)}",
        f"PnL Paper (USDC) : {stats.get('pnl', 0.0):.2f}",
        "--------------------------"
    ]
    return "\n".join(lines)

def explain_refusal(reason: str) -> str:
    return FRENCH_REASONS.get(reason, f"Refus pour raison technique : {reason}")
