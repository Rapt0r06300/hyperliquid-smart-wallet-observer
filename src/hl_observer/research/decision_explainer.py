"""Decision explainer (V12, repo 13): explain decisions using evidence references.

Context layer: turns a decision row + evidence references into a human explanation. It does
NOT change the decision. It stays pure unless a caller explicitly supplies a durable review
ledger path, in which case it appends a consultative receipt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def _is_timestamp_ms(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _review_items(
    values: object,
    *,
    category: str,
    allowed_refs: set[str],
    issues: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(values, (list, tuple)):
        issues.append(f"{category.upper()}_INVALID")
        return []
    normalized: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            issues.append(f"{category.upper()}_ITEM_{index}_INVALID")
            continue
        summary = value.get("summary")
        finding_key = value.get("finding_key")
        refs = value.get("evidence_refs")
        if not isinstance(summary, str) or not summary.strip():
            issues.append(f"{category.upper()}_ITEM_{index}_SUMMARY_MISSING")
        if not isinstance(finding_key, str) or not finding_key.strip():
            issues.append(f"{category.upper()}_ITEM_{index}_FINDING_KEY_MISSING")
        if not isinstance(refs, (list, tuple)) or not refs:
            issues.append(f"{category.upper()}_ITEM_{index}_EVIDENCE_MISSING")
            refs = ()
        valid_refs = [ref for ref in refs if isinstance(ref, str) and ref in allowed_refs]
        if len(valid_refs) != len(refs):
            issues.append(f"{category.upper()}_ITEM_{index}_EVIDENCE_UNVERIFIED")
        normalized.append(
            {
                "summary": summary.strip() if isinstance(summary, str) else "",
                "finding_key": finding_key.strip() if isinstance(finding_key, str) else "",
                "evidence_refs": valid_refs,
            }
        )
    return normalized


def build_leader_review(
    *,
    leader_id: object,
    outcome: object,
    as_of_ms: object,
    max_evidence_age_ms: object,
    favorable: object = (),
    counterevidence: object = (),
    unknowns: object = (),
    falsification_condition: object,
    evidence: object = (),
) -> dict[str, Any]:
    """Build a consultative leader review bound to SAFE, causal, fresh, hashed evidence.

    This is an explanation receipt only. It neither selects a leader nor authorizes a
    Copy-Vault action, changes a frozen candidate/split, selects a champion, or proves PnL.
    """
    issues: list[str] = []
    leader = leader_id.strip() if isinstance(leader_id, str) else ""
    if not leader:
        issues.append("LEADER_ID_MISSING")
    normalized_outcome = outcome.strip().upper() if isinstance(outcome, str) else ""
    if normalized_outcome not in {"RETAINED", "DEMOTED", "REJECTED"}:
        issues.append("OUTCOME_INVALID")
    if not _is_timestamp_ms(as_of_ms):
        issues.append("AS_OF_INVALID")
    if (
        isinstance(max_evidence_age_ms, bool)
        or not isinstance(max_evidence_age_ms, int)
        or max_evidence_age_ms <= 0
    ):
        issues.append("MAX_EVIDENCE_AGE_INVALID")

    evidence_rows: list[dict[str, Any]] = []
    evidence_by_ref: dict[str, dict[str, Any]] = {}
    if not isinstance(evidence, (list, tuple)):
        issues.append("EVIDENCE_INVALID")
        evidence = ()
    for index, row in enumerate(evidence):
        if not isinstance(row, Mapping):
            issues.append(f"EVIDENCE_{index}_INVALID")
            continue
        ref = row.get("ref")
        row_leader = row.get("leader_id")
        source = row.get("source")
        digest = row.get("source_sha256")
        observed = row.get("observed_at_ms")
        received = row.get("received_at_ms")
        period_start = row.get("period_start_ms")
        period_end = row.get("period_end_ms")
        row_issues: list[str] = []
        if not isinstance(ref, str) or not ref.strip():
            row_issues.append("REF_MISSING")
        elif ref in evidence_by_ref:
            row_issues.append("REF_DUPLICATE")
        if row_leader != leader or not leader:
            row_issues.append("LEADER_ID_MISMATCH")
        if not isinstance(source, str) or not source.strip():
            row_issues.append("SOURCE_MISSING")
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            row_issues.append("SOURCE_SHA256_INVALID")
        if row.get("quality") != "SAFE":
            row_issues.append("EVIDENCE_NOT_SAFE")
        if row.get("manifest_verified") is not True:
            row_issues.append("EVIDENCE_MANIFEST_UNVERIFIED")
        if row.get("replay_compatible") is not True:
            row_issues.append("EVIDENCE_NOT_REPLAY_COMPATIBLE")
        timestamps = (observed, received, period_start, period_end)
        if not all(_is_timestamp_ms(value) for value in timestamps):
            row_issues.append("EVIDENCE_TIMESTAMP_INVALID")
        elif _is_timestamp_ms(as_of_ms):
            if (
                observed > received
                or received > as_of_ms
                or period_start > period_end
                or period_end > as_of_ms
            ):
                row_issues.append("EVIDENCE_NOT_CAUSAL_OR_PERIOD_INVALID")
            elif (
                isinstance(max_evidence_age_ms, int)
                and not isinstance(max_evidence_age_ms, bool)
                and max_evidence_age_ms > 0
                and as_of_ms - period_end > max_evidence_age_ms
            ):
                row_issues.append("EVIDENCE_STALE")
        if row_issues:
            issues.extend(f"EVIDENCE_{index}_{reason}" for reason in row_issues)
            continue
        normalized = {
            "ref": ref.strip(),
            "leader_id": leader,
            "source": source.strip(),
            "source_sha256": digest,
            "quality": "SAFE",
            "observed_at_ms": observed,
            "received_at_ms": received,
            "period_start_ms": period_start,
            "period_end_ms": period_end,
        }
        evidence_by_ref[normalized["ref"]] = normalized
        evidence_rows.append(normalized)

    allowed_refs = set(evidence_by_ref)
    favorable_rows = _review_items(
        favorable, category="favorable", allowed_refs=allowed_refs, issues=issues
    )
    counter_rows = _review_items(
        counterevidence, category="counterevidence", allowed_refs=allowed_refs, issues=issues
    )
    favorable_keys = {row["finding_key"] for row in favorable_rows if row["finding_key"]}
    counter_keys = {row["finding_key"] for row in counter_rows if row["finding_key"]}
    contradictions = sorted(favorable_keys & counter_keys)
    if contradictions:
        issues.append("CONTRADICTORY_FINDINGS")

    if not isinstance(unknowns, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() for item in unknowns
    ):
        issues.append("UNKNOWNS_INVALID")
        normalized_unknowns = []
    else:
        normalized_unknowns = [item.strip() for item in unknowns]
    if not isinstance(falsification_condition, str) or not falsification_condition.strip():
        issues.append("FALSIFICATION_CONDITION_MISSING")
        normalized_falsification = ""
    else:
        normalized_falsification = falsification_condition.strip()
    if not evidence_rows:
        issues.append("SAFE_EVIDENCE_MISSING")

    return {
        "schema_version": "copy_vault.leader_review.v1",
        "leader_id": leader,
        "outcome_observed": normalized_outcome,
        "as_of_ms": as_of_ms if _is_timestamp_ms(as_of_ms) else None,
        "favorable": favorable_rows,
        "counterevidence": counter_rows,
        "unknowns": normalized_unknowns,
        "falsification_condition": normalized_falsification,
        "evidence": evidence_rows,
        "contradictory_findings": contradictions,
        "review_status": "UNMEASURABLE" if issues else "CONSULTATIVE_REVIEWABLE",
        "issues": sorted(set(issues)),
        "verification_scope": "STRUCTURAL_RECEIPT_VALIDATION_ONLY",
        "source_bytes_rehashed_here": False,
        "canonical_safe_audit_required": True,
        "consultative_only": True,
        "can_change_decision": False,
        "can_modify_frozen_candidate": False,
        "can_modify_oos_forward_splits": False,
        "can_select_champion": False,
        "can_prove_pnl": False,
    }

def explain_decision(
    decision: dict,
    *,
    evidence_refs: list[str],
    leader_review_payload: Mapping[str, Any] | None = None,
    leader_review_ledger_path: str | None = None,
    leader_review_safe_inventory: Mapping[str, Any] | None = None,
    leader_review_reviewer_id: str | None = None,
    leader_review_id: str | None = None,
) -> dict[str, Any]:
    raw_accepted = decision.get("accepted")
    accepted_is_valid = raw_accepted is None or isinstance(raw_accepted, bool)
    accepted = raw_accepted is True
    code = decision.get("reason_code") or (
        "ACCEPT" if accepted else "NO_TRADE" if accepted_is_valid else "DECISION_STATUS_UNVERIFIABLE"
    )
    msg = decision.get("dashboard_message") or code
    if isinstance(evidence_refs, (list, tuple)):
        refs = [ref.strip() for ref in evidence_refs if isinstance(ref, str) and ref.strip()]
        refs_valid = len(refs) == len(evidence_refs)
    else:
        refs = []
        refs_valid = False
    result = {
        "summary": f"{code}: {msg}",
        "accepted": accepted,
        "decision_status_valid": accepted_is_valid,
        "evidence_refs": refs,
        "evidence_refs_valid": refs_valid,
        "context_only": True,            # never authoritative; never mutates the decision
        "changes_decision": False,
    }
    if leader_review_payload is not None:
        if not isinstance(leader_review_payload, Mapping):
            review = {"review_status": "UNMEASURABLE", "issues": ["LEADER_REVIEW_PAYLOAD_INVALID"]}
        else:
            try:
                review = build_leader_review(**dict(leader_review_payload))
            except (TypeError, ValueError):
                review = {"review_status": "UNMEASURABLE", "issues": ["LEADER_REVIEW_PAYLOAD_INVALID"]}
        result["leader_review"] = review
        if leader_review_ledger_path is not None:
            try:
                from hl_observer.research.leader_review_ledger import append_leader_review

                receipt = append_leader_review(
                    leader_review_ledger_path,
                    leader_review_payload if isinstance(leader_review_payload, Mapping) else {},
                    safe_inventory=leader_review_safe_inventory,
                    reviewer_id=leader_review_reviewer_id or "",
                    review_id=leader_review_id,
                )
                result["leader_review_receipt"] = receipt
                result["leader_review_persistence_status"] = "PERSISTED"
            except (OSError, TypeError, ValueError, RuntimeError) as exc:
                result["leader_review_persistence_status"] = "FAILED"
                result["leader_review_persistence_error"] = (
                    f"{type(exc).__name__}:{exc}"
                )
        else:
            result["leader_review_persistence_status"] = "NOT_REQUESTED"
    return result


__all__ = ["build_leader_review", "explain_decision"]
