"""CHANTIER #3 — TWAP réels : collecte userTwapSliceFills + userTwapHistory (endpoints officiels HL) et
ALIMENTE le modèle residual-flow / metaorder hazard.

Chaque slice-fill (executedSz, executedNtl, ts) est parsée en record canonique ; on accumule par twap_id la
fraction exécutée (cumulé / taille totale), le stade (FIRST_SLICE/EARLY/MIDDLE/LATE) et on branche directement
research.metaorder_hazard (flux_residuel + remaining_flow_probability). Sans source → BLOCKED_EXTERNAL, aucune
slice inventée. 0 réseau ici, 0 ordre réel.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.research.metaorder_hazard import flux_residuel, remaining_flow_probability

BLOCKED = "BLOCKED_EXTERNAL"
_LONG = ("B", "BUY", "LONG", "BID")


def _num(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def slice_canonique(s: Mapping[str, Any]) -> dict[str, Any] | None:
    """Parse un userTwapSliceFill → canonique. None si champs essentiels absents."""
    tid = s.get("twap_id", s.get("oid", s.get("twapId")))
    coin = s.get("coin")
    if tid is None or not coin:
        return None
    side = str(s.get("side", s.get("dir", ""))).strip().upper()
    return {"twap_id": str(tid), "coin": str(coin),
            "side": (1.0 if any(side.startswith(x) for x in _LONG) else -1.0) if side else None,
            "executed_sz": _num(s.get("executedSz", s.get("executed_sz"))),
            "executed_ntl": _num(s.get("executedNtl", s.get("executed_ntl"))),
            "total_size": _num(s.get("total_size", s.get("sz", s.get("totalSz")))),
            "ts_ms": s.get("ts_ms", s.get("time")), "state": s.get("state")}


def _stade(frac: float, premier: bool) -> str:
    if premier:
        return "FIRST_SLICE"
    if frac < 0.15:
        return "EARLY"
    if frac < 0.6:
        return "MIDDLE"
    return "LATE"


def collecter_twap(slices: Iterable[Mapping[str, Any]] | None, out_path: str | None = None) -> dict[str, Any]:
    """Parse les slice-fills, accumule la fraction exécutée par twap_id et branche le modèle hazard. Écrit un
    JSONL canonique si `out_path` fourni. Sans slices → BLOCKED_EXTERNAL."""
    if not slices:
        return {"statut": BLOCKED, "manque": "userTwapSliceFills / userTwapHistory (WS+REST) cote user",
                "real_execution": False}
    cumule: dict[str, float] = {}
    vus_par_twap: dict[str, int] = {}
    records: list[dict[str, Any]] = []
    fh = open(out_path, "a", encoding="utf-8") if out_path else None
    try:
        for raw in slices:
            sc = slice_canonique(raw)
            if sc is None or sc["executed_sz"] is None:
                continue
            tid = sc["twap_id"]
            premier = tid not in cumule
            cumule[tid] = cumule.get(tid, 0.0) + sc["executed_sz"]
            vus_par_twap[tid] = vus_par_twap.get(tid, 0) + 1
            total = sc["total_size"]
            frac = (cumule[tid] / total) if isinstance(total, (int, float)) and total > 0 else None
            sc["executed_fraction"] = (round(frac, 6) if frac is not None else None)
            if frac is not None:
                sc["flux_residuel"] = flux_residuel(total, frac)
                sc["hazard"] = remaining_flow_probability(stade=_stade(frac, premier), executed_fraction=frac)
            records.append(sc)
            if fh:
                fh.write(json.dumps(sc, ensure_ascii=False) + "\n")
    finally:
        if fh:
            fh.close()
    return {"statut": "OK", "n_slices": len(records), "n_twaps": len(cumule),
            "exemple": (records[-1] if records else None), "real_execution": False}


__all__ = ["slice_canonique", "collecter_twap", "BLOCKED"]
