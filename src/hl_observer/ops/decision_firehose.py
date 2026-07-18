"""FIREHOSE DE DÉCISIONS (idées #1/#2/#5) — chaque décision de CHAQUE stratégie (carry, shadow des
nouveaux modules…) devient un CANDIDAT replay, écrit dans le MÊME flux que lit le docteur replay
(runtime/replay/candidates.jsonl). Résultat : on rejoue sur des masses de décisions RÉELLES et
datées, MÊME sans ouverture réelle. Répond à « sans ouverture pas de replay ».

Le schéma du candidat est compatible avec le moteur A/B existant (coin, direction, current_mid,
recorded_at, edge_remaining_bps). On n'invente rien : une décision sans mid/edge n'est pas écrite.
PAPER only, lecture seule côté marché. Aucun ordre. Une décision journalisée n'est pas un ordre.
"""
from __future__ import annotations

from typing import Any

from hl_observer.runtime.replay_recorder import (
    CANDIDATES_MAX_BYTES, CANDIDATES_MAX_LINES, MARKS_MAX_BYTES, MARKS_MAX_LINES,
    append_replay_lines)

BASE_REPLAY = "runtime/replay"


def candidat_depuis_decision(decision: dict[str, Any], *, strategie: str, ts_s: float,
                             mid: float | None, shadow: bool = False) -> dict[str, Any] | None:
    """Convertit une décision (carry/autre) en ligne-candidat replay. None si mid absent (on ne
    fabrique pas un candidat sans prix). `direction` dérivée du funding (positif -> LONG spot)."""
    coin = str(decision.get("coin") or "").upper()
    if not coin or mid is None or float(mid) <= 0:
        return None
    funding = decision.get("funding_bps_h")
    direction = "LONG" if (funding is None or float(funding) >= 0) else "SHORT"
    edge = decision.get("gain_net_24h_bps")
    if edge is None:
        edge = decision.get("edge_remaining_bps")
    return {
        "coin": coin, "direction": direction, "current_mid": float(mid),
        "recorded_at": float(ts_s),
        "edge_remaining_bps": float(edge) if isinstance(edge, (int, float)) else None,
        "strategie": str(strategie), "accepte": bool(decision.get("viable")),
        "shadow": bool(shadow), "real_execution": False,
    }


def enregistrer_decision(root: str, decision: dict[str, Any], *, strategie: str, ts_s: float,
                         mid: float | None, shadow: bool = False) -> int:
    """Écrit la décision comme candidat replay (shard par-PID, capé). Best-effort : 0 si non écrite."""
    row = candidat_depuis_decision(decision, strategie=strategie, ts_s=ts_s, mid=mid, shadow=shadow)
    if row is None:
        return 0
    base = str(root).rstrip("/\\") + "/" + BASE_REPLAY
    return append_replay_lines(base, "candidates.jsonl", [row],
                               max_bytes=CANDIDATES_MAX_BYTES, max_lines=CANDIDATES_MAX_LINES)


def enregistrer_marks(root: str, mids: dict[str, float], *, ts_s: float) -> int:
    """🔴 CRITIQUE — écrit les MARKS de prix (coin, ts, mid) dans le flux replay.

    CONSTAT du 18/07 : `marks.jsonl` contenait **0 ligne** alors que 1 610 candidats étaient
    enregistrés -> le replay A/B ne pouvait RIEN mesurer (c'est la cause racine du « 1 sur 1M » :
    sans marks, `prefilter_candidates` jette TOUS les candidats). L'écrivain existant
    (`v26_exit_pipeline`) n'était pas atteint par la boucle. On écrit donc les marks depuis le
    runtime qui, lui, TOURNE. Prix invalide -> ligne ignorée (rien d'inventé). Best-effort.
    """
    rows = []
    for coin, mid in (mids or {}).items():
        try:
            m = float(mid)
        except (TypeError, ValueError):
            continue
        c = str(coin).upper()
        if c and m > 0:
            rows.append({"coin": c, "ts": float(ts_s), "mid": m})
    if not rows:
        return 0
    base = str(root).rstrip("/\\") + "/" + BASE_REPLAY
    return append_replay_lines(base, "marks.jsonl", rows,
                               max_bytes=MARKS_MAX_BYTES, max_lines=MARKS_MAX_LINES)


def enregistrer_shadow(root: str, strategie: str, decisions: list[dict[str, Any]], *,
                       ts_s: float, mids: dict[str, float]) -> int:
    """#2 shadow-mode : logue ce que la stratégie OUVRIRAIT (sans rien risquer) -> flux de candidats
    replay. Renvoie le nombre écrit. Une décision sans mid connu est ignorée (pas fabriquée)."""
    n = 0
    for d in decisions or []:
        coin = str(d.get("coin") or "").upper()
        n += enregistrer_decision(root, d, strategie=strategie, ts_s=ts_s,
                                  mid=mids.get(coin), shadow=True)
    return n


__all__ = ["candidat_depuis_decision", "enregistrer_decision", "enregistrer_shadow", "BASE_REPLAY"]
