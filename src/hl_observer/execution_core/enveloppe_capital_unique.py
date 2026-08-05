"""AUD-122 — enveloppe de capital UNIQUE 1000 USD : l'exploratoire est DEDANS, jamais EN PLUS.

Les cohortes/moteurs paper (strict, experimental, ALPHA, probes...) ne doivent JAMAIS voir leurs
budgets SOMMES au-dela d'un master unique de 1000 USD. Ce checker somme les budgets engages et
SIGNALE tout depassement (aucune addition silencieuse au-dela du master). Read-only, paper.
"""
from __future__ import annotations

from typing import Mapping

ENVELOPPE_MASTER_USD = 1000.0


def verifier_enveloppe(budgets: Mapping[str, float], *, master_usd: float = ENVELOPPE_MASTER_USD) -> dict:
    """{total_engage, master, respecte, depassement, par_cohorte, raison}. respecte ssi la SOMME des
    budgets engages <= master. Un budget exploratoire ne peut donc pas s'ajouter par-dessus les 1000."""
    par = {str(k): float(v) for k, v in budgets.items()}
    total = round(sum(par.values()), 6)
    depasse = total > float(master_usd) + 1e-9
    return {"total_engage": total, "master": float(master_usd), "respecte": not depasse,
            "depassement": round(max(0.0, total - float(master_usd)), 6), "par_cohorte": par,
            "raison": ("OK" if not depasse
                       else "ENVELOPPE_DEPASSEE (budgets sommes au-dela du master 1000)")}


__all__ = ["verifier_enveloppe", "ENVELOPPE_MASTER_USD"]
