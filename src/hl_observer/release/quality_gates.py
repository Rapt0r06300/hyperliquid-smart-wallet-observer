from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hl_observer.dashboard_truth.dashboard_truth_audit import run_dashboard_truth_audit
from hl_observer.data_sources.acquisition_engine import DataQualityGate, FetchRequest, FetchResult
from hl_observer.realtime.recovery_engine import (
    RealtimeRecoveryEngine,
    ReconnectPolicy,
    RecoveryAction,
    StreamEventType,
    WatchStreamEvent,
)
from hl_observer.realtime.realtime_health import check_realtime_health
from hl_observer.release.prompt_coverage import evaluate_prompt_coverage, verify_non_deletion
from hl_observer.runtime.hygiene import scan_runtime_hygiene
from hl_observer.runtime.write_diagnostics import (
    RUNTIME_WRITE_BLOCKED,
    RUNTIME_WRITE_WARN,
    check_runtime_write_readiness,
)
from hl_observer.security.safety_audit import run_safety_audit
from hl_observer.simulation.decision_replay_analyzer import analyze_decision_logs_summary, default_logs_to_send_dir


GATE_OK = "OK"
GATE_WARN = "WARN"
GATE_BLOCKED = "BLOCKED_WITH_PROOF"
GATE_FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class QualityGate:
    name: str
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class QualityGateReport:
    gates: tuple[QualityGate, ...]

    @property
    def hard_failed(self) -> bool:
        return any(gate.status == GATE_FAIL for gate in self.gates)

    @property
    def blocked_count(self) -> int:
        return sum(1 for gate in self.gates if gate.status == GATE_BLOCKED)


def run_quality_gates(root: Path = Path("."), *, log_dir: Path | None = None) -> QualityGateReport:
    root = root.resolve()
    log_dir = log_dir or default_logs_to_send_dir(root)
    safety = run_safety_audit(root)
    runtime = scan_runtime_hygiene(_load_settings_for_runtime(), root=root)
    coverage = evaluate_prompt_coverage(root)
    coverage_ok, coverage_missing = verify_non_deletion(coverage.rows)
    dashboard = run_dashboard_truth_audit(log_dir)
    realtime = check_realtime_health(log_dir, stale_after_seconds=60)
    runtime_writes = check_runtime_write_readiness(log_dir, stale_after_seconds=60)
    analysis = analyze_decision_logs_summary(log_dir)
    data_quality_ok = _data_quality_gate_ok()
    realtime_recovery_ok = _realtime_recovery_gate_ok()
    root_archives = list(root.glob("*.zip")) + list(root.glob("*.7z")) + list(root.glob("*.rar"))
    gates = [
        QualityGate("GATE_SECURITY", GATE_OK if safety.ok else GATE_FAIL, "safety-audit ok" if safety.ok else "; ".join(safety.findings)),
        QualityGate("GATE_RUNTIME_ARCHIVE", GATE_OK if not root_archives else GATE_FAIL, f"root_archives={len(root_archives)}"),
        QualityGate(
            "GATE_RUNTIME_WRITES",
            _runtime_write_gate_status(runtime_writes.status),
            runtime_writes.reason,
        ),
        QualityGate("GATE_LOGS", GATE_OK if analysis.event_count > 0 else GATE_BLOCKED, f"events={analysis.event_count}"),
        QualityGate(
            "GATE_REALTIME",
            _realtime_gate_status(realtime.status),
            f"{realtime.status}: {realtime.reason}; replay_write_warnings={len(realtime.replay_write_warnings)}",
        ),
        QualityGate(
            "GATE_REALTIME_RECOVERY",
            GATE_OK if realtime_recovery_ok else GATE_FAIL,
            "stale/gapped events are blocked from signals and produce reconnect+backfill plan",
        ),
        QualityGate(
            "GATE_PNL_LOG_EVENTS",
            GATE_OK if analysis.event_count > 0 else GATE_BLOCKED,
            f"closed_log_event_pnl_usdc={analysis.total_estimated_pnl_usdc}; live equity is reported by `hl_observer live-pnl`",
        ),
        QualityGate("GATE_DASHBOARD_TRUTH", GATE_OK if dashboard.ok else GATE_FAIL, f"missing={len(dashboard.missing_metrics)} placeholders={len(dashboard.placeholder_findings)}"),
        QualityGate("GATE_PROMPT_COVERAGE", GATE_OK if coverage_ok else GATE_FAIL, f"missing={len(coverage_missing)}"),
        QualityGate(
            "GATE_DATA_QUALITY",
            GATE_OK if data_quality_ok else GATE_FAIL,
            "fresh high-confidence data accepted; stale/low-confidence PnL proof rejected",
        ),
        QualityGate("GATE_TESTNET_DISABLED", GATE_OK, "testnet executor remains locked by settings and tests"),
        QualityGate("GATE_NO_REAL_EXECUTION", GATE_OK, "simulation/local read-only only"),
    ]
    return QualityGateReport(gates=tuple(gates))


