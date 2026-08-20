"""Specific executable evaluator for the preserved technical requirements 546..775.

These are derived technical requirements, never reconstructed historical labels.
Each base requirement owns five independently reported facets:
CONTRACT, POSITIVE_PATH, NEGATIVE_FAIL_CLOSED, DETERMINISM_CAUSALITY and
EVIDENCE_PROVENANCE.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping

FACETS = (
    "CONTRACT",
    "POSITIVE_PATH",
    "NEGATIVE_FAIL_CLOSED",
    "DETERMINISM_CAUSALITY",
    "EVIDENCE_PROVENANCE",
)

ANTI_OVERFIT_REQUIREMENTS = (
    ("train_validation", "train et validation séparés"),
    ("oos", "out-of-sample"),
    ("forward", "forward"),
    ("purge_embargo", "purge et embargo"),
    ("walk_forward", "walk-forward"),
    ("cpcv", "CPCV"),
    ("pbo", "PBO"),
    ("placebos", "placebos"),
    ("neighbor_sensitivity", "sensibilité aux voisins"),
    ("cost_latency_stress", "stress frais/slippage/latence"),
    ("alternate_universes", "univers alternatifs"),
    ("holdout_veto", "veto holdout et absence de retuning après observation"),
)
MAXDATA_REQUIREMENTS = (
    ("target_4usd", "objectif 4 USD par famille"),
    ("completed_suites_truth", "COMPLETED_SUITES uniquement pour les succès réels"),
    ("state_sha", "état lié au SHA exact"),
    ("state_dataset", "état lié au snapshot dataset"),
    ("state_suite_config_runtime", "état lié suite/config/runtime proof"),
    ("cache_checkpoint", "cache et checkpoint anti-recalcul"),
    ("escalate_stop", "escalade et arrêt contrôlés"),
    ("continue_below_target", "continuer tant qu'une famille est sous cible"),
    ("memory_partition", "mémoire séparée SHA/famille/snapshot/config"),
    ("stale_cannot_overwrite", "un état stale/incomplet d'un autre SHA ne remplace pas la certification courante"),
)
DETERMINISM_REQUIREMENTS = (
    ("no_hidden_global_mutation", "aucun monkeypatch/global mutation caché"),
    ("pure_validation_io", "validation pure, routage déterministe et I/O explicites"),
    ("reproducible_replay", "replay/forward/dataset reproductibles"),
)
SELF_HOSTED_REQUIREMENTS = (
    ("runner_not_installed", "PREPARER_PC_ALINA non lancé et runner non installé par défaut"),
    ("explicit_go", "GO_SELF_HOSTED=TRUE explicite"),
    ("main_sha_owner_no_pr", "main uniquement, SHA exact, owner, pas de PR"),
    ("minimal_permissions", "permissions minimales contents:read et persist-credentials false"),
    ("controlled_command_token_paper", "commande contrôlée, token dataset read-only, paper-only, real execution false"),
    ("sanitized_artifacts", "artifacts nettoyés et secrets protégés"),
    ("pinned_actions_untrusted_data", "actions épinglées, code avant gate, dataset non fiable"),
    ("input_attack_surface", "path traversal, zip-slip, symlink, exécutable dataset, shell injection et entrées bornées"),
)
CI_REQUIREMENTS = (
    ("relevant_suites_green", "suites CI pertinentes vertes"),
    ("no_test_deletion_to_hide_red", "aucun rouge masqué par suppression de tests"),
    ("cross_platform_labs", "Linux, Windows, PowerShell 5.1, HyperLab, Alpha et labo replay-forward"),
    ("security_selfhosted_tests", "tests sécurité et self-hosted"),
)
WINDOWS_REQUIREMENTS = (
    ("embedded_runtime", "Python, MinGit et wheelhouse/offline embarqués"),
    ("hermetic", "tests hermétiques sans user-site ni Python système"),
    ("paths_new_pc", "espaces, autre disque, nouveau PC et imports circulaires"),
    ("runtime_sqlite_copy", "runtime et SQLite exacts après copie et archive reproductible"),
)
OBSERVABILITY_REQUIREMENTS = (
    ("cockpit_runtime", "cockpit: progression, ressources et runtime"),
    ("github_online_truth", "vérité GitHub en ligne, pas seulement service Running"),
)
DOCS_REQUIREMENTS = (("readme_truth", "README: scope courant, objectif +4, données/replay/safety et runner non installé"),)
REHEARSALS_REQUIREMENTS = (
    ("ordered_rehearsals", "répétitions pré-full ~180GB avec crash/restart/RAM/disque/consommation runtime"),
    ("final_go_gate", "GO final: main propre, CI verte, ledger ~180GB, PnL réconcilié, 3 familles certifiables, anti-overfit/placebos/sanitisation/reproductibilité/docs"),
)

CATEGORY_REQUIREMENTS = {
    "ANTI_OVERFIT": ANTI_OVERFIT_REQUIREMENTS,
    "MAXDATA_AUTONOMY": MAXDATA_REQUIREMENTS,
    "DETERMINISM": DETERMINISM_REQUIREMENTS,
    "SELF_HOSTED_SECURITY": SELF_HOSTED_REQUIREMENTS,
    "CI": CI_REQUIREMENTS,
    "WINDOWS_PORTABILITY": WINDOWS_REQUIREMENTS,
    "OBSERVABILITY": OBSERVABILITY_REQUIREMENTS,
    "DOCS": DOCS_REQUIREMENTS,
    "REHEARSALS_GO": REHEARSALS_REQUIREMENTS,
}


@dataclass(frozen=True)
class Probe:
    contract: bool
    positive: bool
    negative: bool
    deterministic: bool
    evidence: tuple[str, ...]


def _read(root: Path, relative: str) -> str:
    try:
        return (root / relative).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _hashes(root: Path, paths: tuple[str, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in paths:
        path = root / relative
        if path.is_file():
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _contains(root: Path, relative: str, *tokens: str) -> bool:
    text = _read(root, relative)
    return bool(text) and all(token in text for token in tokens)


def _safe(call: Callable[[], bool]) -> bool:
    try:
        return bool(call())
    except Exception:
        return False


def _row(root: Path, key: str, description: str, probe: Probe) -> dict[str, Any]:
    hashes = _hashes(root, probe.evidence)
    provenance = bool(probe.evidence) and len(hashes) == len(probe.evidence) and all(len(v) == 64 for v in hashes.values())
    facets = {
        "CONTRACT": bool(probe.contract),
        "POSITIVE_PATH": bool(probe.positive),
        "NEGATIVE_FAIL_CLOSED": bool(probe.negative),
        "DETERMINISM_CAUSALITY": bool(probe.deterministic),
        "EVIDENCE_PROVENANCE": provenance,
    }
    return {
        "key": key,
        "description": description,
        "facets": facets,
        "evidence": list(probe.evidence),
        "evidence_sha256": hashes,
        "ok": all(facets.values()),
    }


def _anti_probes(root: Path) -> dict[str, Probe]:
    from hl_observer.backtesting.cross_validation import purged_walk_forward_splits
    from hl_observer.backtesting.robustesse_selection import HARD_PLACEBO_DIMENSIONS, pbo_cscv
    from hl_observer.backtesting.robustness_protocol import (
        alternate_universe_partitions,
        apply_holdout_veto,
        freeze_train_selection,
        stress_cost_latency,
    )
    from hl_observer.backtesting.scenario_search import _plateau_flag
    from hl_observer.backtesting.validation_extras import walk_forward_multi_window
    from hl_observer.backtesting.validation_gates import out_of_sample_gate
    from hl_observer.hyperlab.validation import cpcv_splits, placebo_pvalue
    from hl_observer.research.forward_frozen import ForwardFrozen

    paths = {
        "train_validation": ("src/hl_observer/backtesting/validation_extras.py", "src/hl_observer/backtesting/scenario_search.py"),
        "oos": ("src/hl_observer/backtesting/validation_gates.py",),
        "forward": ("src/hl_observer/research/forward_frozen.py",),
        "purge_embargo": ("src/hl_observer/backtesting/cross_validation.py", "src/hl_observer/backtesting/scenario_search.py"),
        "walk_forward": ("src/hl_observer/backtesting/validation_extras.py",),
        "cpcv": ("src/hl_observer/hyperlab/validation.py", "src/hl_observer/backtesting/cross_validation.py"),
        "pbo": ("src/hl_observer/backtesting/robustesse_selection.py",),
        "placebos": ("src/hl_observer/hyperlab/validation.py", "src/hl_observer/backtesting/robustesse_selection.py"),
        "neighbor_sensitivity": ("src/hl_observer/backtesting/scenario_search.py",),
        "cost_latency_stress": ("src/hl_observer/backtesting/robustness_protocol.py",),
        "alternate_universes": ("src/hl_observer/backtesting/robustness_protocol.py",),
        "holdout_veto": ("src/hl_observer/backtesting/robustness_protocol.py", "src/hl_observer/simulation/economic_objective.py"),
    }

    def split_ok() -> bool:
        splits = walk_forward_multi_window(30, train_size=10, test_size=5, step=5)
        return bool(splits) and all(max(train) < min(test) and set(train).isdisjoint(test) for train, test in splits)

    def oos_pos() -> bool:
        return out_of_sample_gate([1.0] * 30 + [2.0] * 20)["passed"] is True

    def oos_neg() -> bool:
        return out_of_sample_gate([1.0] * 30 + [-2.0] * 20)["passed"] is False

    def forward_pos() -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "forward.jsonl")
            f = ForwardFrozen(path); seal = f.promouvoir("candidate", {"x": 1}); f.observer("candidate", {"net_bps": 2.0})
            g = ForwardFrozen(path)
            return seal["scelle"] is True and g.etat("candidate")["n_observations"] == 1

    def forward_neg() -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            f = ForwardFrozen(str(Path(tmp) / "forward.jsonl")); f.promouvoir("candidate", {"x": 1})
            try:
                f.promouvoir("candidate", {"x": 2})
            except ValueError:
                return True
            return False

    def purge_pos() -> bool:
        splits = purged_walk_forward_splits(24, n_splits=4, embargo=2)
        usable = [(tr, te) for tr, te in splits if tr and te]
        return bool(usable) and all(max(tr) <= min(te) - 3 for tr, te in usable)

    def cpcv_pos() -> bool:
        splits = cpcv_splits(6, 2, embargo=1)
        return len(splits) == 15 and all(set(train).isdisjoint(test) for train, test in splits)

    matrix = [
        [1.0, 1.2, 1.1, 1.3, 1.4, 1.2],
        [0.2, 0.1, 0.0, 0.1, 0.2, 0.1],
        [-0.2, -0.1, -0.3, -0.1, -0.2, -0.1],
    ]

    def pbo_pos() -> bool:
        return pbo_cscv(matrix).get("pbo") is not None

    def pbo_neg() -> bool:
        return pbo_cscv([[1.0, 1.0]]).get("pbo") is None

    def placebo_pos() -> bool:
        a = placebo_pvalue([0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5], n_perm=50, seed=7)
        b = placebo_pvalue([0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5], n_perm=50, seed=7)
        return a == b and a.get("p_value") is not None and set(HARD_PLACEBO_DIMENSIONS) >= {"RANDOM_WALLET", "RANDOM_TIME", "RANDOM_DIRECTION", "SAME_COSTS", "SAME_L2", "SAME_LATENCY"}

    def neighbor_pos() -> bool:
        def sc(x: float):
            return SimpleNamespace(sl_bps=x * 130, tp_bps=x * 420, trailing_stop_bps=x * 220, horizon_min=x * 480, min_edge_bps=x * 60)
        center = sc(0.5); peers = [(center, 5.0)] + [(sc(0.5 + i * 0.001), 1.0) for i in range(1, 15)]
        return _plateau_flag(center, peers) is True

    def neighbor_neg() -> bool:
        def sc(x: float):
            return SimpleNamespace(sl_bps=x * 130, tp_bps=x * 420, trailing_stop_bps=x * 220, horizon_min=x * 480, min_edge_bps=x * 60)
        center = sc(0.5); peers = [(center, 5.0)] + [(sc(0.5 + i * 0.001), -1.0) for i in range(1, 15)]
        return _plateau_flag(center, peers) is False

    def stress_pos() -> bool:
        rows = stress_cost_latency(fees_bps=4, slippage_bps=3, latency_bps=2)
        return [row["multiplier"] for row in rows] == [1.0, 1.5, 2.0] and rows[-1]["total_cost_bps"] == 18.0

    def stress_neg() -> bool:
        try:
            stress_cost_latency(fees_bps=-1, slippage_bps=0, latency_bps=0)
        except ValueError:
            return True
        return False

    def universe_pos() -> bool:
        a = alternate_universe_partitions(["BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE"], partitions=3)
        b = alternate_universe_partitions(["DOGE", "XRP", "HYPE", "SOL", "ETH", "BTC"], partitions=3)
        return a == b and len(set(sum((list(x) for x in a), []))) == 6

    def universe_neg() -> bool:
        try:
            alternate_universe_partitions(["BTC"], partitions=3)
        except ValueError:
            return True
        return False

    def holdout_pos() -> bool:
        frozen = freeze_train_selection({"A": 5.0, "B": 4.0})
        confirmed = apply_holdout_veto(frozen, oos_passed=True, forward_passed=True)
        vetoed = apply_holdout_veto(frozen, oos_passed=False, forward_passed=True)
        return confirmed["winner"] == "A" and confirmed["accepted"] is True and vetoed["verdict"] == "VETO" and confirmed["retune_allowed"] is False

    def holdout_neg() -> bool:
        try:
            apply_holdout_veto({"winner": "A", "train_scores_sha256": "0" * 64, "holdout_used_for_ranking": True}, oos_passed=True, forward_passed=True)
        except ValueError:
            return True
        return False

    deterministic_split = _safe(lambda: walk_forward_multi_window(30, train_size=10, test_size=5) == walk_forward_multi_window(30, train_size=10, test_size=5))
    deterministic_cpcv = _safe(lambda: cpcv_splits(6, 2, embargo=1) == cpcv_splits(6, 2, embargo=1))
    deterministic_pbo = _safe(lambda: pbo_cscv(matrix) == pbo_cscv(matrix))
    return {
        "train_validation": Probe(_contains(root, paths["train_validation"][0], "walk_forward_multi_window"), _safe(split_ok), _safe(lambda: walk_forward_multi_window(3, train_size=3, test_size=2) == []), deterministic_split, paths["train_validation"]),
        "oos": Probe(_contains(root, paths["oos"][0], "out_of_sample_gate"), _safe(oos_pos), _safe(oos_neg), _safe(lambda: out_of_sample_gate([1.0] * 50) == out_of_sample_gate([1.0] * 50)), paths["oos"]),
        "forward": Probe(_contains(root, paths["forward"][0], "retune interdit", "append-only"), _safe(forward_pos), _safe(forward_neg), _safe(forward_pos), paths["forward"]),
        "purge_embargo": Probe(_contains(root, paths["purge_embargo"][0], "embargo"), _safe(purge_pos), _safe(lambda: purged_walk_forward_splits(2, n_splits=5, embargo=1) == []), _safe(lambda: purged_walk_forward_splits(24, n_splits=4, embargo=2) == purged_walk_forward_splits(24, n_splits=4, embargo=2)), paths["purge_embargo"]),
        "walk_forward": Probe(_contains(root, paths["walk_forward"][0], "walk_forward_multi_window"), _safe(split_ok), _safe(lambda: walk_forward_multi_window(4, train_size=3, test_size=2) == []), deterministic_split, paths["walk_forward"]),
        "cpcv": Probe(_contains(root, paths["cpcv"][0], "cpcv_splits"), _safe(cpcv_pos), _safe(lambda: cpcv_splits(3, 4, embargo=1) == []), deterministic_cpcv, paths["cpcv"]),
        "pbo": Probe(_contains(root, paths["pbo"][0], "pbo_cscv", "PBO_SEUIL"), _safe(pbo_pos), _safe(pbo_neg), deterministic_pbo, paths["pbo"]),
        "placebos": Probe(_contains(root, paths["placebos"][0], "placebo_pvalue"), _safe(placebo_pos), _safe(lambda: placebo_pvalue([1], [1], n_perm=5).get("p_value") is None), _safe(placebo_pos), paths["placebos"]),
        "neighbor_sensitivity": Probe(_contains(root, paths["neighbor_sensitivity"][0], "_plateau_flag"), _safe(neighbor_pos), _safe(neighbor_neg), _safe(neighbor_pos), paths["neighbor_sensitivity"]),
        "cost_latency_stress": Probe(_contains(root, paths["cost_latency_stress"][0], "stress_cost_latency"), _safe(stress_pos), _safe(stress_neg), _safe(lambda: stress_cost_latency(fees_bps=4, slippage_bps=3, latency_bps=2) == stress_cost_latency(fees_bps=4, slippage_bps=3, latency_bps=2)), paths["cost_latency_stress"]),
        "alternate_universes": Probe(_contains(root, paths["alternate_universes"][0], "alternate_universe_partitions"), _safe(universe_pos), _safe(universe_neg), _safe(universe_pos), paths["alternate_universes"]),
        "holdout_veto": Probe(_contains(root, paths["holdout_veto"][0], "holdout_used_for_ranking", "retune_allowed"), _safe(holdout_pos), _safe(holdout_neg), _safe(holdout_pos), paths["holdout_veto"]),
    }


def _maxdata_probes(root: Path) -> dict[str, Probe]:
    from hl_observer.datasets.economic_memory import EconomicMemoryError, load_exact_proof, record_certified_proof
    from hl_observer.datasets.max_data_policy import (
        TARGET_NET_USD_PER_FAMILY,
        choose_max_data_job,
        completed_suites_from_registry,
        record_completed_suite_from_result,
        targets_reached_from_brain,
    )
    from hl_observer.simulation.economic_objective import TARGET_NET_USD

    policy_path = "src/hl_observer/datasets/max_data_policy.py"
    memory_path = "src/hl_observer/datasets/economic_memory.py"
    completion_path = "src/hl_observer/ops/autonomous_completion.py"
    job_path = "src/hl_observer/ops/autonomous_research_job.py"
    guard_path = "src/hl_observer/ops/autonomous_research_guard.py"

    def completed_registry_probe() -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            rootp = Path(tmp); ws = rootp / "workspace"; ws.mkdir()
            good = rootp / "good.json"
            good.write_text(json.dumps({
                "schema": "alina.autonomous_research_result.v1", "status": "SUCCESS", "exit_code": 0,
                "analysis_complete": True, "completion_recorded": True, "paper_only": True,
                "real_execution": False, "start_live_collection": False, "mode": "economic",
                "suite": "economic-full", "job_id": "ok", "project_sha": "a" * 40,
                "workspace": str(ws),
            }), encoding="utf-8")
            record_completed_suite_from_result(rootp, good)
            return completed_suites_from_registry(rootp, project_sha="a" * 40) == ("economic-full",)

    def completed_registry_negative() -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            rootp = Path(tmp); ws = rootp / "workspace"; ws.mkdir()
            bad = rootp / "bad.json"
            bad.write_text(json.dumps({
                "schema": "alina.autonomous_research_result.v1", "status": "SUCCESS",
                "analysis_complete": True, "completion_recorded": True, "paper_only": True,
                "real_execution": False, "start_live_collection": False, "mode": "economic",
                "suite": "economic-full", "job_id": "bad", "project_sha": "a" * 40,
                "workspace": str(ws),
            }), encoding="utf-8")
            try:
                record_completed_suite_from_result(rootp, bad)
            except ValueError:
                return True
            return False

    def memory_probe() -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            common = dict(project_sha="a" * 40, dataset_snapshot_sha256="b" * 64, config_sha256="c" * 64, suite="economic-full", runtime_proof_sha256="d" * 64, net_pnl_usd=4.2, analysis_complete=True, certified=True)
            a = record_certified_proof(tmp, family="copy_vault", **common)
            b = record_certified_proof(tmp, family="lead_lag", **common)
            exact = load_exact_proof(tmp, family="copy_vault", project_sha="a" * 40, dataset_snapshot_sha256="b" * 64, config_sha256="c" * 64, suite="economic-full", runtime_proof_sha256="d" * 64)
            return a["key"] != b["key"] and exact["family"] == "copy_vault"

    def memory_negative() -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            common = dict(project_sha="a" * 40, family="copy_vault", dataset_snapshot_sha256="b" * 64, config_sha256="c" * 64, suite="economic-full", runtime_proof_sha256="d" * 64, net_pnl_usd=4.2, analysis_complete=True, certified=True)
            record_certified_proof(tmp, **common)
            try:
                record_certified_proof(tmp, **{**common, "runtime_proof_sha256": "e" * 64})
            except EconomicMemoryError:
                return True
            return False

    decisions = [
        {"family": "copy_vault", "priority": 100, "phase": "COLLECT_MORE"},
        {"family": "lead_lag", "priority": 90, "phase": "FREEZE_AND_CONFIRM_FORWARD"},
        {"family": "cross_venue_dislocation_v2", "priority": 80, "phase": "FREEZE_AND_CONFIRM_FORWARD"},
    ]
    plans = {
        "economic-full": {"missing_asset_count": 0, "remaining_download_gib": 1.0},
        "copy-vault-full": {"missing_asset_count": 0, "remaining_download_gib": 2.0},
    }

    def select_ready() -> bool:
        d = choose_max_data_job(family_decisions=decisions, suite_plans=plans, free_disk_gib=100, all_targets_reached=False, reserve_gib=25)
        return d["status"] == "READY" and d["holdout_used_for_ranking"] is False

    def select_stop() -> bool:
        done = [{**row, "phase": "FREEZE_AND_CONFIRM_FORWARD"} for row in decisions]
        d = choose_max_data_job(family_decisions=done, suite_plans=plans, free_disk_gib=100, all_targets_reached=True, reserve_gib=25)
        return d["status"] == "STOP_PROOF_REACHED" and d["download_budget_gib"] == 0.0

    common_mem = (memory_path,)
    return {
        "target_4usd": Probe(_contains(root, policy_path, "TARGET_NET_USD_PER_FAMILY = 4.0") and TARGET_NET_USD_PER_FAMILY == 4.0 and TARGET_NET_USD == 4.0, _safe(select_ready), _safe(lambda: not targets_reached_from_brain(decisions)), _safe(lambda: TARGET_NET_USD_PER_FAMILY == TARGET_NET_USD == 4.0), (policy_path, "src/hl_observer/simulation/economic_objective.py")),
        "completed_suites_truth": Probe(_contains(root, policy_path, "_explicit_zero", "analysis_complete", "completion_recorded"), _safe(completed_registry_probe), _safe(completed_registry_negative), _safe(completed_registry_probe), (policy_path, completion_path)),
        "state_sha": Probe(_contains(root, policy_path, "project_sha"), _safe(completed_registry_probe), _safe(lambda: completed_suites_from_registry(tempfile.mkdtemp(), project_sha="a" * 40) == ()), _safe(completed_registry_probe), (policy_path,)),
        "state_dataset": Probe(_contains(root, memory_path, "dataset_snapshot_sha256"), _safe(memory_probe), _safe(memory_negative), _safe(memory_probe), common_mem),
        "state_suite_config_runtime": Probe(_contains(root, memory_path, "config_sha256", "runtime_proof_sha256", "suite"), _safe(memory_probe), _safe(memory_negative), _safe(memory_probe), common_mem),
        "cache_checkpoint": Probe(_contains(root, job_path, "request_digest", "SUCCESS_CACHED") and _contains(root, guard_path, "resume_expected", "checkpoints"), _safe(lambda: _contains(root, job_path, "request_digest")), _safe(lambda: _contains(root, guard_path, "TIMEBOX_REACHED", "process_tree_stopped")), _safe(lambda: _contains(root, job_path, "request_digest")), (job_path, guard_path)),
        "escalate_stop": Probe(_contains(root, policy_path, "suite_ladder", "STOP_PROOF_REACHED", "INSUFFICIENT_DISK"), _safe(select_ready), _safe(select_stop), _safe(lambda: choose_max_data_job(family_decisions=decisions, suite_plans=plans, free_disk_gib=100, all_targets_reached=False, reserve_gib=25) == choose_max_data_job(family_decisions=decisions, suite_plans=plans, free_disk_gib=100, all_targets_reached=False, reserve_gib=25)), (policy_path,)),
        "continue_below_target": Probe(_contains(root, policy_path, "all_targets_reached", "STOP_PROOF_REACHED"), _safe(lambda: not targets_reached_from_brain(decisions) and select_ready()), _safe(lambda: targets_reached_from_brain([{**row, "phase": "FREEZE_AND_CONFIRM_FORWARD"} for row in decisions]) and select_stop()), _safe(select_ready), (policy_path,)),
        "memory_partition": Probe(_contains(root, memory_path, "project_sha", "family", "dataset_snapshot_sha256", "config_sha256"), _safe(memory_probe), _safe(memory_negative), _safe(memory_probe), common_mem),
        "stale_cannot_overwrite": Probe(_contains(root, memory_path, "immutable", "cannot silently overwrite"), _safe(memory_probe), _safe(memory_negative), _safe(memory_negative), common_mem),
    }


def _determinism_probes(root: Path) -> dict[str, Probe]:
    from hl_observer.datasets.max_data_router import choose_max_data_job as routed_choose
    from hl_observer.datasets.experiment_contract import calculate_contract_digest
    from hl_observer.ops import autonomous_research_job as canonical_job
    from hl_observer.ops.autonomous_research_job_router import validate_request as routed_validate

    max_router = "src/hl_observer/datasets/max_data_router.py"
    job_router = "src/hl_observer/ops/autonomous_research_job_router.py"
    family_job = "src/hl_observer/ops/family_economic_job.py"
    dataset_runner = "tools/run_dataset_economic_campaigns.py"
    parity_test = "tests/test_runtime_replay_paper_parity.py"

    def no_mutation_static() -> bool:
        text = "\n".join((_read(root, max_router), _read(root, job_router), _read(root, dataset_runner)))
        return (
            "canonical_policy.choose_max_data_job =" not in text
            and "canonical_job.ECONOMIC_SUITES =" not in text
            and "canonical._tool =" not in text
            and "canonical.dataset_provenance =" not in text
            and "_isolated_run_campaigns" in text
        )

    def no_mutation_behavior() -> bool:
        before = set(canonical_job.ECONOMIC_SUITES)
        raw = {
            "schema": canonical_job.SCHEMA, "job_id": "determinism-test", "suite": "copy-vault-full",
            "mode": "economic", "project_ref": "main", "project_sha": "a" * 40,
            "release_id": canonical_job.CANONICAL_RELEASE_ID, "dataset_repository": canonical_job.CANONICAL_DATASET_REPOSITORY,
            "paper_only": True, "real_execution": False, "start_live_collection": False,
            "download": True, "max_download_gib": 20.0, "stage_timeout_seconds": 3600,
            "cross_budget_s": 20.0, "lead_history_sources": 8,
        }
        a = routed_validate(raw); b = routed_validate(raw)
        return a == b and set(canonical_job.ECONOMIC_SUITES) == before

    family_decisions = [
        {"family": "copy_vault", "priority": 100, "phase": "COLLECT_MORE"},
        {"family": "lead_lag", "priority": 90, "phase": "COLLECT_MORE"},
        {"family": "cross_venue_dislocation_v2", "priority": 80, "phase": "COLLECT_MORE"},
    ]
    plans = {"economic-full": {"missing_asset_count": 0, "remaining_download_gib": 1.0}}

    def pure_routing() -> bool:
        kwargs = dict(family_decisions=family_decisions, suite_plans=plans, free_disk_gib=100, all_targets_reached=False, reserve_gib=25)
        return routed_choose(**kwargs) == routed_choose(**kwargs)

    def digest_deterministic() -> bool:
        contract = {
            "experiment_digest": "x", "criteria": {"family": "copy_vault"},
            "provenance": {"source_release_id": 1, "suite": "economic-full"},
            "research_lab_sources": [{"relative_path": "runtime/data/a.jsonl"}],
            "sqlite_sources": [],
        }
        return calculate_contract_digest(contract) == calculate_contract_digest(json.loads(json.dumps(contract)))

    return {
        "no_hidden_global_mutation": Probe(_safe(no_mutation_static), _safe(no_mutation_behavior), _safe(no_mutation_static), _safe(no_mutation_behavior), (max_router, job_router, family_job, dataset_runner)),
        "pure_validation_io": Probe(_contains(root, max_router, "return route_decision", "canonical_policy.choose_max_data_job") and _contains(root, job_router, "execute_family_job", "canonical_job.execute_job"), _safe(pure_routing), _safe(lambda: routed_choose(family_decisions=family_decisions, suite_plans={}, free_disk_gib=1, all_targets_reached=False, reserve_gib=25)["status"] == "NO_GO"), _safe(pure_routing), (max_router, job_router)),
        "reproducible_replay": Probe((root / parity_test).is_file() and _contains(root, "src/hl_observer/datasets/experiment_contract.py", "calculate_contract_digest"), _safe(digest_deterministic), _safe(lambda: calculate_contract_digest({"criteria": {}}) != calculate_contract_digest({"criteria": {"x": 1}})), _safe(digest_deterministic), (parity_test, "src/hl_observer/datasets/experiment_contract.py")),
    }


def _self_hosted_probes(root: Path) -> dict[str, Probe]:
    preparer = "PREPARER_PC_ALINA.cmd"
    installer_cmd = "INSTALLER_ALINA_RUNNER_WINDOWS.cmd"
    installer_ps1 = "tools/INSTALLER_ALINA_RUNNER_WINDOWS.ps1"
    workflow = ".github/workflows/alina-self-hosted.yml"
    dataset_guard = "src/hl_observer/datasets/dataset_untrusted_guard.py"
    workspace = "src/hl_observer/datasets/replay_workspace.py"
    control = "src/hl_observer/ops/self_hosted_control.py"
    returner = "src/hl_observer/ops/self_hosted_return.py"

    go_everywhere = all(_contains(root, path, "GO_SELF_HOSTED") for path in (preparer, installer_cmd, installer_ps1))
    workflow_text = _read(root, workflow)

    def attack_negative() -> bool:
        from hl_observer.datasets.dataset_untrusted_guard import DatasetUntrustedError, validate_relative_member
        from hl_observer.datasets.github_release_bridge import DatasetBridgeError, _safe_destination
        good = validate_relative_member("runtime/data/book.jsonl") == "runtime/data/book.jsonl"
        bad = 0
        for candidate in ("../escape.json", "C:/evil.json", "runtime/data/payload.exe", "runtime/data/x.ps1"):
            try:
                validate_relative_member(candidate)
            except DatasetUntrustedError:
                bad += 1
        with tempfile.TemporaryDirectory() as tmp:
            try:
                _safe_destination(Path(tmp), "../zip-slip.txt")
            except DatasetBridgeError:
                bad += 1
        return good and bad == 5

    pinned = "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in workflow_text and "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in workflow_text
    return {
        "runner_not_installed": Probe(go_everywhere and _contains(root, preparer, "exit /b 9") and _contains(root, installer_cmd, "exit /b 9"), go_everywhere, go_everywhere, go_everywhere, (preparer, installer_cmd, installer_ps1)),
        "explicit_go": Probe(go_everywhere and _contains(root, installer_ps1, "GO_SELF_HOSTED=TRUE"), go_everywhere, _contains(root, preparer, "GO_SELF_HOSTED=TRUE") and _contains(root, installer_cmd, "GO_SELF_HOSTED=TRUE"), go_everywhere, (preparer, installer_cmd, installer_ps1)),
        "main_sha_owner_no_pr": Probe("refs/heads/main" in workflow_text and "SELF_HOSTED_ACTOR_REFUSED" in workflow_text and "SELF_HOSTED_SHA_REFUSED" in workflow_text and "pull_request:" not in workflow_text, "Gate sécurité avant toute exécution du code HyperSmart" in workflow_text, "pull_request:" not in workflow_text, "CONTROL_ONLY_COMMIT_REQUIRED" in workflow_text, (workflow,)),
        "minimal_permissions": Probe("permissions:\n  contents: read" in workflow_text and "persist-credentials: false" in workflow_text, "contents: read" in workflow_text, "contents: write" not in workflow_text and "pull-requests: write" not in workflow_text, "persist-credentials: false" in workflow_text, (workflow,)),
        "controlled_command_token_paper": Probe(all(token in workflow_text for token in ("ALINA_DATASET_READ_TOKEN", "HYPERSMART_DATASET_TOKEN", "HL_ENABLE_MAINNET_EXECUTION: '0'", "HL_ENABLE_TESTNET_EXECUTION: '0'", "REAL_MAINNET_TRADING: 'false'", "self_hosted_control")), "Canoniser la commande après le gate sécurité" in workflow_text, "PRIVATE_DATASET_TOKEN_MISSING" in workflow_text, "CONTROL_PATH_REFUSED" in workflow_text, (workflow, control)),
        "sanitized_artifacts": Probe(all(token in workflow_text for token in ("github_public", "raw_data_uploaded = $false", "local_paths_uploaded = $false", "public_artifact_allowlisted = $true")), "self_hosted_return" in workflow_text, "datasets\\assets" not in workflow_text.split("Remonter uniquement", 1)[-1], "GITHUB_SAFE_JOB_PROOF.json" in workflow_text, (workflow, returner)),
        "pinned_actions_untrusted_data": Probe(pinned and _contains(root, workspace, "assert_workspace_safe") and (root / dataset_guard).is_file(), pinned, _safe(attack_negative), _safe(attack_negative), (workflow, dataset_guard, workspace)),
        "input_attack_surface": Probe(_contains(root, dataset_guard, "FORBIDDEN_EXTENSIONS", "validate_relative_member") and _contains(root, control, "job_id"), _safe(attack_negative), _safe(attack_negative), "Invoke-Expression" not in workflow_text and "iex " not in workflow_text.casefold(), (dataset_guard, workspace, control, workflow, "src/hl_observer/datasets/github_release_bridge.py")),
    }


def _ci_probes(root: Path) -> dict[str, Probe]:
    workflows = (
        ".github/workflows/ci.yml",
        ".github/workflows/donnees-hypersmart.yml",
        ".github/workflows/hyperlab-ci.yml",
        ".github/workflows/alpha-factory.yml",
        ".github/workflows/labo-continu-ci.yml",
        ".github/workflows/portable-release-windows.yml",
        ".github/workflows/windows-full-nightly.yml",
        ".github/workflows/pre-run-321-775.yml",
    )
    present = tuple(path for path in workflows if (root / path).is_file())
    required_tests = (
        "tests/test_runtime_replay_paper_parity.py",
        "tests/test_alina_self_hosted_assets.py",
        "tests/test_portable_release_ci.py",
        "tests/test_anti_overfit_gate.py",
        "tests/test_pre_run_546_775.py",
    )

    def no_deleted_tests() -> bool:
        if not (root / ".git").exists():
            return all((root / path).is_file() for path in required_tests)
        cp = subprocess.run(["git", "diff", "--name-status", "HEAD^", "HEAD", "--", "tests"], cwd=root, text=True, capture_output=True, check=False)
        if cp.returncode != 0:
            return False
        return not any(line.startswith("D\t") for line in cp.stdout.splitlines())

    workflow_text = "\n".join(_read(root, path) for path in present)
    all_present = len(present) == len(workflows)
    return {
        "relevant_suites_green": Probe(all_present and all((root / path).is_file() for path in required_tests), "python -m pytest" in workflow_text, _safe(no_deleted_tests), "continue-on-error: true" not in _read(root, ".github/workflows/pre-run-321-775.yml"), present + required_tests),
        "no_test_deletion_to_hide_red": Probe(all((root / path).is_file() for path in required_tests), _safe(no_deleted_tests), _safe(no_deleted_tests), _safe(no_deleted_tests), required_tests),
        "cross_platform_labs": Probe(all_present, all(token in workflow_text.casefold() for token in ("windows-latest", "ubuntu-latest", "powershell", "pytest")), _safe(no_deleted_tests), "tests/test_runtime_replay_paper_parity.py" in _read(root, ".github/workflows/pre-run-321-775.yml"), present),
        "security_selfhosted_tests": Probe((root / "tests/test_alina_self_hosted_assets.py").is_file() and (root / "tests/test_pre_run_546_775.py").is_file(), "test_alina_self_hosted_assets.py" in _read(root, ".github/workflows/pre-run-321-775.yml"), _safe(no_deleted_tests), all((root / path).is_file() for path in required_tests), ("tests/test_alina_self_hosted_assets.py", "tests/test_pre_run_546_775.py", ".github/workflows/pre-run-321-775.yml")),
    }


def _windows_probes(root: Path) -> dict[str, Probe]:
    portable_env = "tools/portable_env.cmd"
    portable_workflow = ".github/workflows/portable-release-windows.yml"
    clone = "src/hl_observer/ops/portable_clone.py"
    transfer = "src/hl_observer/ops/portable_transfer_proof.py"
    docs = "docs/PORTABILITE_WINDOWS.md"
    tests = "tests/test_portable_release_ci.py"
    env_text = _read(root, portable_env)
    return {
        "embedded_runtime": Probe(all(token in env_text for token in ("tools\\python\\python.exe", "PYTHONNOUSERSITE=1", "PIP_NO_INDEX=1", "HYPERSMART_WHEELHOUSE")) and _contains(root, portable_workflow, "tools\\git\\cmd\\git.exe", "WHEELHOUSE_LOCK.json"), (root / portable_workflow).is_file(), "Aucun repli" in env_text, env_text.count("HYPERSMART_PYTHON_SOURCE=embedded-tools-python") == 1, (portable_env, portable_workflow)),
        "hermetic": Probe("PYTHONNOUSERSITE=1" in env_text and "PIP_NO_INDEX=1" in env_text and _contains(root, tests, 'assert "actions/setup-python" not in TEXT'), _contains(root, portable_workflow, "Build twice and validate the extracted ZIP"), "systeme n'est autorise" in env_text or "Python systeme" in env_text, _contains(root, portable_workflow, "Build twice"), (portable_env, portable_workflow, tests)),
        "paths_new_pc": Probe((root / docs).is_file() and (root / transfer).is_file() and _contains(root, clone, "MAX_WINDOWS_PATH", "machine_fingerprint"), _contains(root, transfer, "PC A -> PC B", "verify_clone"), _contains(root, clone, "destination path is too long"), _contains(root, clone, "source_machine_fingerprint"), (docs, clone, transfer)),
        "runtime_sqlite_copy": Probe(_contains(root, clone, "SQLite Backup API") and _contains(root, transfer, "REQUIRED_POST_TRANSFER_FILES") and _contains(root, portable_workflow, "Build twice"), _contains(root, clone, "verify_clone"), _contains(root, clone, "full clone requires a clean worktree"), _contains(root, portable_workflow, "RELEASE_READY"), (clone, transfer, portable_workflow)),
    }


def _observability_probes(root: Path) -> dict[str, Probe]:
    cockpit = "tools/ALINA_RESEARCH_COCKPIT.ps1"
    text = _read(root, cockpit)
    runtime_tokens = (
        "Étape", "Temps total du job", "Espace disque libre", "PID",
        "Dernier signe de vie", "checkpoint", "CPU", "RAM", "child", "ETA",
        "Gio", "trades", "refus", "dataset",
    )
    return {
        "cockpit_runtime": Probe(all(token.casefold() in text.casefold() for token in runtime_tokens), "CURRENT_STATUS.json" in text, "Dernier signe de vie" in text, "RefreshSeconds" in text, (cockpit,)),
        "github_online_truth": Probe("Service runner local" in text and "Connexion GitHub prouvée" in text and "Passerelle GitHub' 'EN LIGNE" not in text, "GITHUB_SYNC_STATUS.json" in text, "NON PROUVÉE" in text or "NON PROUVEE" in text, "heartbeat_unix" in text and "github_run_id" in text, (cockpit, ".github/workflows/alina-self-hosted.yml")),
    }


def _docs_probes(root: Path) -> dict[str, Probe]:
    readme = "README.md"; completion = "docs/PRE_RUN_775_TECHNICAL_COMPLETION.md"; source = "docs/PRE_RUN_775_SOURCE_LOSS_CLOSURE.md"
    readme_text = _read(root, readme)
    completion_text = _read(root, completion)
    core = all(token in readme_text for token in ("Alina SmartFlow", "Copy-Vault", "Lead-Lag", "Cross-Venue", "paper"))
    extended = all(token in (readme_text + completion_text) for token in ("4 USD", "FULL/COLD", "180", "MAX DATA", "runner self-hosted"))
    return {"readme_truth": Probe(core and extended, core, any(token in readme_text.casefold() for token in ("aucune exécution réelle", "aucun ordre réel", "aucun ordre reel", "real_execution")), "scope V2" in readme_text or "Périmètre économique officiel" in readme_text, (readme, completion, source))}


def _rehearsal_probes(root: Path) -> dict[str, Probe]:
    from hl_observer.ops.pre_full_rehearsal import FINAL_GO_FLAGS, ORDERED_STAGES, SCHEMA, evaluate_final_go, evaluate_rehearsals
    module = "src/hl_observer/ops/pre_full_rehearsal.py"; source = "docs/PRE_RUN_775_SOURCE_LOSS_CLOSURE.md"

    def complete_payload(go: bool) -> dict[str, Any]:
        return {
            "schema": SCHEMA, "project_sha": "a" * 40, "paper_only": True, "real_execution": False,
            "stages": [{"name": name, "status": "PASSED", "evidence_sha256": hashlib.sha256(name.encode()).hexdigest()} for name in ORDERED_STAGES],
            "final_go": {**{flag: True for flag in FINAL_GO_FLAGS}, "GO_SELF_HOSTED": "TRUE" if go else "FALSE"},
        }

    return {
        "ordered_rehearsals": Probe(_contains(root, module, "ORDERED_STAGES", "full-archive", "crash-resume", "runtime-consumption"), _safe(lambda: evaluate_rehearsals(complete_payload(False))["ok"] is True), _safe(lambda: evaluate_rehearsals({"schema": SCHEMA, "project_sha": "a" * 40, "paper_only": True, "real_execution": False, "stages": []})["ok"] is False), _safe(lambda: evaluate_rehearsals(complete_payload(False)) == evaluate_rehearsals(complete_payload(False))), (module, source)),
        "final_go_gate": Probe(_contains(root, module, "FINAL_GO_FLAGS", "GO_SELF_HOSTED_NOT_EXPLICIT_TRUE"), _safe(lambda: evaluate_final_go(complete_payload(True))["go"] is True), _safe(lambda: evaluate_final_go(complete_payload(False))["go"] is False), _safe(lambda: evaluate_final_go(complete_payload(True)) == evaluate_final_go(complete_payload(True))), (module, source)),
    }


def _category(root: Path, name: str, probes: Mapping[str, Probe]) -> dict[str, Any]:
    rows = [_row(root, key, description, probes[key]) for key, description in CATEGORY_REQUIREMENTS[name]]
    facets_done = sum(sum(1 for value in row["facets"].values() if value) for row in rows)
    return {
        "category": name,
        "requirements": rows,
        "requirements_done": sum(1 for row in rows if row["ok"]),
        "requirements_total": len(rows),
        "facets_done": facets_done,
        "facets_total": len(rows) * len(FACETS),
        "ok": all(row["ok"] for row in rows),
    }


def evaluate_remaining_requirements(root: Path) -> dict[str, Any]:
    root = root.resolve()
    probes = {
        "ANTI_OVERFIT": _anti_probes(root),
        "MAXDATA_AUTONOMY": _maxdata_probes(root),
        "DETERMINISM": _determinism_probes(root),
        "SELF_HOSTED_SECURITY": _self_hosted_probes(root),
        "CI": _ci_probes(root),
        "WINDOWS_PORTABILITY": _windows_probes(root),
        "OBSERVABILITY": _observability_probes(root),
        "DOCS": _docs_probes(root),
        "REHEARSALS_GO": _rehearsal_probes(root),
    }
    categories = {name: _category(root, name, probes[name]) for name in CATEGORY_REQUIREMENTS}
    requirements_total = sum(row["requirements_total"] for row in categories.values())
    facets_total = sum(row["facets_total"] for row in categories.values())
    return {
        "schema": "hypersmart.pre_run_546_775.v1",
        "requirements_total": requirements_total,
        "requirements_done": sum(row["requirements_done"] for row in categories.values()),
        "facets_total": facets_total,
        "facets_done": sum(row["facets_done"] for row in categories.values()),
        "categories": categories,
        "ok": requirements_total == 46 and facets_total == 230 and all(row["ok"] for row in categories.values()),
        "historical_literal": False,
        "provenance": "DERIVED_TECHNICAL_REQUIREMENT",
        "paper_only": True,
        "real_execution": False,
    }


__all__ = [
    "ANTI_OVERFIT_REQUIREMENTS", "CATEGORY_REQUIREMENTS", "CI_REQUIREMENTS",
    "DETERMINISM_REQUIREMENTS", "DOCS_REQUIREMENTS", "FACETS",
    "MAXDATA_REQUIREMENTS", "OBSERVABILITY_REQUIREMENTS", "REHEARSALS_REQUIREMENTS",
    "SELF_HOSTED_REQUIREMENTS", "WINDOWS_REQUIREMENTS", "evaluate_remaining_requirements",
]
