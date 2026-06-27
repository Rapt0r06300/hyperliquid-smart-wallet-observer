from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from hl_observer.simulation.decision_replay_analyzer import (
    DecisionEvent,
    analyze_decision_logs_summary,
    load_recent_decision_events,
)
from hl_observer.utils.time import now_ms


@dataclass(frozen=True, slots=True)
class ReplayResult:
    source_dir: Path
    events_available: int
    events_replayed: int
    output_path: Path
    state_path: Path
    speed: str
    replayed_at_ms: int
    read_only: bool = True
    write_warnings: tuple[str, ...] = ()


def replay_events_from_logs(log_dir: Path, *, speed: str = "5x", limit: int = 100) -> ReplayResult:
    selected = load_recent_decision_events(log_dir, limit=max(0, limit))
    summary = analyze_decision_logs_summary(log_dir)
    replayed_at = now_ms()
    output_path = log_dir / "realtime_replay_latest.jsonl"
    state_path = log_dir / "realtime_replay_state.json"
    write_warnings: list[str] = []
    output_payload = "".join(
        json.dumps(_event_to_replay_row(event, replayed_at), sort_keys=True, ensure_ascii=False) + "\n"
        for event in selected
    )
    output_warning = _safe_write_text(output_path, output_payload)
    if output_warning:
        write_warnings.append(output_warning)
    state_payload = json.dumps(
        {
            "source_dir": str(log_dir),
            "events_available": summary.event_count,
            "events_replayed": len(selected),
            "speed": speed,
            "replayed_at_ms": replayed_at,
            "read_only": True,
            "network_used": False,
            "execution": "forbidden",
            "mode": "LOCAL_REPLAY_ONLY",
            "write_warnings": write_warnings,
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    state_warning = _safe_write_text(state_path, state_payload)
    if state_warning:
        write_warnings.append(state_warning)
    return ReplayResult(
        source_dir=log_dir,
        events_available=summary.event_count,
        events_replayed=len(selected),
        output_path=output_path,
        state_path=state_path,
        speed=speed,
        replayed_at_ms=replayed_at,
        write_warnings=tuple(write_warnings),
    )


def format_replay_result(result: ReplayResult) -> str:
    return "\n".join(
        [
            "realtime_replay=local_logs_only",
            f"source_dir={result.source_dir}",
            f"events_available={result.events_available}",
            f"events_replayed={result.events_replayed}",
            f"speed={result.speed}",
            f"output={result.output_path}",
            f"state={result.state_path}",
            f"replayed_at_ms={result.replayed_at_ms}",
            f"read_only={str(result.read_only).lower()}",
            "write_warnings=" + " || ".join(result.write_warnings) if result.write_warnings else "write_warnings=none",
            "orders_created=0",
        ]
    )


def _safe_write_text(path: Path, text: str) -> str | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        return f"{path}: {exc.__class__.__name__}: {exc}"
    return None


def _event_to_replay_row(event: DecisionEvent, replayed_at_ms: int) -> dict:
    return {
        "replayed_at_ms": replayed_at_ms,
        "original_timestamp_ms": event.timestamp_ms,
        "wallet_address": event.wallet_address,
        "coin": event.coin,
        "leader_action": event.leader_action,
        "leader_side": event.leader_side,
        "bot_decision": event.bot_decision,
        "status": event.status,
        "reason": event.reason,
        "estimated_net_pnl_usdc": event.estimated_net_pnl_usdc,
        "edge_remaining_bps": event.edge_remaining_bps,
        "copy_degradation_bps": event.copy_degradation_bps,
        "signal_age_ms": event.signal_age_ms,
        "plain_english": event.plain_english,
        "read_only": True,
        "execution": "forbidden",
    }
