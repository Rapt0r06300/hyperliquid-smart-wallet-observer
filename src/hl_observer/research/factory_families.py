"""ALPHA P15 — registre EXHAUSTIF des familles de la Factory. Plus aucune famille oubliée ou non couverte.

Chaque famille économique/recherche est déclarée avec son module et son statut (ACTIVE / SHADOW /
BLOCKED_EXTERNAL). `run_factory` et le test de couverture s'appuient dessus pour garantir qu'AUCUNE famille
n'est ni testée ni explicitement bloquée. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

# famille -> (module de recherche, statut)
FAMILLES: dict[str, dict[str, str]] = {
    "wallet_binance_anticipation": {"module": "wallet_binance_anticipation", "statut": "ACTIVE"},
    "lead_lag": {"module": "hl_binance_leadlag", "statut": "ACTIVE"},
    "copy_wallet": {"module": "wallet_copy_edge", "statut": "ACTIVE"},
    "copy_population": {"module": "wallet_population", "statut": "ACTIVE"},
    "cross_venue": {"module": "basis_vs_latency", "statut": "ACTIVE"},
    "twap_metaorder": {"module": "metaorder_hazard", "statut": "SHADOW"},
    "ofi_microstructure": {"module": "ofi_microprice", "statut": "SHADOW"},
    "mlofi": {"module": "mlofi", "statut": "SHADOW"},
    "maker_execution": {"module": "maker_toxicity", "statut": "SHADOW"},
    "liquidations_triggers": {"module": "liquidation_flow", "statut": "SHADOW"},
    "exits": {"module": "exit_factory", "statut": "SHADOW"},
    "multi_venue": {"module": "multi_venue", "statut": "BLOCKED_EXTERNAL"},
    "l4_intent": {"module": "order_intent", "statut": "BLOCKED_EXTERNAL"},
    "hf_data": {"module": "hf_recorder", "statut": "BLOCKED_EXTERNAL"},
}


def familles_par_statut(statut: str) -> list[str]:
    return [f for f, v in FAMILLES.items() if v["statut"] == statut]


def familles_a_couvrir() -> list[str]:
    """Familles ACTIVE/SHADOW (doivent être testées) — les BLOCKED_EXTERNAL sont exemptées mais documentées."""
    return [f for f, v in FAMILLES.items() if v["statut"] in ("ACTIVE", "SHADOW")]


def verifier_exhaustivite(modules_presents: set[str]) -> dict[str, Any]:
    """Chaque famille ACTIVE/SHADOW a-t-elle son module présent ? Les BLOCKED sont listées à part."""
    manquantes = [f for f in familles_a_couvrir() if FAMILLES[f]["module"] not in modules_presents]
    return {"n_familles": len(FAMILLES), "a_couvrir": len(familles_a_couvrir()),
            "manquantes": manquantes, "bloquees": familles_par_statut("BLOCKED_EXTERNAL"),
            "exhaustif": not manquantes}


__all__ = ["FAMILLES", "familles_par_statut", "familles_a_couvrir", "verifier_exhaustivite"]
