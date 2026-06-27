"""V13 — Build (FeatureRow, Outcome) pairs from data the engine ALREADY produces.

Two sources:
  * training_samples.jsonl (primary, written live by sample_recorder) — clean, paired.
  * snapshot bot_simulation.events (bootstrap) — pair OPEN features ↔ CLOSE pnl by
    matched_position_key, no-lookahead. Limited to the snapshot window.
Pure / read-only. Uses the canonical feature set so training ↔ inference align.
"""

from __future__ import annotations

import json

from hl_observer.ml.dataset import FeatureRow, Outcome
from hl_observer.ml.features import canonical_features

_OPEN = ("OPEN", "ENTRY", "ADD", "INCREASE")
_CLOSE = ("CLOSE", "REDUCE", "EXIT")


def _features_from_event(ev: dict) -> dict:
    return canonical_features(
        net_edge_bps=ev.get("edge_remaining_bps", 0.0) or 0.0,
        signal_age_ms=ev.get("signal_age_ms", 0.0) or 0.0,
        consensus_wallets=ev.get("consensus_wallets", 0.0) or 0.0,
        liquidity_score=ev.get("liquidity_score", 0.0) or 0.0,
        leader_score=ev.get("leader_score", 0.0) or 0.0,
        adverse_move_bps=ev.get("adverse_price_move_bps", 0.0) or 0.0,
        price_deviation_bps=ev.get("price_deviation_bps", 0.0) or 0.0,
    )


def rows_outcomes_from_samples(path: str) -> tuple[list[FeatureRow], list[Outcome]]:
    rows: list[FeatureRow] = []
    outcomes: list[Outcome] = []
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            did = str(d.get("decision_id"))
            rows.append(FeatureRow(decision_id=did, ts_ms=int(d.get("ts_ms", 0)),
                                   features=dict(d.get("features") or {}),
                                   context=str(d.get("context", "LIVE"))))
            outcomes.append(Outcome(did, int(d.get("close_ts_ms", 0)), float(d.get("net_pnl_usdc", 0.0))))
    except FileNotFoundError:
        return [], []
    return rows, outcomes


def rows_outcomes_from_events(events: list[dict], *, context: str = "REPLAY") -> tuple[list[FeatureRow], list[Outcome]]:
    """Bootstrap: pair OPEN features ↔ CLOSE realized pnl by matched_position_key."""
    by_key_open: dict[str, dict] = {}
    rows: list[FeatureRow] = []
    outcomes: list[Outcome] = []
    seq = sorted(events, key=lambda e: int(e.get("observed_at_ms") or 0))
    for ev in seq:
        action = str(ev.get("bot_replay_action") or "").upper()
        key = str(ev.get("matched_position_key") or "")
        ts = int(ev.get("observed_at_ms") or 0)
        if not key:
            continue
        if any(t in action for t in _OPEN):
            by_key_open[key] = {"features": _features_from_event(ev), "ts": ts, "did": f"{key}:{ts}"}
        elif any(t in action for t in _CLOSE):
            op = by_key_open.pop(key, None)
            if op is None or ts <= int(op["ts"]):
                continue                        # no tracked open / lookahead -> skip
            pnl = float(ev.get("estimated_net_pnl_usdc") or 0.0)
            rows.append(FeatureRow(decision_id=op["did"], ts_ms=int(op["ts"]),
                                   features=op["features"], context=context))
            outcomes.append(Outcome(op["did"], ts, pnl))
    return rows, outcomes


def _salvage_events(txt: str) -> list[dict]:
    """Recover complete event objects from a truncated/mid-write snapshot (no exception)."""
    dec = json.JSONDecoder()
    for key in ('"ledger_events"', '"events"'):
        i = txt.find(key)
        if i == -1:
            continue
        j = txt.find("[", i)
        if j == -1:
            continue
        out: list[dict] = []
        k = j + 1
        n = len(txt)
        while k < n:
            while k < n and txt[k] in " \t\r\n,":
                k += 1
            if k >= n or txt[k] == "]":
                break
            try:
                obj, end = dec.raw_decode(txt, k)
            except Exception:
                break                       # hit the truncation point -> stop, keep what we have
            if isinstance(obj, dict):
                out.append(obj)
            k = end
        if out:
            return out
    return []


def _read_snapshot_events(snapshot_path: str) -> list[dict]:
    """Full event list (prefers ledger_events), tolerant of a snapshot being written live."""
    try:
        txt = open(snapshot_path, encoding="utf-8", errors="replace").read()
    except FileNotFoundError:
        return []
    try:
        snap = json.loads(txt)
        bs = snap.get("bot_simulation") or snap
        return list(bs.get("ledger_events") or bs.get("events") or [])
    except Exception:
        return _salvage_events(txt)          # mid-write file -> salvage complete objects


def ingest_snapshot_to_samples(snapshot_path: str, samples_path: str, *, context: str = "REPLAY") -> int:
    """Append NEW (deduped) labeled samples extracted from a live snapshot into the
    accumulating training_samples.jsonl. Returns the number of new rows written.

    This lets the model learn over time WITHOUT any hot-path edit: the engine already
    writes the snapshot; we harvest its closed-trade events and accumulate them. Robust to
    a snapshot being mid-write (salvages complete events) and uses the FULL ledger_events.
    """
    events = _read_snapshot_events(snapshot_path)
    rows, outcomes = rows_outcomes_from_events(events, context=context)
    out_by_id = {o.decision_id: o for o in outcomes}
    seen: set[str] = set()
    try:
        for line in open(samples_path, encoding="utf-8"):
            line = line.strip()
            if line:
                seen.add(str(json.loads(line).get("decision_id")))
    except FileNotFoundError:
        pass
    from pathlib import Path
    Path(samples_path).parent.mkdir(parents=True, exist_ok=True)
    n_new = 0
    with open(samples_path, "a", encoding="utf-8") as fh:
        for r in rows:
            if r.decision_id in seen:
                continue
            o = out_by_id.get(r.decision_id)
            if o is None or int(o.close_ts_ms) <= int(r.ts_ms):
                continue
            fh.write(json.dumps({
                "decision_id": r.decision_id, "ts_ms": int(r.ts_ms),
                "close_ts_ms": int(o.close_ts_ms), "context": r.context,
                "features": r.features, "net_pnl_usdc": round(float(o.realized_net_pnl_usdc), 6),
            }, sort_keys=True) + "\n")
            seen.add(r.decision_id); n_new += 1
    return n_new


__all__ = ["rows_outcomes_from_samples", "rows_outcomes_from_events", "ingest_snapshot_to_samples"]
