"""Registre de couverture exécutable des optimisations pré-run 001 -> 100.

Le dépôt a accumulé plusieurs générations d'identifiants. Pour ce lot, les preuves
historiques disponibles sur ``main`` couvrent IDEA-001..091 puis HS-092..100.
Ce module ne transforme JAMAIS « fichier présent » en « DONE » : il distingue
``CODE_PRESENT`` et ``EVIDENCE_MISSING``. Le statut ``VERIFIED`` appartient à la CI
qui exécute les tests associés.

Aucun réseau, aucune mutation de données, aucune exécution de trading.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = "hypersmart.pre_run_001_100.coverage.v1"


@dataclass(frozen=True, slots=True)
class OptimizationEvidence:
    optimization_id: int
    title: str
    category: str
    source_paths: tuple[str, ...]
    test_paths: tuple[str, ...]
    paper_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _ids(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(int(v) for v in values)


def _build_registry() -> dict[int, OptimizationEvidence]:
    registry: dict[int, OptimizationEvidence] = {}

    def add(ids: Iterable[int], title: str, category: str, sources: tuple[str, ...], tests: tuple[str, ...]) -> None:
        for optimization_id in _ids(ids):
            if optimization_id in registry:
                raise RuntimeError(f"duplicate optimization id {optimization_id}")
            registry[optimization_id] = OptimizationEvidence(
                optimization_id=optimization_id,
                title=title,
                category=category,
                source_paths=sources,
                test_paths=tests,
            )

    add(
        (1, 2, 4),
        "dataset tick, RAW vers CANONICAL et snapshot incremental",
        "data_truth",
        (
            "src/hl_observer/collection/tick_dataset.py",
            "src/hl_observer/normalization/market_events.py",
            "src/hl_observer/market_truth/pipeline.py",
        ),
        ("tests/test_tick_dataset.py", "tests/test_canonical_market_events.py"),
    )
    add(
        (3, 5, 6),
        "qualite du feed, stale/gap/outlier et score fail-closed",
        "data_quality",
        ("src/hl_observer/realtime/feed_quality.py", "src/hl_observer/market_truth/pipeline.py"),
        ("tests/test_feed_quality_gate.py", "tests/test_feed_quality_reader.py"),
    )
    add(
        (7, 8),
        "demarrage borne, instance unique et reprise/reconnexion",
        "runtime_resilience",
        (
            "src/hl_observer/runtime/persistent_poll_runner.py",
            "src/hl_observer/collection/verrou_instance.py",
        ),
        ("tests/test_persistent_poll_runner.py", "tests/test_verrou_instance.py"),
    )
    add(
        (9,),
        "deduplication durable inter-crash",
        "runtime_truth",
        ("src/hl_observer/runtime/protections.py",),
        ("tests/test_runtime_protections.py",),
    )
    add(
        (10,),
        "journal operationnel et incidents bloquants",
        "runtime_truth",
        ("src/hl_observer/runtime/protections.py",),
        ("tests/test_runtime_protections.py",),
    )
    add(
        (11,),
        "TruthReconciler canonique signal-fill-ledger",
        "market_truth",
        ("src/hl_observer/market_truth/truth_chain.py",),
        ("tests/test_market_truth_pipeline.py", "tests/test_market_truth_replay_stage.py"),
    )
    add(
        range(12, 22),
        "prix executable, VWAP, fills partiels et couts",
        "execution_realism",
        ("src/hl_observer/market_truth/executable_replay.py",),
        ("tests/test_market_truth_pipeline.py", "tests/test_market_truth_replay_stage.py"),
    )
    add(
        range(22, 27),
        "latence, edge decay, timings et break-even",
        "execution_realism",
        ("src/hl_observer/ops/market_truth_replay.py", "src/hl_observer/market_truth/executable_replay.py"),
        ("tests/test_market_truth_replay_stage.py", "tests/test_forward_causal_parity_bloc17.py"),
    )
    add(
        range(27, 36),
        "forward causal, anti-lookahead, ledger et reprise",
        "causality",
        (
            "src/hl_observer/backtesting/anti_lookahead_pipeline.py",
            "src/hl_observer/backtesting/backtest_live_parity.py",
            "src/hl_observer/market_truth/truth_chain.py",
        ),
        ("tests/test_forward_causal_parity_bloc17.py", "tests/test_paper_pipeline_e2e.py"),
    )
    add(
        (36,),
        "ledger corrompu bloque la preuve economique",
        "pnl_truth",
        ("src/hl_observer/runtime/protections.py",),
        ("tests/test_runtime_protections.py",),
    )
    add(
        range(37, 41),
        "validation economique, ROI explicites, marks causaux et drawdown",
        "pnl_truth",
        ("src/hl_observer/ops/economic_revalidation.py",),
        ("tests/test_economic_revalidation_bloc18.py",),
    )
    add(
        range(41, 52),
        "walk-forward, PBO, DSR, bootstrap, placebos et ablations",
        "anti_overfit",
        ("src/hl_observer/backtesting/anti_overfit_gate.py",),
        ("tests/test_anti_overfit_gate.py", "tests/test_robustesse_selection.py"),
    )
    add(
        range(52, 56),
        "regimes et specialisations coin/horizon pre-enregistrees",
        "regimes",
        ("tools/regimes_marche.py",),
        ("tests/test_idees_36_a_91.py",),
    )
    add(
        range(56, 61),
        "ladder, inventaire, OFI, depletion et toxicite L2",
        "microstructure",
        ("src/hl_observer/experimental/metaorder_l2_tape.py",),
        ("tests/test_metaorder_l2_tape.py",),
    )
    add(
        range(61, 67),
        "entites, copyabilite, metaorders, lead-lag, cohortes et conflits",
        "wallet_research",
        (
            "src/hl_observer/following/entity_consensus.py",
            "src/hl_observer/experimental/metaorder_shadow.py",
        ),
        ("tests/test_entity_consensus.py", "tests/test_metaorder_shadow.py"),
    )
    add(
        range(67, 71),
        "stops, time-stop, reduce partiel et MAE/MFE",
        "risk_exits",
        ("tools/exits_risque.py",),
        ("tests/test_idees_36_a_91.py",),
    )
    add(
        (71,),
        "controle cross-source = qualite uniquement, jamais signal",
        "research_guardrails",
        ("src/hl_observer/runtime/protections.py",),
        ("tests/test_runtime_protections.py",),
    )
    add(
        range(72, 78),
        "scheduler, progression, sante, dashboard et rapport remplaces par la suite canonique",
        "orchestration",
        ("src/hl_observer/ops/historical_analysis_suite.py",),
        ("tests/test_historical_analysis_launcher.py",),
    )
    add(
        range(78, 81),
        "provenance, panne ingestion et verrou synthetique",
        "research_guardrails",
        ("src/hl_observer/runtime/protections.py",),
        ("tests/test_runtime_protections.py",),
    )
    add(
        range(81, 92),
        "garde-fous de recherche canoniques IDEA-81 a 91",
        "research_guardrails",
        ("src/hl_observer/runtime/research_guardrails.py",),
        ("tests/test_runtime_research_guardrails.py",),
    )

    add(
        (92,),
        "runner persistant invoque la CLI in-process sans taxe de spawn",
        "runtime_runner",
        ("src/hl_observer/runtime/persistent_poll_runner.py",),
        ("tests/test_persistent_poll_runner.py",),
    )
    add(
        (93,),
        "exceptions programmeur distinguees des erreurs recuperables",
        "runtime_runner",
        ("src/hl_observer/runtime/persistent_poll_runner.py",),
        ("tests/test_persistent_poll_runner.py",),
    )
    add(
        (94,),
        "lock atomique lie a une identite run_id",
        "runtime_lock",
        ("src/hl_observer/collection/verrou_instance.py",),
        ("tests/test_verrou_instance.py",),
    )
    add(
        (95,),
        "heartbeat/liberation proteges et session terminee non reprise",
        "runtime_lock",
        ("src/hl_observer/collection/verrou_instance.py",),
        ("tests/test_verrou_instance.py", "tests/test_session_identity.py"),
    )
    add(
        range(96, 100),
        "etats/capacites strategie explicites, lanes strictes et shadow fail-closed",
        "strategy_registry",
        ("src/hl_observer/strategies/paper_registry.py",),
        ("tests/test_v12_strategy_registry.py",),
    )
    add(
        (100,),
        "references ledger obligatoires et identifiants UNKNOWN non promotables",
        "ledger_identity",
        ("src/hl_observer/simulation/paper_ledger.py", "src/hl_observer/market_truth/truth_chain.py"),
        ("tests/test_paper_ledger.py", "tests/test_market_truth_pipeline.py"),
    )

    expected = set(range(1, 101))
    actual = set(registry)
    if actual != expected:
        raise RuntimeError(f"coverage registry invalid: missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
    return registry


REGISTRY = _build_registry()


def inspect_coverage(root: Path | str) -> dict[str, object]:
    base = Path(root)
    rows: list[dict[str, object]] = []
    missing_ids: list[int] = []
    for optimization_id in range(1, 101):
        evidence = REGISTRY[optimization_id]
        source_presence = {path: (base / path).is_file() for path in evidence.source_paths}
        test_presence = {path: (base / path).is_file() for path in evidence.test_paths}
        sources_ok = bool(source_presence) and all(source_presence.values())
        tests_ok = bool(test_presence) and all(test_presence.values())
        code_present = sources_ok and tests_ok
        if not code_present:
            missing_ids.append(optimization_id)
        rows.append(
            {
                **evidence.as_dict(),
                "source_presence": source_presence,
                "test_presence": test_presence,
                "status": "CODE_PRESENT" if code_present else "EVIDENCE_MISSING",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "range": "001-100",
        "n_items": 100,
        "n_code_present": 100 - len(missing_ids),
        "n_missing": len(missing_ids),
        "missing_ids": missing_ids,
        "all_code_present": not missing_ids,
        "verified": False,
        "verification_rule": "VERIFIED only after the associated CI tests execute successfully on the same HEAD",
        "items": rows,
        "real_execution": False,
    }


__all__ = ["SCHEMA_VERSION", "OptimizationEvidence", "REGISTRY", "inspect_coverage"]
