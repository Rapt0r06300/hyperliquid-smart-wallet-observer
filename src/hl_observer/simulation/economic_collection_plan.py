"""Truthful, resumable collection plan for the three economic campaigns.

The plan is deliberately diagnostic.  It never creates observations or turns
an unmeasured/negative campaign into a success.  Its purpose is to distinguish
missing future market evidence from a hypothesis that has already failed OOS.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_executable import PROTOCOL_NAME as COPY_VAULT_PROTOCOL

from .economic_campaigns import REPORT_DIR
from .economic_objective import CANONICAL_FAMILIES, canonical_family

SCHEMA_VERSION = "hypersmart.economic_collection_resume.v1"
STATE_FILENAME = "collection_resume_state.json"
REPORT_FILENAME = "HYPERSMART_ECONOMIC_COLLECTION_RESUME.md"
COPY_BOOK_REJECTION_REASONS = (
    "NO_OBSERVED_BOOK_FOR_COIN",
    "STALE_OR_MISSING_REFERENCE_BOOK",
    "STALE_OR_MISSING_ENTRY_BOOK",
    "STALE_OR_MISSING_EXIT_BOOK",
    "NON_CAUSAL_FORWARD_BOOK",
)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _freeze(campaign: Mapping[str, Any]) -> dict[str, Any] | None:
    value = campaign.get("parameter_freeze")
    if not isinstance(value, Mapping):
        return None
    return {
        "campaign_id": value.get("campaign_id"),
        "frozen_at_ms": value.get("frozen_at_ms"),
        "parameters_sha256": value.get("parameters_sha256"),
        "path": value.get("path"),
    }


def _copy_state(
    campaign: Mapping[str, Any],
    raw: Mapping[str, Any],
    collector_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    audit = _mapping(raw.get("canonical_input_audit"))
    metaorders = _mapping(raw.get("metaorder_audit"))
    books = _mapping(raw.get("book_meta"))
    causal = _mapping(raw.get("causal_protocol_audit"))
    calibration = _mapping(raw.get("calibration"))
    grid = calibration.get("grid") if isinstance(calibration.get("grid"), list) else []
    book_rejections = {
        reason: sum(
            _integer(_mapping(_mapping(row).get("diagnostics")).get(reason))
            for row in grid
            if isinstance(row, Mapping)
        )
        for reason in COPY_BOOK_REJECTION_REASONS
    }
    book_rejection_total = sum(book_rejections.values())
    train_executable_episodes_max = max(
        (
            _integer(_mapping(_mapping(row).get("summary")).get("positions_fermees"))
            for row in grid
            if isinstance(row, Mapping)
        ),
        default=0,
    )
    minimum_train_episodes = max(
        1,
        _integer(calibration.get("minimum_train_trades")) or 8,
    )
    training_selection_eligible = calibration.get("selection_eligible") is True
    parameters_frozen = bool(
        campaign.get("parameters_frozen") is True or _freeze(campaign) is not None
    )
    causal_metaorders = _integer(causal.get("causal_protocol_metaorders"))
    closed = _integer(campaign.get("closed_positions"))
    schema_ready = raw.get("schema_version") == "hypersmart.copy_vault_executable_campaign.v1"
    objective_met = campaign.get("objective_status") == "ATTEINT"
    collector = _mapping(collector_state)
    active_collectors = _mapping(collector.get("actifs"))
    protocols = _mapping(collector.get("protocols"))
    active_protocol = str(protocols.get("userfills-live") or "")
    collector_protocol_ready: bool | None = None
    if "userfills-live" in active_collectors:
        collector_protocol_ready = active_protocol == COPY_VAULT_PROTOCOL
    data_only = bool(
        schema_ready
        and not objective_met
        and not parameters_frozen
        and not training_selection_eligible
        and (
            causal_metaorders < minimum_train_episodes
            or train_executable_episodes_max < minimum_train_episodes
            or book_rejection_total > 0
        )
    )
    state = (
        "PROVEN"
        if objective_met
        else "CAUSAL_COLLECTOR_PROTOCOL_RESTART_REQUIRED"
        if collector_protocol_ready is False
        else "FUTURE_CAUSAL_BOOK_AND_VAULT_DATA_REQUIRED"
        if data_only
        else "CONTROLLED_BLOCKER_REMAINS"
    )
    return {
        "family": "copy_vault",
        "evidence_state": state,
        "collection_actionable": not objective_met,
        "software_pipeline_ready": schema_ready,
        "running_collector_protocol_ready": collector_protocol_ready,
        "future_data_required_only": data_only and collector_protocol_ready is not False,
        "objective_status": campaign.get("objective_status"),
        "objective_reasons": list(campaign.get("objective_reasons") or []),
        "freeze": _freeze(campaign),
        "progress": {
            "raw_fills": _integer(audit.get("raw_fills")),
            "canonical_alpha_entries": _integer(audit.get("alpha_entries")),
            "missing_or_stale_nav_rejected": _integer(
                audit.get("missing_or_stale_asof_nav_rejected")
            ),
            "metaorders": _integer(metaorders.get("metaorders")),
            "historical_metaorders_audit_only": _integer(metaorders.get("all_metaorders")),
            "causal_protocol_metaorders": causal_metaorders,
            "observed_book_rows": _integer(books.get("valid_rows")),
            "causal_protocol_book_rows": _integer(
                causal.get("causal_protocol_book_rows")
            ),
            "book_coins": _integer(books.get("coins")),
            "book_rejections_across_grid": book_rejections,
            "stale_or_missing_book_rejections_across_grid": book_rejection_total,
            "train_executable_episodes_max": train_executable_episodes_max,
            "minimum_train_episodes": minimum_train_episodes,
            "training_selection_eligible": training_selection_eligible,
            "parameters_frozen": parameters_frozen,
            "closed_liquidatable_episodes": closed,
            "expected_collector_protocol": COPY_VAULT_PROTOCOL,
            "active_collector_protocol": active_protocol or None,
        },
        "required_collectors": [
            "vault-collector",
            "scorer-vaults",
            "userfills-live",
            "carnet-collector",
            "backfill-fills",
            "backfill-candles-vaults",
        ],
        "required_artifacts": [
            "runtime/data/vault_fills.jsonl",
            "runtime/data/vault_fills_live.jsonl",
            "runtime/data/vault_episodes.jsonl",
            "runtime/data/vault_snapshots.jsonl",
            "runtime/data/carnet_venues.jsonl",
            "runtime/data/copy_vault_l2_tape.jsonl",
        ],
        "exact_missing_evidence": (
            [
                "restart userfills-live so its heartbeat proves the v6 causal-checkpoint protocol",
                "capture REFERENCE, ENTRY and EXIT books from live WS or causal /info l2Book checkpoints",
            ]
            if collector_protocol_ready is False
            else []
        )
        + [
            "at least 8 causal train metaorders with observed executable BBO",
            "entry and exit books no more than 30 seconds from each copied event",
            "purged positive OOS, positive post-freeze forward, placebo beaten",
        ],
        "rerun_condition": (
            "new causal vault metaorders and matching observed books exist after the latest "
            "input boundary; rerun then freeze only if train selection is eligible"
        ),
    }


def _lead_state(
    campaign: Mapping[str, Any],
    raw: Mapping[str, Any],
    collector_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    del collector_state
    executable = _mapping(raw.get("executable_campaign"))
    diagnostics = _mapping(executable.get("diagnostics"))
    temporal = _mapping(executable.get("temporal_evidence"))
    oos = _mapping(temporal.get("oos"))
    forward = _mapping(temporal.get("forward"))
    placebos = _mapping(temporal.get("placebos"))
    candidate = _integer(diagnostics.get("candidate_observations"))
    liquidatable = _integer(diagnostics.get("liquidatable_observations"))
    missing_sizes = _integer(diagnostics.get("missing_top_sizes"))
    closed = _integer(campaign.get("closed_positions"))
    schema_ready = (
        executable.get("schema_version") == "hypersmart.lead_lag_executable_campaign.v1"
        and executable.get("execution_model") == "causal_marketable_top_v3"
    )
    objective_met = campaign.get("objective_status") == "ATTEINT"
    oos_net = _number(oos.get("net_pnl_usd"))
    forward_net = _number(forward.get("net_pnl_usd"))
    measured_negative = bool(
        closed > 0
        and oos_net is not None
        and oos_net <= 0.0
        and oos.get("no_lookahead") is True
        and forward_net is not None
        and forward_net <= 0.0
        and forward.get("post_freeze") is True
    )
    data_only = bool(
        schema_ready
        and not objective_met
        and not measured_negative
        and closed == 0
        and candidate > 0
        and missing_sizes >= candidate
    )
    state = (
        "PROVEN"
        if objective_met
        else "HYPOTHESIS_KILLED_OOS_FORWARD"
        if measured_negative
        else "FUTURE_SIZED_BBO_REQUIRED"
        if data_only
        else "CONTROLLED_BLOCKER_REMAINS"
    )
    return {
        "family": "lead_lag",
        "evidence_state": state,
        "collection_actionable": bool(not objective_met and not measured_negative),
        "software_pipeline_ready": schema_ready,
        "future_data_required_only": data_only,
        "objective_status": campaign.get("objective_status"),
        "objective_reasons": list(campaign.get("objective_reasons") or []),
        "freeze": _freeze(campaign),
        "progress": {
            "candidate_observations": candidate,
            "liquidatable_observations": liquidatable,
            "missing_top_sizes": missing_sizes,
            "purged_or_unassigned": _integer(diagnostics.get("purged_or_unassigned")),
            "closed_liquidatable_episodes": closed,
            "net_pnl_usd": _number(campaign.get("net_pnl_usd")),
            "profit_factor": _number(campaign.get("profit_factor")),
            "oos_sample_count": _integer(oos.get("sample_count")),
            "oos_net_pnl_usd": oos_net,
            "forward_sample_count": _integer(forward.get("sample_count")),
            "forward_net_pnl_usd": forward_net,
            "placebo_beaten": placebos.get("beaten") is True,
        },
        "required_collectors": ["bbo-collector", "allmids-collector"],
        "required_artifacts": [
            "runtime/data/bbo_tape.jsonl",
            "runtime/data/bbo_shards/*.jsonl.gz",
        ],
        "exact_missing_evidence": (
            [
                "the frozen lead-lag rule is negative in both purged OOS and post-freeze forward",
                "a materially new causal mechanism must be declared and frozen before evaluation",
                "positive purged OOS and true post-freeze forward remain mandatory",
            ]
            if measured_negative
            else [
                "at least 30 post-code shocks with observed bid_sz and ask_sz",
                "causal pre-signal, entry and exit BBO for each certified episode",
                "purged positive OOS, positive post-freeze forward, placebo beaten",
            ]
        ),
        "economic_prior_warning": (
            "legacy observations without top sizes are diagnostic only and cannot certify edge"
        ),
        "methodology_action": (
            "KILL_CURRENT_FROZEN_HYPOTHESIS_OR_DECLARE_NEW_MECHANISM"
            if measured_negative
            else "CONTINUE_FROZEN_FORWARD_COLLECTION"
        ),
        "rerun_condition": (
            "do not promote by waiting: test only a new predeclared mechanism against the same ledger"
            if measured_negative
            else "at least 30 new sized BBO shocks exist after the physical freeze boundary"
        ),
    }


def _cross_state(
    campaign: Mapping[str, Any],
    raw: Mapping[str, Any],
    collector_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    del collector_state
    verdict = _mapping(raw.get("verdict_realiste_16bps"))
    temporal = _mapping(raw.get("temporal_evidence"))
    oos = _mapping(temporal.get("oos"))
    forward = _mapping(temporal.get("forward"))
    placebo = _mapping(temporal.get("placebos"))
    closed = _integer(verdict.get("positions_fermees"))
    schema_ready = (
        raw.get("schema_version") == "hypersmart.cross_venue_campaign.v2"
        and verdict.get("LIQUIDATABLE_NET") is True
        and verdict.get("all_positions_two_leg_closed") is True
    )
    objective_met = campaign.get("objective_status") == "ATTEINT"
    measured_negative = bool(
        closed > 0
        and oos.get("net_pnl_usd") is not None
        and float(oos.get("net_pnl_usd")) <= 0.0
    )
    state = (
        "PROVEN"
        if objective_met
        else "HYPOTHESIS_KILLED_OOS"
        if measured_negative
        else "FUTURE_POST_FREEZE_DATA_REQUIRED"
    )
    return {
        "family": "cross_venue_dislocation_v2",
        "evidence_state": state,
        # More observations of the same frozen, negative-OOS mechanism cannot
        # repair it. Collection resumes only after a materially new mechanism
        # is declared and frozen; shared collectors may still run for Copy/Lead.
        "collection_actionable": bool(not objective_met and not measured_negative),
        "software_pipeline_ready": schema_ready,
        "future_data_required_only": bool(
            schema_ready and not objective_met and not measured_negative and closed > 0
        ),
        "objective_status": campaign.get("objective_status"),
        "objective_reasons": list(campaign.get("objective_reasons") or []),
        "freeze": _freeze(campaign),
        "progress": {
            "closed_atomic_two_leg_positions": closed,
            "net_pnl_usd": verdict.get("net_total_usd"),
            "profit_factor": verdict.get("profit_factor", verdict.get("pf")),
            "oos_sample_count": _integer(oos.get("sample_count")),
            "oos_net_pnl_usd": oos.get("net_pnl_usd"),
            "forward_sample_count": _integer(forward.get("sample_count")),
            "placebo_beaten": placebo.get("beaten") is True,
        },
        "required_collectors": ["carnet-collector", "venues-collector"],
        "required_artifacts": ["runtime/data/carnet_venues.jsonl"],
        "exact_missing_evidence": (
            [
                "the frozen v2 rule is negative OOS and loses to placebo",
                "a materially new mechanism must be declared and frozen before evaluation",
                "positive purged OOS and true post-freeze forward are still mandatory",
            ]
            if measured_negative
            else ["positive post-freeze forward and placebo-beating evidence"]
        ),
        "methodology_action": (
            "KILL_CURRENT_FROZEN_HYPOTHESIS_OR_DECLARE_NEW_MECHANISM"
            if measured_negative
            else "CONTINUE_FROZEN_FORWARD_COLLECTION"
        ),
        "rerun_condition": (
            "do not promote by waiting: test only a new predeclared mechanism against the same "
            "atomic two-leg ledger"
            if measured_negative
            else "new atomic four-side books exist after the physical freeze boundary"
        ),
    }


def build_collection_plan(
    campaigns: Iterable[Mapping[str, Any]],
    raw_reports: Mapping[str, Mapping[str, Any]],
    *,
    collector_state: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Build one fail-closed, reproducible resume state."""

    by_family = {canonical_family(row.get("family")): row for row in campaigns}
    builders = {
        "copy_vault": _copy_state,
        "lead_lag": _lead_state,
        "cross_venue_dislocation_v2": _cross_state,
    }
    families = [
        builders[name](
            by_family.get(name, {}),
            _mapping(raw_reports.get(name)),
            collector_state,
        )
        for name in CANONICAL_FAMILIES
    ]
    required_collectors = sorted(
        {
            collector
            for row in families
            if row["objective_status"] != "ATTEINT"
            and row.get("collection_actionable") is True
            for collector in row["required_collectors"]
        }
    )
    goal_complete = all(row["objective_status"] == "ATTEINT" for row in families)
    unmet = [row for row in families if row["objective_status"] != "ATTEINT"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_ms": int(now_ms if now_ms is not None else time.time() * 1000),
        "paper_read_only": True,
        "real_execution": False,
        "starting_capital_usd_per_family": 1000.0,
        "target_net_usd_per_family": 4.0,
        "goal_complete": goal_complete,
        "all_software_pipelines_ready": all(
            row["software_pipeline_ready"] for row in families
        ),
        "safe_to_claim_future_data_required_only": bool(
            unmet and all(row["future_data_required_only"] for row in unmet)
        ),
        "required_collectors": required_collectors,
        "collector_state": dict(collector_state or {}),
        "families": families,
        "rerun_command": (
            "portable_runtime\\python\\python.exe "
            "tools\\run_economic_objective_campaigns.py"
        ),
        "promotion_rule": (
            "all three families must independently have >= +4 USD reconciled net, positive "
            "purged OOS, positive true post-freeze forward, liquidatable evidence and placebo beaten"
        ),
    }


