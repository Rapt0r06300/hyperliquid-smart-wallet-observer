"""V13 — Train the local model from real logs (offline CLI). FREE, paper-only.

Learning loop (no hot-path edit needed):
  python -m hl_observer.ml.train_cli \
      --ingest-snapshot logs/.../simulation_snapshot_latest.json \
      --samples runtime/ml/training_samples.jsonl \
      --out runtime/models/trade_model_v13.json

Steps: harvest closed-trade samples from the live snapshot → append (deduped) to the
accumulating samples file → train calibrated logistic → save model ONLY if it beats the
base-rate baseline out-of-sample → write a report sidecar + append a HISTORY row so the
dashboard can show how the model improves over successive retrainings. Never trades.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from hl_observer.ml.ledger_extract import (
    ingest_snapshot_to_samples, rows_outcomes_from_events, rows_outcomes_from_samples,
)
from hl_observer.ml.train import train_from_dataset


def _write_outputs(out: str, rep: dict) -> None:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out + ".report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    ev = rep.get("evaluation") or {}
    hist_row = {
        "ts": int(time.time()), "n": rep.get("n"), "n_win": rep.get("n_win"),
        "brier": ev.get("brier"), "baseline_brier": ev.get("baseline_brier"),
        "brier_advantage": ev.get("brier_advantage"), "accuracy": ev.get("accuracy"),
        "beats_baseline": ev.get("beats_baseline"), "saved": rep.get("saved"),
    }
    with open(out + ".history.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(hist_row, sort_keys=True) + "\n")


def run(*, samples=None, snapshot=None, ingest_snapshot=None, out=None,
        context="LIVE", min_samples=40) -> dict:
    requested_context = str(context or "LIVE").upper()
    train_context = None if requested_context in {"ALL", "ANY", "MIXED", "*"} else requested_context
    ingest_context = "LIVE" if train_context is None else train_context
    ingested = 0
    if ingest_snapshot and samples:
        ingested = ingest_snapshot_to_samples(ingest_snapshot, samples, context=ingest_context)
    if samples:
        rows, outcomes = rows_outcomes_from_samples(samples)
    elif snapshot:
        snap = json.load(open(snapshot, encoding="utf-8"))
        events = (snap.get("bot_simulation") or {}).get("events") or []
        rows, outcomes = rows_outcomes_from_events(events, context=context or "REPLAY")
    else:
        rows, outcomes = [], []
    if not rows:
        rep = {"trained": False, "saved": False, "reason": "no_samples_found",
               "n": 0, "ingested": ingested,
               "context_requested": requested_context,
               "context_effective": train_context or "ALL"}
        if out:
            _write_outputs(out, rep)
        return rep
    rep = train_from_dataset(rows, outcomes, context=train_context, out_path=out, min_samples=min_samples)
    rep["ingested"] = ingested
    rep["context_requested"] = requested_context
    rep["context_effective"] = train_context or "ALL"
    if out:
        _write_outputs(out, rep)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Train V13 local trade model (paper-only).")
    ap.add_argument("--samples")
    ap.add_argument("--snapshot")
    ap.add_argument("--ingest-snapshot", dest="ingest_snapshot")
    ap.add_argument("--out", default="runtime/models/trade_model_v13.json")
    ap.add_argument("--context", default="LIVE")
    ap.add_argument("--min-samples", type=int, default=40)
    a = ap.parse_args(argv)
    rep = run(samples=a.samples, snapshot=a.snapshot, ingest_snapshot=a.ingest_snapshot,
              out=a.out, context=a.context, min_samples=a.min_samples)
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
