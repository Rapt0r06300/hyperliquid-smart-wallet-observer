"""Contrat autoritaire des flags critiques du runtime HyperSmart.

Le lanceur Windows reste le point d'assignation, mais ces valeurs sont la verite
machine-verifiable : le preflight refuse tout profil divergent avant le demarrage
du moteur. Cela evite qu'un ancien flag paper/carry soit reactive silencieusement.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
import json
import os
from pathlib import Path
from collections.abc import Sequence
from typing import Mapping

from hl_observer.strategies.active_scope import OFFICIAL_SCOPE_FAMILY, OFFICIAL_SCOPE_VERSION

# Flags qui doivent deja etre presents lorsque preflight_lanceur s'execute.
PREFLIGHT_RUNTIME_FLAGS = MappingProxyType({
    "HL_ENV": "paper",
    "HL_ENABLE_MAINNET_EXECUTION": "0",
    "HL_ENABLE_TESTNET_EXECUTION": "0",
    "HYPERSMART_MODE": "SIMULATION_ONLY_UNTIL_MANUAL_REVIEW",
    "HYPERSMART_STARTUP_PROFILE": "harvest",
    # La voie v1 ecrivait dans le ledger UI historique. Elle est quarantinee :
    # seul EXPERIMENTAL_PAPER v2 porte le cross-venue actif.
    "HYPERSMART_ARB_DISLOCATION_PAPER": "0",
    "HYPERSMART_EXPERIMENTAL_PAPER": "1",
    "HYPERSMART_EXPLORATORY_PAPER": "1",
    "HYPERSMART_EXPERIMENTAL_CROSS_VENUE_GELE": "0",
    "HYPERSMART_FUNDING_ARB_PAPER": "0",
    "HYPERSMART_V9_PIPELINE_AUTHORITATIVE": "1",
    "HYPERSMART_V12_GATE_AUTHORITATIVE": "1",
    "HYPERSMART_RESET_ON_LAUNCH": "0",
    "HYPERSMART_ENABLE_AUX_IA": "0",
    "HYPERSMART_ENABLE_AUX_STREAM": "1",
    "HYPERSMART_ACTIVE_STRATEGY_SCOPE": OFFICIAL_SCOPE_FAMILY,
    "HYPERSMART_SCOPE_VERSION": OFFICIAL_SCOPE_VERSION,
})

# Ces flags sont assignes plus loin dans le .cmd, mais avant tout writer/economic
# runtime. Les tests de contrat les verrouillent egalement contre toute resurrection
# du carry historique.
POST_PREFLIGHT_RUNTIME_FLAGS = MappingProxyType({
    "HYPERSMART_CARRY_HYPE_PAPER": "0",
    "HYPERSMART_CARRY_ETAPE2": "0",
    "HYPERSMART_CARRY_DISABLED": "1",
})

CRITICAL_RUNTIME_FLAGS = MappingProxyType({
    **dict(PREFLIGHT_RUNTIME_FLAGS),
    **dict(POST_PREFLIGHT_RUNTIME_FLAGS),
})

# Machine-readable contract for the two collection lanes.  The workflow tests
# bind this contract to the checked-in GitHub-hosted controller/worker files so
# a renamed job or a missing durable handoff cannot silently become a local
# assumption.
RESUMABLE_COLLECTION_CONTRACT = MappingProxyType({
    "controller_workflow": ".github/workflows/resumable-campaign-controller.yml",
    "worker_workflow": ".github/workflows/resumable-campaign-worker.yml",
    "collection_jobs": ("copy_work", "other_work"),
    "controller_outputs": (
        "copy_matrix",
        "copy_count",
        "other_matrix",
        "other_count",
        "phase",
        "phase_epoch",
    ),
    "worker_phase_guards": ("--expected-phase", "--expected-epoch"),
    "durable_worker_markers": (
        "Claim durable campaign lease",
        "Persist collection data or analysis evidence (SAFE certification first)",
        "id: durable",
    ),
})

OFFICIAL_LAUNCH_CONTRACT = MappingProxyType({
    "runtime_entrypoint": "LANCER_HYPERSMART.cmd",
    "runtime_handoff": "tools/start_hypersmart_simulation.ps1",
    "ui_service": "-m hl_observer ui",
    "collector_dispatch": "hl_observer.ops.superviseur_collecteurs demarrer-tous harvest",
    "collector_stop": "hl_observer.ops.superviseur_collecteurs arreter",
    "scope_module": "src/hl_observer/strategies/active_scope.py",
    "scope_family": OFFICIAL_SCOPE_FAMILY,
    "scope_version": OFFICIAL_SCOPE_VERSION,
    "hosted_controller": ".github/workflows/resumable-campaign-controller.yml",
    "mode": "paper",
})

# Machine-readable consumer inventory for the launch parameters.  The inventory
# is deliberately small and canonical: it describes consumers, not another
# configuration source, and is audited for file existence at startup checks.
RUNTIME_PARAMETER_CONSUMERS = MappingProxyType({
    "scope": (
        "src/hl_observer/strategies/active_scope.py",
        "src/hl_observer/ops/preflight_lanceur.py",
    ),
    "orchestration": (
        "tools/start_hypersmart_simulation.ps1",
        "src/hl_observer/ops/global_observer_pipeline.py",
    ),
    "collection": (
        "src/hl_observer/ops/superviseur_collecteurs.py",
        "src/hl_observer/runtime/persistent_poll_runner.py",
    ),
    "inventory": (
        "tools/scan_economic_hardcodes.py",
        "src/hl_observer/ops/scope_flag_inventory.py",
    ),
})

ORCHESTRATION_BOUNDARY = MappingProxyType({
    "launcher": "LANCER_HYPERSMART.cmd",
    "orchestrator": "tools/start_hypersmart_simulation.ps1",
    "quant_engine": "src/hl_observer/ops/global_observer_pipeline.py",
    "hosted_controller": ".github/workflows/resumable-campaign-controller.yml",
    "paper_only": True,
})

# A child process must not inherit an operator's permissive experiment or
# execution switch.  The deny list is intentionally explicit and small: it is
# a safety boundary, not a generic environment scrubber.
CHILD_ENV_DENY_KEYS = frozenset({
    "HYPERSMART_ACTIVE_STRATEGIES",
    "HYPERSMART_ENABLE_MAINNET_EXECUTION",
    "HYPERSMART_ENABLE_TESTNET_EXECUTION",
    "REAL_MAINNET_TRADING",
    "TESTNET_EXECUTION_ENABLED",
    "START_MAINNET_EXECUTION",
    "START_TESTNET_EXECUTION",
    "HYPERSMART_EXECUTION_ENDPOINT",
    "HYPERSMART_PRIVATE_KEY",
    "HL_PRIVATE_KEY",
    "PRIVATE_KEY",
})

CHILD_RUNTIME_OVERRIDES = MappingProxyType({
    **dict(CRITICAL_RUNTIME_FLAGS),
    "REAL_MAINNET_TRADING": "false",
    "TESTNET_ONLY": "true",
    "HYPERSMART_ANALYSIS_LOCAL_ONLY": "1",
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
})


@dataclass(frozen=True)
class RuntimeContractResult:
    ok: bool
    mismatches: tuple[str, ...]

    @property
    def detail(self) -> str:
        return "profil runtime conforme" if self.ok else "; ".join(self.mismatches)


def verify_runtime_env(
    env: Mapping[str, str],
    *,
    expected: Mapping[str, str] = PREFLIGHT_RUNTIME_FLAGS,
) -> RuntimeContractResult:
    """Compare l'environnement au contrat exact, sans valeur implicite.

    Un flag absent est un echec : un runtime critique ne doit jamais dependre de
    l'environnement parent ou d'un ancien terminal Windows.
    """
    mismatches: list[str] = []
    for key, wanted in expected.items():
        actual = env.get(key)
        if actual is None:
            mismatches.append(f"{key}=MISSING (attendu {wanted})")
            continue
        got = str(actual).strip()
        if got != wanted:
            mismatches.append(f"{key}={got!r} (attendu {wanted!r})")
    return RuntimeContractResult(not mismatches, tuple(mismatches))


def build_safe_child_environment(
    parent: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a deny-by-default paper environment for a child process.

    Parent values are retained only when they are not known control-plane
    overrides.  Canonical runtime flags are then written explicitly, so an
    absent or permissive parent variable cannot activate execution or another
    strategy family in the child.
    """
    environment = dict(parent if parent is not None else os.environ)
    for key in CHILD_ENV_DENY_KEYS:
        environment.pop(key, None)
    environment.update(CHILD_RUNTIME_OVERRIDES)
    return environment