def render_collection_plan(plan: Mapping[str, Any]) -> str:
    lines = [
        "# Reprise des campagnes economiques",
        "",
        f"- Objectif global termine : **{plan.get('goal_complete')}**",
        f"- Logiciels de preuve prets : **{plan.get('all_software_pipelines_ready')}**",
        "- Seules des donnees futures manquent : "
        f"**{plan.get('safe_to_claim_future_data_required_only')}**",
        "- Mode : PAPER / READ-ONLY ; execution reelle : false",
        "",
    ]
    for row in plan.get("families") or []:
        progress = row.get("progress") or {}
        lines.extend(
            [
                f"## {row.get('family')}",
                "",
                f"- Verdict objectif : **{row.get('objective_status')}**",
                f"- Etat de preuve : **{row.get('evidence_state')}**",
                f"- Pipeline logiciel pret : **{row.get('software_pipeline_ready')}**",
                f"- Donnees futures uniquement : **{row.get('future_data_required_only')}**",
                f"- Collecte encore actionnable : **{row.get('collection_actionable')}**",
                f"- Action methodologique : **{row.get('methodology_action')}**",
                f"- Progression : `{json.dumps(progress, ensure_ascii=False, sort_keys=True)}`",
                "- Manque exact : " + "; ".join(row.get("exact_missing_evidence") or []),
                f"- Condition de relance : {row.get('rerun_condition')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Collecte",
            "",
            "Collecteurs requis : " + ", ".join(plan.get("required_collectors") or []),
            "",
            "Commande : `" + str(plan.get("rerun_command")) + "`",
            "",
        ]
    )
    return "\n".join(lines)


def write_collection_plan(root: str | Path, plan: Mapping[str, Any]) -> tuple[Path, Path]:
    project_root = Path(root).resolve()
    target = project_root / REPORT_DIR / STATE_FILENAME
    report = project_root / REPORT_DIR / REPORT_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)
    for path, content in (
        (target, json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"),
        (report, render_collection_plan(plan)),
    ):
        temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    return target, report


__all__ = [
    "REPORT_FILENAME",
    "SCHEMA_VERSION",
    "STATE_FILENAME",
    "build_collection_plan",
    "render_collection_plan",
    "write_collection_plan",
]