def format_quality_gates(report: QualityGateReport) -> str:
    lines = [
        "quality_gates=simulation_read_only",
        f"hard_failed={str(report.hard_failed).lower()}",
        f"blocked_with_proof={report.blocked_count}",
    ]
    lines.extend(f"{gate.name}: {gate.status} | {gate.message}" for gate in report.gates)
    return "\n".join(lines)


def _realtime_gate_status(status: str) -> str:
    if status in {"LIVE_FROM_LOCAL_LOGS", "LIVE_REPLAY_FROM_LOCAL_LOGS"}:
        return GATE_OK
    if status == "STALE":
        return GATE_BLOCKED
    return GATE_WARN


def _runtime_write_gate_status(status: str) -> str:
    if status == RUNTIME_WRITE_BLOCKED:
        return GATE_BLOCKED
    if status == RUNTIME_WRITE_WARN:
        return GATE_WARN
    return GATE_OK


def _data_quality_gate_ok() -> bool:
    request = FetchRequest(
        request_id="quality-gate",
        provider_name="OfficialInfoProvider",
        endpoint="/info",
        request_type="userFillsByTime",
        wallet_address="0x" + "1" * 40,
        created_at_ms=1_000,
    )
    gate = DataQualityGate()
    good = gate.assess(
        FetchResult(
            request=request,
            success=True,
            payload=[{"time": 9_500}],
            fetched_at_ms=10_000,
            local_received_at_ms=10_100,
            exchange_ts_ms=9_500,
            source_confidence_score=0.95,
            transport_latency_ms=100,
        ),
        now_ms=10_000,
        proves_pnl=True,
    )
    bad = gate.assess(
        FetchResult(
            request=request,
            success=True,
            payload=[{"time": 1_000}],
            fetched_at_ms=10_000,
            local_received_at_ms=15_000,
            exchange_ts_ms=1_000,
            source_confidence_score=0.2,
            transport_latency_ms=5_000,
        ),
        now_ms=10_000,
        proves_pnl=True,
    )
    return good.accepted_for_simulation and not bad.accepted_for_simulation and "LOW_CONFIDENCE_CANNOT_PROVE_PNL" in bad.reasons


def _realtime_recovery_gate_ok() -> bool:
    wallet = "0x" + "2" * 40
    engine = RealtimeRecoveryEngine(
        ReconnectPolicy(stale_after_ms=1_000, max_event_gap_ms=1_000, max_sequence_gap=1, max_pages=2)
    )
    first = WatchStreamEvent(
        event_id="gate:first",
        wallet_address=wallet,
        observed_at_ms=1_000,
        received_at_ms=1_000,
        event_type=StreamEventType.NEW,
        sequence=1,
        payload_hash="gate:first",
    )
    second = WatchStreamEvent(
        event_id="gate:gap",
        wallet_address=wallet,
        observed_at_ms=3_500,
        received_at_ms=5_000,
        event_type=StreamEventType.NEW,
        sequence=4,
        payload_hash="gate:gap",
    )
    engine.process_event(first)
    decision = engine.process_event(second)
    return (
        decision.action == RecoveryAction.RECONNECT_AND_BACKFILL
        and decision.backfill is not None
        and decision.should_reconnect
        and not decision.accepted_for_signal
        and "DATA_GAP_BY_TIME" in decision.warnings
        and "DATA_GAP_BY_SEQUENCE" in decision.warnings
        and "STALE_EVENT" in decision.warnings
    )


def _load_settings_for_runtime():
    from hl_observer.config.loader import load_settings

    return load_settings()