def verify_safe_child_environment(env: Mapping[str, str]) -> RuntimeContractResult:
    """Verify both the canonical flags and the absence of inherited overrides."""
    mismatches = list(verify_runtime_env(env).mismatches)
    for key in sorted(CHILD_ENV_DENY_KEYS):
        if key in env and key not in CHILD_RUNTIME_OVERRIDES:
            mismatches.append(f"{key}=INHERITED_OVERRIDE")
    if env.get("REAL_MAINNET_TRADING") != "false":
        mismatches.append("REAL_MAINNET_TRADING must be false")
    if env.get("TESTNET_ONLY") != "true":
        mismatches.append("TESTNET_ONLY must be true")
    return RuntimeContractResult(not mismatches, tuple(mismatches))


def parse_cmd_set_assignments(text: str) -> dict[str, list[str]]:
    """Extrait les `set \"KEY=VALUE\"` actifs d'un lanceur .cmd.

    Les lignes REM sont ignorees. Plusieurs valeurs pour une cle sont conservees
    afin que les tests puissent detecter un double source-of-truth contradictoire.
    """
    out: dict[str, list[str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("rem "):
            continue
        low = line.lower()
        if not low.startswith('set "') or not line.endswith('"'):
            continue
        body = line[5:-1]
        if "=" not in body:
            continue
        key, value = body.split("=", 1)
        out.setdefault(key, []).append(value)
    return out


def _is_hex(value: object, *, length: int) -> bool:
    if not isinstance(value, str) or len(value) != length:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def websocket_snapshot_receipt(frames: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Prove WS snapshot/ack/reconnect semantics without inventing events.

    ``isSnapshot`` is intentionally mandatory for every non-ACK frame.  A
    reconnect duplicate is retained in the audit result but contributes once
    to the causal event count, so a snapshot can never become a live event.
    """
    if not isinstance(frames, Sequence) or isinstance(frames, (str, bytes)):
        return {"status": "UNKNOWN", "reason": "frames_not_sequence"}
    ack_seen = False
    identities: set[str] = set()
    live_ids: set[str] = set()
    snapshots = 0
    duplicates = 0
    for frame in frames:
        if not isinstance(frame, Mapping):
            return {"status": "UNKNOWN", "reason": "frame_not_mapping"}
        kind = str(frame.get("kind") or frame.get("type") or "").upper()
        if kind in {"ACK", "SUBSCRIPTION_ACK"}:
            ack_seen = True
            continue
        marker = frame.get("isSnapshot")
        identity = frame.get("native_id") or frame.get("tid") or frame.get("hash")
        if type(marker) is not bool or not _nonempty(identity):
            return {"status": "UNKNOWN", "reason": "snapshot_marker_or_identity_missing"}
        key = str(identity)
        if key in identities:
            duplicates += 1
        identities.add(key)
        if marker:
            snapshots += 1
        else:
            live_ids.add(key)
    if not ack_seen:
        return {"status": "UNKNOWN", "reason": "ack_missing"}
    if not frames:
        return {"status": "UNKNOWN", "reason": "frames_empty"}
    return {
        "status": "PROVEN",
        "ack_seen": True,
        "snapshot_count": snapshots,
        "unique_event_count": len(identities),
        "causal_live_event_count": len(live_ids),
        "duplicates_removed": duplicates,
        "replay_admissible": True,
    }


def websocket_unique_users_receipt(
    subscriptions: Sequence[Mapping[str, object]], *, expected_users: int = 10
) -> dict[str, object]:
    """Require ACKed subscriptions for a complete unique-user WS campaign."""
    if type(expected_users) is not int or expected_users <= 0:
        return {"status": "UNKNOWN", "reason": "expected_users_invalid"}
    user_ids: set[str] = set()
    for row in subscriptions:
        if not isinstance(row, Mapping) or row.get("ack") is not True:
            return {"status": "UNKNOWN", "reason": "subscription_ack_missing"}
        user_id = row.get("user_id")
        if not _nonempty(user_id):
            return {"status": "UNKNOWN", "reason": "user_id_missing"}
        user_ids.add(str(user_id))
    status = "PROVEN" if len(user_ids) >= expected_users else "UNKNOWN"
    return {"status": status, "unique_users": len(user_ids), "expected_users": expected_users}


def health_receipt_gate(
    receipt: Mapping[str, object] | str | Path, *, expected_schema: int
) -> dict[str, object]:
    """Fail closed when the health receipt is absent, stale, or malformed."""
    if isinstance(receipt, (str, Path)):
        try:
            payload = json.loads(Path(receipt).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"status": "UNKNOWN", "reason": "receipt_unavailable"}
    else:
        payload = receipt
    if not isinstance(payload, Mapping):
        return {"status": "UNKNOWN", "reason": "receipt_not_mapping"}
    checks = payload.get("checks")
    ok = (
        type(payload.get("schema_version")) is int
        and payload.get("schema_version") == expected_schema
        and payload.get("status") == "HEALTHY"
        and _is_hex(payload.get("source_sha256"), length=64)
        and _nonempty(payload.get("created_at_utc"))
        and isinstance(checks, Mapping)
        and bool(checks)
        and all(value is True for value in checks.values())
    )
    return {"status": "PROVEN" if ok else "UNKNOWN", "schema_version": payload.get("schema_version")}


def campaign_binding_receipt(
    *,
    code_sha: object,
    manifest_code_sha: object,
    dataset_selection_id: object,
    expected_dataset_selection_id: object,
    phase_epoch: object,
) -> dict[str, object]:
    """Bind campaign execution to one code SHA, dataset selection, and epoch."""
    ok = (
        _is_hex(code_sha, length=40)
        and code_sha == manifest_code_sha
        and _nonempty(dataset_selection_id)
        and dataset_selection_id == expected_dataset_selection_id
        and type(phase_epoch) is int
        and phase_epoch >= 0
    )
    return {
        "status": "PROVEN" if ok else "UNKNOWN",
        "code_sha": code_sha,
        "dataset_selection_id": dataset_selection_id,
        "phase_epoch": phase_epoch,
    }


def partition_quarantine_receipt(
    partitions: Sequence[Mapping[str, object]],
    *,
    expected_partitions: int = 8,
    total_count: int,
    total_unique_count: int,
) -> dict[str, object]:
    """Require every quarantine partition and reconcile global counters."""
    if type(expected_partitions) is not int or expected_partitions <= 0:
        return {"status": "UNKNOWN", "reason": "partition_expectation_invalid"}
    if len(partitions) != expected_partitions:
        return {"status": "UNKNOWN", "reason": "partition_count_mismatch"}
    ids: set[str] = set()
    count = 0
    unique_count = 0
    for row in partitions:
        if not isinstance(row, Mapping):
            return {"status": "UNKNOWN", "reason": "partition_not_mapping"}
        partition_id = row.get("partition_id")
        if not _nonempty(partition_id) or str(partition_id) in ids:
            return {"status": "UNKNOWN", "reason": "partition_id_invalid"}
        if row.get("status") != "QUARANTINED" or not _is_hex(row.get("sha256"), length=64):
            return {"status": "UNKNOWN", "reason": "partition_integrity_missing"}
        record_count = row.get("record_count")
        row_unique_count = row.get("unique_count")
        if type(record_count) is not int or record_count < 0:
            return {"status": "UNKNOWN", "reason": "record_count_invalid"}
        if type(row_unique_count) is not int or row_unique_count < 0 or row_unique_count > record_count:
            return {"status": "UNKNOWN", "reason": "unique_count_invalid"}
        ids.add(str(partition_id))
        count += record_count
        unique_count += row_unique_count
    ok = count == total_count and unique_count == total_unique_count
    return {
        "status": "PROVEN" if ok else "UNKNOWN",
        "partition_count": len(ids),
        "record_count": count,
        "unique_count": unique_count,
    }


def safe_replay_chain_receipt(stages: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    """Prove one SHA-bound SAFE shard path through sync, loader, and replay."""
    required = ("sync", "book_loader", "replay")
    if any(not isinstance(stages.get(name), Mapping) for name in required):
        return {"status": "UNKNOWN", "reason": "chain_stage_missing"}
    rows = [stages[name] for name in required]
    code_shas = {row.get("code_sha") for row in rows}
    dataset_shas = {row.get("dataset_sha256") for row in rows}
    ok = (
        all(row.get("status") == "PROVEN" for row in rows)
        and len(code_shas) == 1
        and len(dataset_shas) == 1
        and all(_is_hex(value, length=64) for value in dataset_shas)
        and all(_is_hex(value, length=40) for value in code_shas)
        and rows[0].get("safe") is True
        and type(rows[-1].get("replay_rows")) is int
        and rows[-1].get("replay_rows") > 0
    )
    return {"status": "PROVEN" if ok else "UNKNOWN", "stages": list(required)}


def freeze_discovery_receipt(cycles: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Require discovery to continue after at least two independent freezes."""
    if len(cycles) < 2:
        return {"status": "UNKNOWN", "reason": "two_cycles_required"}
    for cycle in cycles:
        if (
            not isinstance(cycle, Mapping)
            or not _nonempty(cycle.get("cycle_id"))
            or cycle.get("freeze_status") != "FROZEN"
            or cycle.get("discovery_status") != "CONTINUED"
            or cycle.get("continued_after_freeze") is not True
        ):
            return {"status": "UNKNOWN", "reason": "freeze_discovery_cycle_invalid"}
    return {"status": "PROVEN", "cycles": len(cycles)}


def release_atomicity_receipt(
    *, asset: Mapping[str, object], manifest: Mapping[str, object],
    receipt: Mapping[str, object], checkpoint: Mapping[str, object],
) -> dict[str, object]:
    """Reject releases whose asset, manifest, receipt, and checkpoint diverge."""
    rows = (asset, manifest, receipt, checkpoint)
    hashes = {row.get("sha256") for row in rows}
    ok = (
        all(isinstance(row, Mapping) and row.get("status") == "PUBLISHED" for row in rows)
        and len(hashes) == 1
        and all(_is_hex(value, length=64) for value in hashes)
        and checkpoint.get("resume_idempotent") is True
        and checkpoint.get("partial") is False
    )
    return {"status": "PROVEN" if ok else "UNKNOWN", "sha256": next(iter(hashes), None)}


def publication_loop_receipt(workflow_text: str) -> dict[str, object]:
    """Check bot-loop, empty-commit, and current-HEAD publication guards."""
    required = (
        "github.actor != 'github-actions[bot]'",
        "git diff --cached --quiet",
        "git rev-parse HEAD",
        "--main-head",
    )
    found = {marker: marker in workflow_text for marker in required}
    return {"status": "PROVEN" if all(found.values()) else "UNKNOWN", "guards": found}


def ccxt_execution_dependency_receipt(
    imports: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Allow ccxt only as discovery-only input, never as an execution path."""
    unsafe = []
    seen = False
    for row in imports:
        if not isinstance(row, Mapping):
            unsafe.append("row_not_mapping")
            continue
        package = str(row.get("package") or "")
        if package != "ccxt":
            continue
        seen = True
        module = str(row.get("module") or "")
        if row.get("execution_capable") is True or row.get("order_methods") is True:
            unsafe.append(module or "unknown_module")
        if module != "hl_observer.markets.ccxt_universe":
            unsafe.append(module or "unknown_module")
    return {"status": "PROVEN" if seen and not unsafe else "UNKNOWN", "unsafe_modules": unsafe}


def global_trade_dedup_receipt(
    partitions: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Require complete SHA-bound partitions and globally unique trade IDs."""
    ids: list[str] = []
    for row in partitions:
        if not isinstance(row, Mapping):
            return {"status": "UNKNOWN", "reason": "partition_not_mapping"}
        if row.get("coverage_complete") is not True or not _is_hex(row.get("sha256"), length=64):
            return {"status": "UNKNOWN", "reason": "partition_not_complete"}
        trade_ids = row.get("trade_ids")
        if not isinstance(trade_ids, Sequence) or isinstance(trade_ids, (str, bytes)):
            return {"status": "UNKNOWN", "reason": "trade_ids_missing"}
        if any(not _nonempty(item) for item in trade_ids):
            return {"status": "UNKNOWN", "reason": "trade_identity_missing"}
        ids.extend(str(item) for item in trade_ids)
    unique = len(set(ids))
    return {
        "status": "PROVEN" if ids and unique == len(ids) else "UNKNOWN",
        "trade_count": len(ids),
        "unique_trade_count": unique,
    }


def global_closure_receipt(report: Mapping[str, object]) -> dict[str, object]:
    """Allow closure only when the real index and every task are complete."""
    total = report.get("total_tasks")
    verified = report.get("verified_tasks")
    ok = (
        report.get("status") == "CLOSED"
        and report.get("coverage_complete") is True
        and _is_hex(report.get("index_sha256"), length=64)
        and _is_hex(report.get("receipt_digest"), length=64)
        and type(total) is int
        and total > 0
        and type(verified) is int
        and verified == total
    )
    return {"status": "PROVEN" if ok else "UNKNOWN", "total_tasks": total, "verified_tasks": verified}


def copy_vault_coverage_receipt(lanes: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Require every published lane to be proven and replay-compatible."""
    if not lanes:
        return {"status": "UNKNOWN", "reason": "lanes_empty"}
    for lane in lanes:
        if (
            not isinstance(lane, Mapping)
            or lane.get("family") != "copy_vault"
            or lane.get("status") != "PROVEN"
            or lane.get("replay_compatible") is not True
            or type(lane.get("shards")) is not int
            or lane.get("shards") <= 0
            or not _is_hex(lane.get("source_sha256"), length=64)
        ):
            return {"status": "UNKNOWN", "reason": "lane_not_proven"}
    return {"status": "PROVEN", "lanes": len(lanes), "shards": sum(int(row["shards"]) for row in lanes)}


def hosted_resume_receipt(
    runs: Sequence[Mapping[str, object]], *, expected_code_sha: object
) -> dict[str, object]:
    """Require two completed GitHub-hosted exact-SHA resumptions."""
    run_ids = set()
    state_shas = set()
    ok = _is_hex(expected_code_sha, length=40) and len(runs) >= 2
    for row in runs:
        if not isinstance(row, Mapping):
            ok = False
            continue
        run_ids.add(row.get("run_id"))
        state_shas.add(row.get("persisted_state_sha256"))
        ok = ok and (
            _nonempty(row.get("run_id"))
            and row.get("runner_kind") == "github-hosted"
            and row.get("status") == "COMPLETED"
            and row.get("code_sha") == expected_code_sha
            and _is_hex(row.get("persisted_state_sha256"), length=64)
            and _nonempty(row.get("artifact"))
        )
    ok = ok and len(run_ids) == len(runs) and len(state_shas) == 1
    return {"status": "PROVEN" if ok else "UNKNOWN", "runs": len(run_ids)}


def scoreboard_terminal_receipt(scoreboard: Mapping[str, object]) -> dict[str, object]:
    """Require a manually authorized terminal scoreboard in paper mode."""
    current = scoreboard.get("current_epoch")
    archived = scoreboard.get("archived_epoch")
    ok = (
        scoreboard.get("phase") == "DONE"
        and scoreboard.get("manual_order_ack") is True
        and scoreboard.get("execution_enabled") is False
        and type(current) is int
        and type(archived) is int
        and archived < current
    )
    return {"status": "PROVEN" if ok else "UNKNOWN", "phase": scoreboard.get("phase")}


def ci_terminal_gate_receipt(run: Mapping[str, object]) -> dict[str, object]:
    """Separate intentional supersession from an unproven CI cancellation."""
    if run.get("status") == "CANCELLED" and run.get("superseded_by_newer_sha") is True:
        return {"status": "EXPECTED_CANCELLED", "reason": "superseded"}
    ok = (
        run.get("status") == "COMPLETED"
        and run.get("conclusion") == "success"
        and run.get("head_stable") is True
        and run.get("terminal_gate") is True
        and _is_hex(run.get("head_sha"), length=40)
    )
    return {"status": "PROVEN" if ok else "UNKNOWN", "head_sha": run.get("head_sha")}


def campaign_diagnostic_receipt(
    *, manifest_path: object, reason_code: object, phase_epoch: object | None,
) -> dict[str, object]:
    """Expose a stable, non-sensitive reason/file/epoch diagnostic."""
    ok = _nonempty(manifest_path) and _nonempty(reason_code) and (
        phase_epoch is None or (type(phase_epoch) is int and phase_epoch >= 0)
    )
    return {
        "status": "PROVEN" if ok else "UNKNOWN",
        "manifest_path": str(manifest_path),
        "reason_code": str(reason_code),
        "phase_epoch": phase_epoch,
    }


def capability_runtime_receipt(
    payload: Mapping[str, object], *, expected_sha: object
) -> dict[str, object]:
    """Reject a healthy capability snapshot produced by an older SHA."""
    ok = (
        _is_hex(expected_sha, length=40)
        and payload.get("github_sha") == expected_sha
        and payload.get("runner_kind") == "github-hosted"
        and payload.get("paper_read_only") is True
        and payload.get("real_execution") is False
        and _is_hex(payload.get("receipt_digest"), length=64)
        and _nonempty(payload.get("generated_at_utc"))
        and _nonempty(payload.get("schema_version"))
    )
    return {"status": "PROVEN" if ok else "UNKNOWN", "github_sha": payload.get("github_sha")}


__all__ = [
    "PREFLIGHT_RUNTIME_FLAGS",
    "POST_PREFLIGHT_RUNTIME_FLAGS",
    "CRITICAL_RUNTIME_FLAGS",
    "RESUMABLE_COLLECTION_CONTRACT",
    "OFFICIAL_LAUNCH_CONTRACT",
    "RUNTIME_PARAMETER_CONSUMERS",
    "ORCHESTRATION_BOUNDARY",
    "CHILD_ENV_DENY_KEYS",
    "CHILD_RUNTIME_OVERRIDES",
    "RuntimeContractResult",
    "verify_runtime_env",
    "build_safe_child_environment",
    "verify_safe_child_environment",
    "parse_cmd_set_assignments",
    "websocket_snapshot_receipt",
    "websocket_unique_users_receipt",
    "health_receipt_gate",
    "campaign_binding_receipt",
    "partition_quarantine_receipt",
    "safe_replay_chain_receipt",
    "freeze_discovery_receipt",
    "release_atomicity_receipt",
    "publication_loop_receipt",
    "ccxt_execution_dependency_receipt",
    "global_trade_dedup_receipt",
    "global_closure_receipt",
    "copy_vault_coverage_receipt",
    "hosted_resume_receipt",
    "scoreboard_terminal_receipt",
    "ci_terminal_gate_receipt",
    "campaign_diagnostic_receipt",
    "capability_runtime_receipt",
]
