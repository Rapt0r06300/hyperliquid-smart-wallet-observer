"""Operator CLI surface for Phase Authority & Resumable Campaign Management."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from hl_observer.control_plane.phase_state import AlinaPhaseState
from hl_observer.control_plane.phase_controller import PhaseController
from hl_observer.control_plane.resumable_campaign import (
    CampaignManifest,
    select_due_campaigns,
    SCHEMA_VERSION_V2,
)
from hl_observer.control_plane.dispatch_receipt import generate_request_id, DispatchReceipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alina SmartFlow Phase & Campaign Control Plane")
    parser.add_argument("--state-file", type=str, default="control/alina-phase.json", help="Path to alina-phase.json")
    parser.add_argument("--intent-file", type=str, default=None, help="Optional durable operator-intent output")

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

    # phase idle
    p_idle = subparsers.add_parser("idle", help="Transition to IDLE phase")
    p_idle.add_argument("--request-id", type=str, required=True, help="Operator request UUID or string")
    p_idle.add_argument("--requested-by", type=str, default="operator", help="Requesting identity")

    # Canonical operator intents. These create deterministic, paper-only intent envelopes;
    # Dataset V2 remains the durable heavy execution plane.
    intent_commands = {
        "replay": "replay",
        "backtest": "backtest",
        "oos": "oos",
        "forward": "forward_paper",
        "pnl-proof": "module_pnl_proof",
        "scoreboard": "scoreboard",
        "full-cycle": "full_cycle",
        "pause": "pause",
        "resume": "resume",
        "retry": "retry",
    }
    for command in intent_commands:
        p_intent = subparsers.add_parser(command, help=f"Create {command} operator intent")
        p_intent.add_argument("--request-id", type=str, required=True)
        p_intent.add_argument("--requested-by", type=str, default="operator")
        p_intent.add_argument("--config-json", type=str, default="{}")
        p_intent.add_argument("--main-code-sha", type=str, default="working-tree")

    # campaign status
    c_status = subparsers.add_parser("campaign-status", help="Inspect active campaigns for current phase")
    c_status.add_argument("--manifest-dir", type=str, default="campaigns/")

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

    elif args.command == "idle":
        receipt = controller.transition_to_idle(
            request_id=args.request_id,
            requested_by=args.requested_by,
        )
        print(json.dumps(receipt.to_dict(), indent=2))
        return 0

    elif args.command in {"replay", "backtest", "oos", "forward", "pnl-proof", "scoreboard", "full-cycle", "pause", "resume", "retry"}:
        try:
            config = json.loads(args.config_json)
        except json.JSONDecodeError as exc:
            parser.error(f"--config-json must be valid JSON: {exc}")
        if not isinstance(config, dict):
            parser.error("--config-json must be a JSON object")
        state = controller.current_state
        intent_kind = {
            "replay": "replay",
            "backtest": "backtest",
            "oos": "oos",
            "forward": "forward_paper",
            "pnl-proof": "module_pnl_proof",
            "scoreboard": "scoreboard",
            "full-cycle": "full_cycle",
            "pause": "pause",
            "resume": "resume",
            "retry": "retry",
        }[args.command]
        if intent_kind in {"replay", "backtest", "oos", "forward_paper", "module_pnl_proof", "scoreboard", "full_cycle"} and state.phase != "ANALYZE":
            raise ValueError(f"{args.command} requires ANALYZE phase, current={state.phase}")
        envelope = {
            "schema_version": "alina.operator_intent.v1",
            "request_id": args.request_id,
            "intent": intent_kind,
            "requested_by": args.requested_by,
            "requested_at_utc": state.requested_at_utc,
            "phase": state.phase,
            "phase_epoch": state.epoch,
            "source_collection_epoch": state.source_collection_epoch,
            "collection_cutoff_at_utc": state.collection_cutoff_at_utc,
            "main_code_sha": args.main_code_sha,
            "config": config,
            "paper_only": True,
            "read_only": True,
            "real_execution": False,
        }
        if args.intent_file:
            Path(args.intent_file).write_text(json.dumps(envelope, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(envelope, indent=2, sort_keys=True))
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
