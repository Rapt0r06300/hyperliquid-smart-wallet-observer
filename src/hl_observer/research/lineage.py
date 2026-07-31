"""ALPHA P59 — LINEAGE source→feature→alpha + détection de LEAKAGE (causalité).

Pour chaque feature : source, timestamp de source, normalisation, transformation, version, statut de causalité.
Détection immédiate de fuite : une feature dont un input a un timestamp POSTÉRIEUR à l'instant de décision
utilise du futur → `LEAKAGE`. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def tracer_feature(nom: str, *, source: str, source_ts_ms: Any, decision_ts_ms: Any,
                   normalisation: str = "none", transformation: str = "identity", version: str = "v1") -> dict[str, Any]:
    """Trace une feature ; statut CAUSAL si source_ts <= decision_ts, sinon LEAKAGE."""
    causal = "INCONNU"
    if isinstance(source_ts_ms, (int, float)) and isinstance(decision_ts_ms, (int, float)):
        causal = "CAUSAL" if source_ts_ms <= decision_ts_ms else "LEAKAGE"
    return {"feature": nom, "source": source, "source_ts_ms": source_ts_ms, "decision_ts_ms": decision_ts_ms,
            "normalisation": normalisation, "transformation": transformation, "version": version,
            "causality": causal}


def auditer(features: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Audit d'un ensemble de features : liste les fuites. `ok` seulement si zéro LEAKAGE."""
    fuites = [f["feature"] for f in features if f.get("causality") == "LEAKAGE"]
    return {"n_features": len(features), "fuites": fuites, "ok": not fuites}


__all__ = ["tracer_feature", "auditer"]
