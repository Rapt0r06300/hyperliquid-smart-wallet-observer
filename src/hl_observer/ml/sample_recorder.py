"""V13 — Training-sample recorder: the LEARNING LOOP.

When a paper position OPENS we stash its decision-time canonical features; when it CLOSES
we pair them with the realized net PnL and append ONE labeled row to a JSONL file. Over
time this accumulates the real (features -> outcome) dataset the model trains on.

Pure/append-only, read-only w.r.t. the market (no order, no network). Guarded so a logging
failure never affects the engine. A module-level shared recorder mirrors shared_recorder.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SAMPLES_PATH = "runtime/ml/training_samples.jsonl"


class TrainingSampleRecorder:
    def __init__(self, path: str = DEFAULT_SAMPLES_PATH, *, context: str = "LIVE") -> None:
        self.path = str(path)
        self.context = str(context)
        self._pending: dict[str, tuple[dict, int]] = {}

    def record_entry(self, position_key: str, features: dict, ts_ms: int) -> None:
        if not position_key:
            return
        self._pending[str(position_key)] = ({k: float(v) for k, v in (features or {}).items()}, int(ts_ms))

    def record_exit(self, position_key: str, realized_net_pnl_usdc: float, ts_ms: int) -> dict | None:
        key = str(position_key)
        item = self._pending.pop(key, None)
        if item is None:
            return None                         # close without a tracked open -> no sample
        feats, entry_ts = item
        if int(ts_ms) <= int(entry_ts):
            return None                         # no-lookahead: exit must be strictly after entry
        row = {
            "decision_id": key, "ts_ms": int(entry_ts), "close_ts_ms": int(ts_ms),
            "context": self.context, "features": feats,
            "net_pnl_usdc": round(float(realized_net_pnl_usdc), 6),
        }
        try:
            p = Path(self.path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception:
            return None                         # logging must never break the engine
        return row

    def pending_count(self) -> int:
        return len(self._pending)


_SHARED: TrainingSampleRecorder | None = None


def get_sample_recorder() -> TrainingSampleRecorder:
    global _SHARED
    if _SHARED is None:
        import os
        _SHARED = TrainingSampleRecorder(
            os.environ.get("HYPERSMART_V13_SAMPLES_PATH") or DEFAULT_SAMPLES_PATH
        )
    return _SHARED


__all__ = ["TrainingSampleRecorder", "get_sample_recorder", "DEFAULT_SAMPLES_PATH"]
