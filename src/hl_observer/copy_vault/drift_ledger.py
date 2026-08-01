"""[COPY-VAULT #79] DRIFT LEDGER : conserver la QUANTITÉ et la RAISON de tout écart entre l'exposition cible et
l'exposition réelle — rounding, liquidity, skipped event, latency, risk cap. Sans ce registre, la dérive de
réplication est invisible et on ne sait pas si elle vient d'un bug ou d'une contrainte légitime. Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

ROUNDING = "ROUNDING"
LIQUIDITY = "LIQUIDITY"
SKIPPED_EVENT = "SKIPPED_EVENT"
LATENCY = "LATENCY"
RISK_CAP = "RISK_CAP"
RAISONS = (ROUNDING, LIQUIDITY, SKIPPED_EVENT, LATENCY, RISK_CAP)


class DriftLedger:
    """Registre des écarts cible↔réel, ventilés par raison. `resume` totalise le drift et son détail."""

    def __init__(self) -> None:
        self._entrees: list[dict[str, Any]] = []

    def enregistrer(self, coin: str, quantite: Any, raison: str) -> dict[str, Any]:
        """Enregistre un écart. Raison hors taxonomie → conservée sous 'AUTRE' (jamais silencieusement ignorée)."""
        if not isinstance(quantite, (int, float)):
            return {"ok": False, "raison": "QUANTITE_INVALIDE"}
        r = raison if raison in RAISONS else "AUTRE"
        self._entrees.append({"coin": str(coin).upper(), "quantite": float(quantite), "raison": r})
        return {"ok": True, "raison_enregistree": r}

    def resume(self) -> dict[str, Any]:
        par_raison: dict[str, float] = {}
        total = 0.0
        for e in self._entrees:
            par_raison[e["raison"]] = round(par_raison.get(e["raison"], 0.0) + abs(e["quantite"]), 12)
            total += abs(e["quantite"])
        return {"drift_total": round(total, 12), "par_raison": par_raison, "n_entrees": len(self._entrees)}


__all__ = ["DriftLedger", "ROUNDING", "LIQUIDITY", "SKIPPED_EVENT", "LATENCY", "RISK_CAP", "RAISONS"]
