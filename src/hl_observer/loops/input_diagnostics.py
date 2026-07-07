from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from hl_observer.loops.candidate_factory import CandidateFactoryReport
from hl_observer.loops.memory import default_loop_memory_dir
from hl_observer.mainnet_readonly_observer.observer import MainnetObservation
from hl_observer.runtime.session_logs import default_logs_to_send_dir


LATEST_INPUT_DIAGNOSTICS = "latest_loop_input_diagnostics.json"


def build_loop_input_diagnostics(
    *,
    observation: MainnetObservation,
    fill_report: CandidateFactoryReport,
    delta_report: CandidateFactoryReport | None = None,
    delta_source_error: str | None = None,
    requested_wallets: list[str] | None = None,
    requested_coins: list[str] | None = None,
    recent_delta_window_seconds: int | None = None,
) -> dict[str, Any]:
    """Explain why the local decision/testnet loop did or did not receive candidates."""

    requested_wallets = requested_wallets or []
    requested_coins = requested_coins or []
    fills_seen = sum(len(fills) for fills in observation.wallet_fills.values())
    fill_candidates = len(fill_report.candidates)
    delta_candidates = len(delta_report.candidates) if delta_report else 0
    candidate_count = fill_candidates + delta_candidates
    skipped_reasons = _skipped_reason_counts(fill_report, delta_report)
    status = _diagnostic_status(
        observation=observation,
        requested_wallets=requested_wallets,
        fills_seen=fills_seen,
        fill_candidates=fill_candidates,
        delta_report=delta_report,
        delta_candidates=delta_candidates,
        delta_source_error=delta_source_error,
    )
    return {
        "status": status,
        "observed_at_ms": observation.observed_at_ms,
        "source": observation.source,
        "requested_wallets": requested_wallets,
        "requested_wallet_count": len(requested_wallets),
        "requested_coins": requested_coins,
        "requested_coin_count": len(requested_coins),
        "wallets_seen": len(observation.wallet_states),
        "fills_seen": fills_seen,
        "all_mids_count": len(observation.all_mids),
        "l2_books_count": len(observation.l2_books),
        "fill_candidate_count": fill_candidates,
        "position_delta_candidate_count": delta_candidates,
        "candidate_count": candidate_count,
        "fill_skipped_reasons": _skipped_reason_counts(fill_report, None),
        "position_delta_skipped_reasons": _skipped_reason_counts(delta_report, None) if delta_report else {},
        "skipped_reasons": skipped_reasons,
        "delta_source_error": delta_source_error,
        "recent_delta_window_seconds": recent_delta_window_seconds,
        "next_actions": _next_actions(status),
        "research_only": True,
        "execution": "forbidden_unless_explicit_testnet_guard",
    }


def write_loop_input_diagnostics(
    diagnostics: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> tuple[Path, Path]:
    root = project_root or Path.cwd()
    runtime_path = default_loop_memory_dir(root) / LATEST_INPUT_DIAGNOSTICS
    logs_path = default_logs_to_send_dir(root) / LATEST_INPUT_DIAGNOSTICS
    text = json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    logs_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(text, encoding="utf-8")
    logs_path.write_text(text, encoding="utf-8")
    return runtime_path, logs_path


def _diagnostic_status(
    *,
    observation: MainnetObservation,
    requested_wallets: list[str],
    fills_seen: int,
    fill_candidates: int,
    delta_report: CandidateFactoryReport | None,
    delta_candidates: int,
    delta_source_error: str | None,
) -> str:
    if fill_candidates + delta_candidates > 0:
        return "READY_CANDIDATES"
    if observation.errors:
        return "READONLY_SOURCE_ERRORS"
    if not observation.all_mids:
        return "NO_MARKET_CONTEXT"
    if delta_source_error:
        return "POSITION_DELTA_SOURCE_ERROR"
    if not requested_wallets and delta_report is None:
        return "NO_WALLETS_OR_DELTAS_REQUESTED"
    if requested_wallets and fills_seen == 0 and delta_report is None:
        return "NO_WALLET_FILLS"
    if delta_report is not None and len(delta_report.candidates) == 0 and len(delta_report.skipped) == 0:
        return "NO_RECENT_POSITION_DELTAS"
    return "NO_MEASURABLE_SIGNAL"


def _skipped_reason_counts(
    first: CandidateFactoryReport | None,
    second: CandidateFactoryReport | None,
) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for report in (first, second):
        if report is None:
            continue
        for item in report.skipped:
            counter[item.reason] += 1
    return dict(counter.most_common())


def _next_actions(status: str) -> list[str]:
    mapping = {
        "READY_CANDIDATES": ["Passer les candidats au DecisionEngine puis verifier evidence_chain/testnet guard."],
        "READONLY_SOURCE_ERRORS": ["Verifier source_health, connectivite Hyperliquid et bornes de pagination."],
        "NO_MARKET_CONTEXT": ["Relancer la lecture /info allMids/l2Book avant toute decision."],
        "POSITION_DELTA_SOURCE_ERROR": ["Corriger la lecture DB position_deltas; ne pas inventer de signal."],
        "NO_WALLETS_OR_DELTAS_REQUESTED": ["Fournir des wallets AUTO/import ou activer les deltas locaux recents."],
        "NO_WALLET_FILLS": ["Verifier que les wallets selectionnes ont des fills publics recents."],
        "NO_RECENT_POSITION_DELTAS": ["Attendre ou collecter des deltas frais; ne pas recycler des deltas vieux."],
        "NO_MEASURABLE_SIGNAL": ["Inspecter skipped_reasons pour savoir quelle donnee manque."],
    }
    return mapping.get(status, ["Continuer l'observation read-only et journaliser le blocage."])
