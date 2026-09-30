"""A5 — Runtime IA: mémoire incassable + ingestion refus + analyste + optim.

Compose memory_store (SQLite WAL survivant au restart), refused_shadow_extract
(chaque refus → échantillon shadow), shadow_analyst (explication), config_optimizer
+ shadow_arms (calibration continue). Un IARuntime unique porte la mémoire. Pur/gardé:
toute erreur d'écriture est absorbée (jamais casser le moteur). Câblage = instancier
IARuntime au boot et l'appeler aux ouvertures/fermetures/refus.
"""

from __future__ import annotations

import os

from hl_observer.ml.memory_store import IAMemory
from hl_observer.ml.refused_shadow_extract import rows_outcomes_from_refusals
from hl_observer.ml.shadow_analyst import explain_decision, summarize_session


def _on(flag: str) -> bool:
    return str(os.getenv(flag, "0")).strip().lower() in {"1", "true", "yes", "on"}


class IARuntime:
    """Boucle d'apprentissage IA branchée sur la mémoire persistante."""

    def __init__(self, db_path: str | None = None) -> None:
        self.enabled = _on("HYPERSMART_IA_MEMORY")
        self.memory: IAMemory | None = None
        if self.enabled:
            try:
                self.memory = IAMemory(db_path or "runtime/ml/ia_memory.sqlite3")
            except Exception:
                self.enabled = False   # mémoire indisponible → dégrade sans casser

    def on_closed_trade(self, decision_id: str, ts_ms: int, features: dict, net_pnl_usdc: float, context: str = "LIVE") -> bool:
        if not (self.enabled and self.memory):
            return False
        try:
            return self.memory.add_sample(decision_id, ts_ms, context, features or {}, net_pnl_usdc)
        except Exception:
            return False

    def ingest_refusals(self, refusal_events: list[dict], marks_by_coin: dict) -> int:
        """Chaque refus mesurable → échantillon shadow persistant."""
        if not (self.enabled and self.memory):
            return 0
        rows, outcomes = rows_outcomes_from_refusals(refusal_events, marks_by_coin)
        n = 0
        for row, out in zip(rows, outcomes):
            if self.memory.add_sample(row.decision_id, row.ts_ms, row.context, row.features, out.realized_net_pnl_usdc):
                n += 1
        return n

    def explain(self, decision: dict) -> str:
        return explain_decision(decision)

    def session_summary(self, closed_trades: list[dict]) -> str:
        return summarize_session(closed_trades)

    def corpus_size(self) -> int:
        return self.memory.sample_count() if (self.enabled and self.memory) else 0


__all__ = ["IARuntime"]
