"""CHANTIER #1 — RECORDER HF HL+Binance simultané (prêt à tourner côté machine Flo).

Multiplexe les flux WS HL (BBO + L2 top-20 + trades signés) et Binance, normalise chaque message en événement
canonique (via research.hf_recorder), DÉDUP par (venue, coin, seq), suit séquences / gaps / reconnects /
out-of-order / desync en STREAMING (mémoire bornée — un run 48h ne bufferise pas tout), et écrit un JSONL
append-only durable. La capture réseau tourne côté user → `capturer_live` = BLOCKED_EXTERNAL ici. Aucune donnée
fabriquée : un timestamp manquant reste None et est compté, jamais remplacé par `now`. 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.research.hf_recorder import BLOCKED, normaliser_event, qualite

_DESYNC_MAX_MS = 100.0


class Recorder:
    """Écrit les événements canoniques en JSONL append-only et tient des stats de qualité incrémentales."""

    def __init__(self, out_path: str, *, desync_max_ms: float = _DESYNC_MAX_MS) -> None:
        self.out_path = out_path
        self.desync_max_ms = float(desync_max_ms)
        self._f = open(out_path, "a", encoding="utf-8")
        self._vus: dict[tuple[Any, Any, Any], set] = {}   # seqs vues PAR stream ET par époque (reset au reconnect)
        self._last_seq: dict[tuple[Any, Any, Any], Any] = {}
        self._last_ex: dict[tuple[Any, Any, Any], float] = {}
        self.n = 0
        self.doublons = 0
        self.gaps = 0
        self.reconnects = 0
        self.out_of_order = 0
        self.desync = 0
        self.ts_manquants = 0

    def ingerer(self, raw: Mapping[str, Any], *, receive_wall_ts: Any = None,
                receive_monotonic_ts: Any = None, normalize_ts: Any = None) -> dict[str, Any] | None:
        ev = normaliser_event(raw, receive_wall_ts=receive_wall_ts,
                              receive_monotonic_ts=receive_monotonic_ts, normalize_ts=normalize_ts)
        key = (ev["venue"], ev["coin"], ev.get("type"))
        seq = ev.get("seq")
        if isinstance(seq, (int, float)) and not isinstance(seq, bool):
            seen = self._vus.setdefault(key, set())
            last = self._last_seq.get(key)
            reconnect = last is not None and seq < last   # reset de séquence = reconnexion (nouvelle époque)
            if reconnect:
                self.reconnects += 1
                seen.clear()
            if seq in seen:                               # doublon dans l'époque courante -> jamais réécrit
                self.doublons += 1
                return None
            seen.add(seq)
            if last is not None and not reconnect and seq - last > 1:
                self.gaps += int(seq - last - 1)          # trou de séquence (updates manqués)
            self._last_seq[key] = seq
        ex = ev.get("exchange_ts")
        if isinstance(ex, (int, float)):
            le = self._last_ex.get(key)
            if le is not None and ex < le:
                self.out_of_order += 1
            self._last_ex[key] = ex
            rw = ev.get("receive_wall_ts")
            if isinstance(rw, (int, float)) and abs(rw - ex) > self.desync_max_ms:
                self.desync += 1
        self.ts_manquants += len(ev.get("ts_manquants", []))
        self._f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        self.n += 1
        return ev

    def cloturer(self) -> dict[str, Any]:
        self._f.flush()
        self._f.close()
        return {"out_path": self.out_path, "n_ecrits": self.n, "doublons": self.doublons,
                "gaps_seq": self.gaps, "reconnects": self.reconnects, "out_of_order": self.out_of_order,
                "desync": self.desync, "ts_manquants_total": self.ts_manquants,
                "quality_ok": bool(self.doublons == 0 and self.out_of_order == 0 and self.ts_manquants == 0),
                "real_execution": False}


def enregistrer(messages: Iterable[Mapping[str, Any]], out_path: str) -> dict[str, Any]:
    """Consomme un itérateur de messages {raw, receive_wall_ts, receive_monotonic_ts, normalize_ts} (streaming)
    et écrit le JSONL canonique. `raw` peut aussi être le message lui-même."""
    r = Recorder(out_path)
    for m in messages:
        raw = m.get("raw", m)
        r.ingerer(raw, receive_wall_ts=m.get("receive_wall_ts"),
                  receive_monotonic_ts=m.get("receive_monotonic_ts"), normalize_ts=m.get("normalize_ts"))
    return r.cloturer()


def manifeste_depuis_fichier(path: str) -> dict[str, Any]:
    """Relit le JSONL enregistré et recalcule le manifeste de qualité (research.hf_recorder.qualite)."""
    from hl_observer.research.jsonl_stream import stream_jsonl
    return qualite(list(stream_jsonl(path)))


def capturer_live(*_a: Any, **_k: Any) -> dict[str, Any]:
    """La capture WS HL+Binance tourne côté machine Flo (pas de réseau ici)."""
    return {"statut": BLOCKED, "manque": "acces WS HL (BBO/L2/trades) + Binance cote user", "real_execution": False}


__all__ = ["Recorder", "enregistrer", "manifeste_depuis_fichier", "capturer_live", "BLOCKED"]
