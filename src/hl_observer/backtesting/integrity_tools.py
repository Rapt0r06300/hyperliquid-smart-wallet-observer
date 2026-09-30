"""Outils d'intégrité & reproductibilité — pur, testé. Exécution du backlog :
seeded_rng (IDEA-75, seeds déterministes), golden_file_check (IDEA-99, tests golden-file),
spoofing_flags (IDEA-17, détection de spoofing/layering). Aucun ordre.
"""
from __future__ import annotations

import json
import random


def seeded_rng(seed: int) -> random.Random:
    """RNG déterministe et isolé (reproductibilité partout)."""
    return random.Random(seed)


def golden_file_check(actual, expected) -> bool:
    """True si `actual` == `expected` (sérialisation JSON stable) — détecte toute dérive de sortie."""
    return json.dumps(actual, sort_keys=True, default=str) == json.dumps(expected, sort_keys=True, default=str)


def spoofing_flags(order_events, *, large_size: float, max_lifetime: float) -> list:
    """Flag les gros ordres AJOUTÉS puis ANNULÉS très vite (spoofing/layering).
    `order_events` : [(id, action 'add'/'cancel', taille, timestamp)]."""
    adds = {}
    flags = []
    for oid, action, size, ts in order_events:
        if action == "add" and float(size) >= large_size:
            adds[oid] = float(ts)
        elif action == "cancel" and oid in adds:
            if float(ts) - adds.pop(oid) <= max_lifetime:
                flags.append(oid)
    return flags
