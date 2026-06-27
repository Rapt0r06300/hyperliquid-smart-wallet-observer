from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from time import time

from hl_observer.simulation.decision_replay_analyzer import (
    DECISION_LOG_FILES,
    analyze_decision_logs_summary,
    default_logs_to_send_dir,
)


@dataclass(frozen=True, slots=True)
class RealtimeHealthReport:
    source_dir: Path
    events_seen: int
    latest_file_age_seconds: float | None
    status: str
    reason: str
    read_only: bool = True
    network_required: bool = False
    replay_write_warnings: tuple[str, ...] = ()


def check_realtime_health(log_dir: Path | None = None, *, stale_after_seconds: int = 30) -> RealtimeHealthReport:
    log_dir = log_dir or default_logs_to_send_dir()
    analysis = analyze_decision_logs_summary(log_dir)
    replay_age, replay_warnings = _replay_state_info(log_dir)
    if replay_age is not None and replay_age <= stale_after_seconds:
        return RealtimeHealthReport(
            source_dir=log_dir,
            events_seen=analysis.event_count,
            latest_file_age_seconds=round(replay_age, 3),
            status="LIVE_REPLAY_FROM_LOCAL_LOGS",
            reason="Replay local recent; ce n'est pas un flux marche live.",
            replay_write_warnings=replay_warnings,
        )
    latest_age = _latest_log_age_seconds(log_dir)
    if analysis.event_count == 0:
        return RealtimeHealthReport(
            source_dir=log_dir,
            events_seen=0,
            latest_file_age_seconds=latest_age,
            status="NO_EVENTS",
            reason="Aucun evenement local dans les logs a envoyer.",
            replay_write_warnings=replay_warnings,
        )
    if latest_age is not None and latest_age > stale_after_seconds:
        return RealtimeHealthReport(
            source_dir=log_dir,
            events_seen=analysis.event_count,
            latest_file_age_seconds=round(latest_age, 3),
            status="STALE",
            reason=_stale_reason(stale_after_seconds, replay_warnings),
            replay_write_warnings=replay_warnings,
        )
    return RealtimeHealthReport(
        source_dir=log_dir,
        events_seen=analysis.event_count,
        latest_file_age_seconds=round(latest_age or 0.0, 3),
        status="LIVE_FROM_LOCAL_LOGS",
        reason="Des evenements recents alimentent le replay local.",
        replay_write_warnings=replay_warnings,
    )


def format_realtime_health(report: RealtimeHealthReport) -> str:
    return "\n".join(
        [
            "realtime_health=local_read_only",
            f"source_dir={report.source_dir}",
            f"events_seen={report.events_seen}",
            f"latest_file_age_seconds={report.latest_file_age_seconds}",
            f"status={report.status}",
            f"reason={report.reason}",
            "replay_write_warnings=" + " || ".join(report.replay_write_warnings)
            if report.replay_write_warnings
            else "replay_write_warnings=none",
            f"read_only={str(report.read_only).lower()}",
            f"network_required={str(report.network_required).lower()}",
        ]
    )


def _latest_log_age_seconds(log_dir: Path) -> float | None:
    if not log_dir.exists():
        return None
    relevant = set(DECISION_LOG_FILES) | {
        "simulation_snapshot_latest.json",
        "simulation_export_state.json",
        "realtime_replay_latest.jsonl",
        "realtime_replay_state.json",
        "cli_simulation_snapshot_latest.json",
        "cli_simulation_decisions_latest.jsonl",
    }
    files = [path for path in log_dir.glob("*") if path.is_file() and path.name in relevant]
    if not files:
        return None
    latest_mtime = max(path.stat().st_mtime for path in files)
    return max(0.0, time() - latest_mtime)


def _replay_state_info(log_dir: Path) -> tuple[float | None, tuple[str, ...]]:
    state_path = log_dir / "realtime_replay_state.json"
    if not state_path.exists():
        return None, ()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None, ()
    try:
        replayed_at_ms = int(payload.get("replayed_at_ms"))
    except (TypeError, ValueError):
        return None, ()
    raw_warnings = payload.get("write_warnings")
    warnings = (
        tuple(str(item) for item in raw_warnings if item)
        if isinstance(raw_warnings, list)
        else ()
    )
    return max(0.0, (time() * 1000 - replayed_at_ms) / 1000), warnings


def _stale_reason(stale_after_seconds: int, replay_warnings: tuple[str, ...]) -> str:
    base = f"Dernier log plus vieux que {stale_after_seconds}s."
    if replay_warnings:
        return base + " Le dernier replay a aussi signale des fichiers runtime non rafraichis."
    return base
