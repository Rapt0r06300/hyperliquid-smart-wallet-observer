"""Machine-readable normative gate registry for the canonical proof chain."""
from __future__ import annotations
import hashlib
import json
from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class ProofGate:
    gate_id: str
    owner: str
    input_evidence: tuple[str, ...]
    validator: str
    failure_code: str
    blocks: tuple[str, ...]

GATES = (
    ProofGate("PROVENANCE", "dataset_v2", ("release_manifest", "asset_sha256"), "validate_publication_receipts", "PROVENANCE_INVALID", ("QUALITY", "REPLAY", "BACKTEST")),
    ProofGate("STORAGE", "dataset_v2", ("compressed_bytes", "uncompressed_bytes_receipt", "storage_coverage"), "validate_dataset_health_receipt", "STORAGE_COVERAGE_INCOMPLETE", ("QUALITY", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER")),
    ProofGate("CROSS_REPO_PUBLICATION", "dataset_v2", ("publication_receipt", "main_alina_head", "dataset_head", "manifest_sha256"), "reconcile_publication_consistency", "CROSS_REPO_IDENTITY_INVALID", ("QUALITY", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER")),
    ProofGate("SECURITY", "alina", ("paper_only", "read_only", "real_execution"), "validate_closure_receipt", "EXECUTION_SURFACE_INVALID", ("DONE",)),
    ProofGate("QUALITY", "dataset_v2", ("manifest", "gap_counts", "sequence_state"), "check_dataset_quality", "QUALITY_NOT_SAFE", ("REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER")),
    ProofGate("COUNT_EXACTNESS", "dataset_v2", ("exact_record_counts", "exact_trade_counts", "global_unique_trade_count", "cross_shard_overlap_count"), "validate_dataset_health_receipt", "COUNT_COVERAGE_INCOMPLETE", ("REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF")),
    ProofGate("REPLAY_COMPATIBLE", "dataset_v2", ("safe_manifest", "replay_compatibility_receipt"), "enforce_safe_replay_invariant", "REPLAY_COMPATIBILITY_NOT_PROVEN", ("REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER")),
    ProofGate("REPLAY", "alina", ("frozen_selection", "replay_receipt"), "run_economic_objective_campaigns", "REPLAY_NOT_DETERMINISTIC", ("BACKTEST", "OOS", "FORWARD_PAPER")),
    ProofGate("BACKTEST", "alina", ("replay_events", "cost_model"), "run_economic_objective_campaigns", "BACKTEST_NOT_COMPLETE", ("OOS", "FORWARD_PAPER", "PNL_PROOF")),
    ProofGate("OOS", "alina", ("frozen_experiment_identity", "backtest_artifact"), "validate_closure_receipt", "OOS_IDENTITY_INVALID", ("FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD")),
    ProofGate("FORWARD_PAPER", "alina", ("oos_receipt", "paper_observations"), "validate_closure_receipt", "FORWARD_IDENTITY_INVALID", ("PNL_PROOF", "SCOREBOARD")),
    ProofGate("PNL_PROOF", "alina", ("safe_replay_events", "canonical_ledger", "module_certificate"), "module_pnl_proof", "PNL_PROOF_UNMEASURABLE", ("SCOREBOARD",)),
    ProofGate("SCOREBOARD", "alina", ("module_certificates", "oos_receipt", "forward_receipt"), "validate_closure_receipt", "SCOREBOARD_NOT_BOUND", ("DONE",)),
)

def gate_contract() -> dict[str, object]:
    rows=[asdict(g) for g in GATES]
    encoded=json.dumps(rows,sort_keys=True,separators=(",",":")).encode()
    return {
        "schema":"alina.normative_gate_registry.v1",
        "gates":rows,
        "gate_count":len(rows),
        "registry_digest":hashlib.sha256(encoded).hexdigest(),
        "paper_only":True,
        "read_only":True,
        "real_execution":False,
    }

__all__=["GATES","ProofGate","gate_contract"]
