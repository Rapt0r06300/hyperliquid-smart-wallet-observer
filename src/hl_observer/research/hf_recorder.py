"""ALPHA P0/P17 — RECORDER HF : événement canonique + normalisation + qualité. (Capture live = BLOCKED ici.)

Interface de collecte haute résolution : chaque événement porte TOUS les timestamps
(exchange / receive_wall / receive_monotonic / normalize / signal / decision / simulated_fill). **Aucun
timestamp absent n'est remplacé silencieusement par `now`** — un champ manquant reste `None` et est signalé
dans le manifeste de qualité. On gère séquence / dédup / out-of-order / DESYNC / gaps. La capture réseau
tourne côté user (pas de réseau ici) → `capture_live` est BLOCKED_EXTERNAL ; la NORMALISATION et la QUALITÉ
sont, elles, codées et testées.

Schéma canonique HL/Binance L2 top-20 : levels 1/3/5/10/20 (prix, size, update_ts) + trades signés.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

TIMESTAMPS = ("exchange_ts", "receive_wall_ts", "receive_monotonic_ts", "normalize_ts",
              "signal_ts", "decision_ts", "simulated_fill_ts")
BLOCKED = "BLOCKED_EXTERNAL"


def normaliser_event(raw: Mapping[str, Any], *, receive_wall_ts: Any = None, receive_monotonic_ts: Any = None,
                     normalize_ts: Any = None) -> dict[str, Any]:
    """Normalise un événement brut → canonique. Timestamps manquants = None (JAMAIS `now`), signalés à part."""
    ev: dict[str, Any] = {"coin": raw.get("coin"), "venue": raw.get("venue"), "type": raw.get("type"),
                          "seq": raw.get("seq"), "update_id": raw.get("update_id")}
    ev["exchange_ts"] = raw.get("exchange_ts") if isinstance(raw.get("exchange_ts"), (int, float)) else None
    ev["receive_wall_ts"] = receive_wall_ts if isinstance(receive_wall_ts, (int, float)) else None
    ev["receive_monotonic_ts"] = receive_monotonic_ts if isinstance(receive_monotonic_ts, (int, float)) else None
    ev["normalize_ts"] = normalize_ts if isinstance(normalize_ts, (int, float)) else None
    for k in ("signal_ts", "decision_ts", "simulated_fill_ts"):
        ev[k] = None
    ev["ts_manquants"] = [k for k in TIMESTAMPS if ev.get(k) is None]
    return ev


def qualite(events: Sequence[Mapping[str, Any]], *, desync_max_ms: float = 100.0) -> dict[str, Any]:
    """Manifeste de qualité : gaps de séquence, doublons, out-of-order, desync, timestamps manquants + hash."""
    seqs = [e.get("seq") for e in events if isinstance(e.get("seq"), (int, float))]
    doublons = len(seqs) - len(set(seqs))
    gaps = sum(1 for i in range(1, len(seqs)) if seqs[i] - seqs[i - 1] > 1)
    ex = [e.get("exchange_ts") for e in events if isinstance(e.get("exchange_ts"), (int, float))]
    out_of_order = sum(1 for i in range(1, len(ex)) if ex[i] < ex[i - 1])
    desync = 0
    for e in events:
        a, b = e.get("exchange_ts"), e.get("receive_wall_ts")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(b - a) > desync_max_ms:
            desync += 1
    manquants = sum(len(e.get("ts_manquants", [])) for e in events)
    manifest = {"n": len(events), "doublons_seq": doublons, "gaps_seq": gaps, "out_of_order": out_of_order,
                "desync": desync, "ts_manquants_total": manquants}
    manifest["hash"] = hashlib.sha1(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:16]
    manifest["quality_ok"] = bool(doublons == 0 and out_of_order == 0 and manquants == 0)
    return manifest


def capture_live() -> dict[str, Any]:
    """La capture réseau HF tourne côté user (pas de réseau ici)."""
    return {"statut": BLOCKED, "manque": "acces WS/REST HL+Binance (collecteurs cote user)"}


__all__ = ["TIMESTAMPS", "normaliser_event", "qualite", "capture_live", "BLOCKED"]
