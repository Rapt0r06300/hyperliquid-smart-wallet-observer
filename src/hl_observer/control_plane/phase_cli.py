"""Operator CLI surface for Phase Authority & Resumable Campaign Management."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from hl_observer.control_plane.phase_state import AlinaPhaseState
from hl_observer.control_plane.phase_controller import PhaseController
from hl_observer.control_plane.analyze_stage_machine import ANALYZE_STAGES
from hl_observer.control_plane.resumable_campaign import (
    CampaignManifest,
    select_due_campaigns,
    SCHEMA_VERSION_V2,
)
from hl_observer.control_plane.dispatch_receipt import generate_request_id, DispatchReceipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alina SmartFlow Phase & Campaign Control Plane")
    parser.add_argument("--state-file", type=str, default="control/alina-phase.json", help="Path to alina-phase.json")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # phase status
    p_status = subparsers.add_parser("status", help="Show current phase state")

    # phase collect
    p_collect = subparsers.add_parser("collect", help="Transition to COLLECT phase")
    p_collect.add_argument("--request-id", type=str, required=True, help="Operator request UUID or string")
    p_collect.add_argument("--requested-by", type=str, default="operator", help="Requesting identity")

    # phase analyze
    p_analyze = subparsers.add_parser("analyze", help="Transition to ANALYZE phase")
    p_analyze.add_argument("--request-id", type=str, required=True, help="Operator request UUID or string")
    p_analyze.add_argument("--requested-by", type=str, default="operator", help="Requesting identity")
    p_analyze.add_argument("--initial-stage", type=str, default="DRAIN", help="Initial analysis stage")

    # advance analyze stage
    p_adv = subparsers.add_parser("advance-stage", help="Advance analysis stage in ANALYZE phase")
    p_adv.add_argument("--target-stage", type=str, required=True, choices=ANALYZE_STAGES, help="Target stage to advance to")

    # phase idle
    p_idle = subparsers.add_parser("idle", help="Transition to IDLE phase")
    p_idle.add_argument("--request-id", type=str, required=True, help="Operator request UUID or string")
    p_idle.add_argument("--requested-by", type=str, default="operator", help="Requesting identity")

    # campaign status
    c_status = subparsers.add_parser("campaign-status", help="Inspect active campaigns for current phase")
    c_status.add_argument("--manifest-dir", type=str, default="campaigns/", help="Directory containing campaign manifests")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    controller = PhaseController(state_file_path=Path(args.state_file))

    if args.command == "status":
        print(json.dumps(controller.current_state.to_dict(), indent=2))
        return 0

    elif args.command == "collect":
        receipt = controller.transition_to_collect(
            request_id=args.request_id,
            requested_by=args.requested_by,
        )
        print(json.dumps(receipt.to_dict(), indent=2))
        return 0

    elif args.command == "analyze":
        receipt = controller.transition_to_analyze(
            request_id=args.request_id,
            requested_by=args.requested_by,
            initial_stage=args.initial_stage,
        )
        print(json.dumps(receipt.to_dict(), indent=2))
        return 0

    elif args.command == "advance-stage":
        new_state = controller.advance_analysis_stage(stage=args.target_stage)
        print(json.dumps(new_state.to_dict(), indent=2))
        return 0

    elif args.command == "idle":
        receipt = controller.transition_to_idle(
            request_id=args.request_id,
            requested_by=args.requested_by,
        )
        print(json.dumps(receipt.to_dict(), indent=2))
        return 0

    elif args.command == "campaign-status":
        m_dir = Path(args.manifest_dir)
        manifests: list[CampaignManifest] = []
        if m_dir.exists():
            for p in m_dir.glob("*.json"):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    manifests.append(CampaignManifest.from_dict(data))
                except Exception as e:
                    print(f"Warning: skipping invalid manifest {p}: {e}", file=sys.stderr)

        state = controller.current_state
        due = select_due_campaigns(
            manifests,
            current_phase=state.phase,
            current_epoch=state.epoch,
        )
        summary = {
            "current_phase": state.phase,
            "current_epoch": state.epoch,
            "total_manifests_loaded": len(manifests),
            "eligible_due_campaigns": [m.campaign_id for m in due],
        }
        print(json.dumps(summary, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
