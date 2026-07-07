"""PERF-2/3/4 — Garde du chemin chaud: rien de bloquant dans le tick de décision.

La cause n°1 des bots lents = un appel REST synchrone, une écriture disque ou un
sleep planqué dans la boucle de décision. Ce garde inspecte une trace d'opérations
d'un cycle et signale ce qui n'a rien à y faire (REST, disk, blocking). Pur,
déterministe: sert de test de non-régression et d'alerte runtime.
"""

from __future__ import annotations

_REST_TOKENS = ("http", "rest", "requests.", "urlopen", "/info", "/exchange", "fetch")
_DISK_TOKENS = ("open(", "write", ".save", "json.dump", "to_disk", "flush", "sqlite", "commit")
_BLOCK_TOKENS = ("sleep", "wait(", "join(", "lock.acquire", "input(")

HOT_PATH_ALLOWED = ("cache", "in_memory", "ws_", "compute", "score", "gate", "ledger_append_async")


def audit_hot_path(operations: list[dict]) -> dict:
    """operations = [{'name': str, 'stage': str, 'blocking': bool?}] du cycle.

    Retourne les violations (REST/disk/blocking) qui devraient sortir du tick.
    """

    violations: list[dict] = []
    for op in operations or []:
        if not isinstance(op, dict):
            continue
        name = str(op.get("name") or "").lower()
        stage = str(op.get("stage") or "hot")
        if stage != "hot":
            continue  # seuls les ops du chemin chaud comptent
        kind = None
        if op.get("blocking") is True:
            kind = "BLOCKING"
        elif any(t in name for t in _REST_TOKENS):
            kind = "REST_IN_HOT_PATH"
        elif any(t in name for t in _DISK_TOKENS):
            kind = "DISK_IN_HOT_PATH"
        elif any(t in name for t in _BLOCK_TOKENS):
            kind = "BLOCKING"
        if kind:
            violations.append({"op": name, "kind": kind})
    return {
        "clean": not violations,
        "violation_count": len(violations),
        "violations": violations,
        "rule": "hot path = WS reads + in-memory compute + async ledger append only",
    }


__all__ = ["audit_hot_path", "HOT_PATH_ALLOWED"]
