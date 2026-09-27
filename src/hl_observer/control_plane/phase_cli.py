"""Operator CLI for phase authority, campaigns, and research-cycle intents."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Sequence

from hl_observer.control_plane.phase_controller import PhaseController
from hl_observer.control_plane.resumable_campaign import (
    CampaignManifest,
    select_due_campaigns,
)


def _persist_transition_receipt(receipt, receipt_dir: str = "control/phase-receipts") -> None:
    target = Path(receipt_dir) / f"{receipt.request_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = receipt.to_dict()
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError("phase transition receipt identity conflict")
        return
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\\n", encoding="utf-8")
    os.replace(temporary, target)


def _request_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--requested-by", default="operator")


def _intent_args(parser: argparse.ArgumentParser) -> None:
    _request_args(parser)
    parser.add_argument("--config-json", default="{}")
    parser.add_argument("--main-code-sha", default="working-tree")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Alina SmartFlow Phase and Campaign Control Plane"
    )
    parser.add_argument("--state-file", default="control/alina-phase.json")
    parser.add_argument("--intent-file", default=None)
    parser.add_argument("--receipt-dir", default="control/phase-receipts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_status = subparsers.add_parser("status", help="Show current phase state")
    p_collect = subparsers.add_parser("collect", help="Transition to COLLECT")
    _request_args(p_collect)
    p_analyze = subparsers.add_parser("analyze", help="Transition to ANALYZE")
    _request_args(p_analyze)
    p_analyze.add_argument("--initial-stage", default="DRAIN")
    p_idle = subparsers.add_parser("idle", help="Transition to IDLE")
    _request_args(p_idle)

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
        item = subparsers.add_parser(command, help=f"Create {command} intent")
        _intent_args(item)

    campaign_status = subparsers.add_parser(
        "campaign-status", help="Inspect current-phase campaigns"
    )
    campaign_status.add_argument("--manifest-dir", default="campaigns/")

    campaign = subparsers.add_parser("campaign", help="Campaign operator surface")
    campaign_sub = campaign.add_subparsers(dest="campaign_action", required=True)
    campaign_status2 = campaign_sub.add_parser("status")
    campaign_status2.add_argument("--manifest-dir", default="campaigns/")
    for action in ("pause", "resume", "retry"):
        item = campaign_sub.add_parser(action)
        _intent_args(item)

    cycle = subparsers.add_parser("research-cycle", help="Research-cycle operator surface")
    cycle_sub = cycle.add_subparsers(dest="cycle_action", required=True)
    cycle_status = cycle_sub.add_parser("status")
    cycle_status.add_argument("--manifest-dir", default="campaigns/")
    cycle_start = cycle_sub.add_parser("start")
    _request_args(cycle_start)
    cycle_start.add_argument("--phase", choices=("IDLE", "COLLECT", "ANALYZE"), required=True)
    cycle_start.add_argument("--initial-stage", default="DRAIN")

    return parser


def _campaign_status(controller: PhaseController, manifest_dir: str) -> int:
    manifests: list[CampaignManifest] = []
    invalid: list[str] = []
    root = Path(manifest_dir)
    if not root.exists():
        print(json.dumps({
            "status": "UNAVAILABLE",
            "reason": "campaign_state_unavailable",
            "manifest_dir": str(root),
        }, indent=2, sort_keys=True))
        return 2
    for path in root.glob("*.json"):
        try:
            manifests.append(
                CampaignManifest.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            )
        except (OSError, ValueError, TypeError) as exc:
            invalid.append(f"{path.name}: {exc}")
    if invalid:
        print(json.dumps({
            "status": "UNAVAILABLE",
            "reason": "invalid_durable_campaign_state",
            "invalid_manifests": sorted(invalid),
        }, indent=2, sort_keys=True))
        return 2
    state = controller.current_state
    due = select_due_campaigns(
        manifests,
        current_phase=state.phase,
        current_epoch=state.epoch,
        current_analysis_stage=state.analysis_stage,
    )
    print(json.dumps({
        "current_phase": state.phase,
        "current_epoch": state.epoch,
        "total_manifests_loaded": len(manifests),
        "eligible_due_campaigns": [manifest.campaign_id for manifest in due],
    }, indent=2, sort_keys=True))
    return 0


def _write_intent(args, controller: PhaseController, intent: str) -> int:
    try:
        config = json.loads(args.config_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--config-json must be valid JSON: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError("--config-json must be a JSON object")
    state = controller.current_state
    analysis_intents = {
        "replay", "backtest", "oos", "forward_paper",
        "module_pnl_proof", "scoreboard", "full_cycle",
    }
    if intent in analysis_intents and state.phase != "ANALYZE":
        raise ValueError(f"{intent} requires ANALYZE phase, current={state.phase}")
    envelope = {
        "schema_version": "alina.operator_intent.v1",
        "request_id": args.request_id,
        "intent": intent,
        "requested_by": args.requested_by,
        "requested_at_utc": state.requested_at_utc,
        "phase": state.phase,
        "phase_epoch": state.epoch,
        "analysis_stage": state.analysis_stage,
        "source_collection_epoch": state.source_collection_epoch,
        "collection_cutoff_at_utc": state.collection_cutoff_at_utc,
        "main_code_sha": args.main_code_sha,
        "config": config,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    if args.intent_file:
        Path(args.intent_file).write_text(
            json.dumps(envelope, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    controller = PhaseController(state_file_path=Path(args.state_file))

    if args.command == "status":
        print(json.dumps(controller.current_state.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "collect":
        receipt = controller.transition_to_collect(
            request_id=args.request_id, requested_by=args.requested_by
        )
        _persist_transition_receipt(receipt, args.receipt_dir)
        print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "analyze":
        receipt = controller.transition_to_analyze(
            request_id=args.request_id,
            requested_by=args.requested_by,
            initial_stage=args.initial_stage,
        )
        _persist_transition_receipt(receipt, args.receipt_dir)
        print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "idle":
        receipt = controller.transition_to_idle(
            request_id=args.request_id, requested_by=args.requested_by
        )
        _persist_transition_receipt(receipt, args.receipt_dir)
        print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
        return 0

    intent_names = {
        "replay": "replay", "backtest": "backtest", "oos": "oos",
        "forward": "forward_paper", "pnl-proof": "module_pnl_proof",
        "scoreboard": "scoreboard", "full-cycle": "full_cycle",
        "pause": "pause", "resume": "resume", "retry": "retry",
    }
    if args.command in intent_names:
        return _write_intent(args, controller, intent_names[args.command])
    if args.command == "campaign-status":
        return _campaign_status(controller, args.manifest_dir)
    if args.command == "campaign":
        if args.campaign_action == "status":
            return _campaign_status(controller, args.manifest_dir)
        return _write_intent(args, controller, args.campaign_action)
    if args.command == "research-cycle":
        if args.cycle_action == "status":
            return _campaign_status(controller, args.manifest_dir)
        if args.phase == "COLLECT":
            receipt = controller.transition_to_collect(
                request_id=args.request_id, requested_by=args.requested_by
            )
        elif args.phase == "ANALYZE":
            receipt = controller.transition_to_analyze(
                request_id=args.request_id,
                requested_by=args.requested_by,
                initial_stage=args.initial_stage,
            )
        else:
            receipt = controller.transition_to_idle(
                request_id=args.request_id, requested_by=args.requested_by
            )
        _persist_transition_receipt(receipt, args.receipt_dir)
        print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
