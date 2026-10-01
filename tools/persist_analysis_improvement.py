#!/usr/bin/env python3
"""Persist one economic analysis result into the durable improvement ledger."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from tools.persist_analysis_scoreboard import _load, build_improvement_ledger

STAGE_BY_KIND = {
    "backtest": "BACKTEST",
    "oos": "OOS",
    "forward_paper": "FORWARD_PAPER",
    "module_pnl_proof": "PNL_PROOF",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-manifest", required=True)
    parser.add_argument("--scoreboard", required=True)
    parser.add_argument("--evidence-tag", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--unit-id", required=True)
    parser.add_argument("--output", default="catalog/ECONOMIC_IMPROVEMENT_LEDGER.json")
    args = parser.parse_args()

    manifest = _load(Path(args.campaign_manifest))
    scoreboard = _load(Path(args.scoreboard))
    if manifest.get("schema_version") != "alina.resumable_campaign.v2":
        raise ValueError("analysis campaign must use resumable campaign v2")
    if manifest.get("creation_phase") != "ANALYZE":
        raise ValueError("improvement history requires ANALYZE")
    kind = str(manifest.get("kind") or "")
    stage = STAGE_BY_KIND.get(kind)
    if stage is None:
        raise ValueError(f"unsupported economic campaign kind: {kind}")
    if manifest.get("analysis_stage") not in (None, stage):
        raise ValueError("manifest analysis_stage mismatch")
    if scoreboard.get("schema_version") != "hypersmart.economic_family_scoreboards.v2":
        raise ValueError("unexpected economic scoreboard schema")
    if scoreboard.get("paper_read_only") is not True or scoreboard.get("real_execution") is not False:
        raise ValueError("scoreboard is not paper/read-only")

    phase_epoch = manifest.get("phase_epoch")
    source_epoch = manifest.get("source_collection_epoch")
    selection_id = str(manifest.get("dataset_selection_id") or "")
    code_sha = str(manifest.get("code_sha") or "")
    campaign_id = str(manifest.get("campaign_id") or "")
    if (
        isinstance(phase_epoch, bool)
        or not isinstance(phase_epoch, int)
        or isinstance(source_epoch, bool)
        or not isinstance(source_epoch, int)
        or not selection_id
        or len(code_sha) != 40
        or not campaign_id
    ):
        raise ValueError("incomplete campaign provenance")

    output = Path(args.output)
    previous = _load(output) if output.is_file() else None
    ledger = build_improvement_ledger(
        scoreboard,
        previous,
        campaign_id=campaign_id,
        phase_epoch=phase_epoch,
        source_collection_epoch=source_epoch,
        dataset_selection_id=selection_id,
        code_sha=code_sha,
        analysis_stage=stage,
        evidence_tag=args.evidence_tag,
        evidence_repository=args.repository,
        unit_id=args.unit_id,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(ledger, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "campaign_id": campaign_id,
        "analysis_stage": stage,
        "ledger_digest": ledger["ledger_digest"],
        "families": {
            family: row["latest"]["status"]
            for family, row in ledger["families"].items()
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
