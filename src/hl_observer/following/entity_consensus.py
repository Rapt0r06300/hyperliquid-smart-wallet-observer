"""Entity-normalized wallet consensus from public, point-in-time evidence.

The module never claims that two addresses share an operator from one
coincidental fill. It links wallets only from an explicit public entity label
or repeated observable behaviour. Missing history reduces confidence instead
of being replaced by fabricated independence.
"""

from __future__ import annotations

import hashlib
import math
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable
from statistics import median
from typing import Any

DEFAULT_CONFIDENCE_PENALTY = 0.5
DEFAULT_MIN_JOINT_EVENTS = 3


def infer_entity_consensus(
    votes: Iterable[dict[str, Any]],
    *,
    as_of_ms: int | None = None,
    time_window_ms: int = 3_000,
    min_joint_events: int = DEFAULT_MIN_JOINT_EVENTS,
    size_ratio_tolerance: float = 0.12,
    confidence_penalty: float = DEFAULT_CONFIDENCE_PENALTY,
) -> dict[str, Any]:
    """Infer candidate entity clusters using only the supplied causal prefix."""

    rows = [_normalize_vote(row) for row in votes or [] if isinstance(row, dict)]
    rows = [row for row in rows if row is not None]
    if as_of_ms is not None:
        rows = [row for row in rows if row["ts_ms"] <= int(as_of_ms)]
    rows.sort(key=lambda row: (row["ts_ms"], row["wallet"], row["coin"], row["side"]))
    by_wallet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_wallet[row["wallet"]].append(row)
    wallets = sorted(by_wallet)
    if not wallets:
        return _empty_result()

    parent = {wallet: wallet for wallet in wallets}

    def find(wallet: str) -> str:
        while parent[wallet] != wallet:
            parent[wallet] = parent[parent[wallet]]
            wallet = parent[wallet]
        return wallet

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            first, second = sorted((root_left, root_right))
            parent[second] = first

    pair_evidence: list[dict[str, Any]] = []
    measurable_pairs = 0
    total_pairs = len(wallets) * (len(wallets) - 1) // 2
    for index, left in enumerate(wallets):
        for right in wallets[index + 1 :]:
            evidence = _pair_evidence(
                by_wallet[left],
                by_wallet[right],
                time_window_ms=max(1, int(time_window_ms)),
                min_joint_events=max(2, int(min_joint_events)),
                size_ratio_tolerance=max(0.0, float(size_ratio_tolerance)),
            )
            evidence["wallet_a"] = left
            evidence["wallet_b"] = right
            pair_evidence.append(evidence)
            if evidence["measurable"]:
                measurable_pairs += 1
            if evidence["same_entity_candidate"]:
                union(left, right)

    clusters_by_root: dict[str, list[str]] = defaultdict(list)
    for wallet in wallets:
        clusters_by_root[find(wallet)].append(wallet)
    clusters = []
    for members in sorted((sorted(value) for value in clusters_by_root.values()), key=lambda value: value[0]):
        identity = "|".join(members)
        clusters.append(
            {
                "cluster_id": "entity-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12],
                "wallets": members,
                "wallet_count": len(members),
            }
        )

    independence_measurable = total_pairs == 0 or measurable_pairs == total_pairs
    penalty = 1.0 if independence_measurable else _clamp(confidence_penalty, 0.0, 1.0)
    entity_count = len(clusters)
    effective_votes = float(entity_count) * penalty
    if entity_count > 0:
        effective_votes = max(min(1.0, float(entity_count)), effective_votes)
    warnings: list[str] = []
    if not independence_measurable:
        warnings.append("ENTITY_INDEPENDENCE_UNMEASURABLE_CONFIDENCE_PENALTY")
    if entity_count < len(wallets):
        warnings.append("RAW_WALLET_CONSENSUS_INFLATED_BY_ENTITY_LINKS")

    return {
        "wallet_count": len(wallets),
        "entity_cluster_count": entity_count,
        "effective_independent_votes": round(effective_votes, 6),
        "independence_measurable": independence_measurable,
        "measurable_pair_count": measurable_pairs,
        "total_pair_count": total_pairs,
        "confidence_penalty": round(penalty, 6),
        "clusters": clusters,
        "pair_evidence": pair_evidence,
        "warnings": warnings,
        "shadow": True,
        "real_execution": False,
    }


def entity_consensus_gate(
    votes: Iterable[dict[str, Any]],
    *,
    min_independent_votes: float = 2.0,
    strict: bool = True,
    **kwargs: Any,
) -> dict[str, Any]:
    """Return a SHADOW gate that uses entity-normalized evidence in strict mode."""

    result = infer_entity_consensus(votes, **kwargs)
    reasons: list[str] = []
    minimum = max(1.0, float(min_independent_votes))
    if result["wallet_count"] < math.ceil(minimum):
        reasons.append("RAW_WALLET_QUORUM_TOO_LOW")
    if strict and result["independence_measurable"]:
        if result["entity_cluster_count"] < minimum:
            reasons.append("ENTITY_CLUSTER_QUORUM_TOO_LOW")
    elif strict and result["effective_independent_votes"] < minimum:
        reasons.append("INDEPENDENCE_UNMEASURABLE_CONFIDENCE_PENALTY")
    return {
        **result,
        "decision": "ALLOW_SHADOW" if not reasons else "ABSTAIN_SHADOW",
        "reasons": reasons,
        "strict": bool(strict),
        "minimum_independent_votes": minimum,
    }


def _normalize_vote(row: dict[str, Any]) -> dict[str, Any] | None:
    wallet = str(
        row.get("wallet")
        or row.get("wallet_address")
        or row.get("leader_wallet")
        or row.get("adresse")
        or ""
    ).strip().lower()
    coin = str(row.get("coin") or "").strip().upper()
    side = _normalize_side(row.get("side") or row.get("direction") or row.get("dir"))
    try:
        timestamp = int(row.get("ts_ms") or row.get("event_time_ms") or row.get("time") or 0)
    except (TypeError, ValueError):
        timestamp = 0
    if not wallet or not coin or side is None or timestamp <= 0:
        return None
    size = _positive_float(
        row.get("size")
        or row.get("sz")
        or row.get("delta_size")
        or row.get("leader_notional_usdc")
        or row.get("notional_usdc")
    )
    return {
        "wallet": wallet,
        "coin": coin,
        "side": side,
        "ts_ms": timestamp,
        "size": size,
        "public_entity_id": _optional_text(
            row.get("public_entity_id") or row.get("onchain_entity_id")
        ),
        "twap_cadence_ms": _positive_float(row.get("twap_cadence_ms")),
        "funding_profile": _optional_text(row.get("funding_profile")),
        "hedge_profile": _optional_text(row.get("hedge_profile")),
    }


def _pair_evidence(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    *,
    time_window_ms: int,
    min_joint_events: int,
    size_ratio_tolerance: float,
) -> dict[str, Any]:
    left_entity = {row["public_entity_id"] for row in left if row["public_entity_id"]}
    right_entity = {row["public_entity_id"] for row in right if row["public_entity_id"]}
    explicit_measurable = bool(left_entity and right_entity)
    explicit_same = bool(left_entity.intersection(right_entity))

    matches = _match_events(left, right, time_window_ms=time_window_ms)
    joint_count = len(matches)
    denominator = max(1, min(len(left), len(right)))
    sync_rate = joint_count / denominator
    ratios = [
        left_row["size"] / right_row["size"]
        for left_row, right_row in matches
        if left_row["size"] is not None
        and right_row["size"] is not None
        and right_row["size"] > 0
    ]
    persistent_ratio = _ratio_is_persistent(
        ratios,
        min_count=min_joint_events,
        tolerance=size_ratio_tolerance,
    )
    cadence_aligned = _cadence_is_aligned(matches, minimum=min_joint_events)
    profile_aligned = _profile_is_aligned(left, right)
    behavioural_measurable = min(len(left), len(right)) >= min_joint_events
    repeated_sync = joint_count >= min_joint_events and sync_rate >= 0.75
    same_entity = explicit_same or (
        repeated_sync and (persistent_ratio or cadence_aligned or profile_aligned)
    )
    reasons = []
    if explicit_same:
        reasons.append("PUBLIC_ENTITY_LINK")
    if repeated_sync:
        reasons.append("REPEATED_SYNCHRONIZED_FILLS")
    if persistent_ratio:
        reasons.append("PERSISTENT_SIZE_RATIO")
    if cadence_aligned:
        reasons.append("ALIGNED_CADENCE")
    if profile_aligned:
        reasons.append("PUBLIC_FUNDING_HEDGE_PROFILE")
    return {
        "measurable": bool(explicit_measurable or behavioural_measurable),
        "same_entity_candidate": bool(same_entity),
        "joint_event_count": joint_count,
        "synchronization_rate": round(sync_rate, 6),
        "persistent_size_ratio": persistent_ratio,
        "cadence_aligned": cadence_aligned,
        "profile_aligned": profile_aligned,
        "reasons": reasons,
    }


def _match_events(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
    *,
    time_window_ms: int,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    matches = []
    used: set[int] = set()
    by_market: dict[tuple[str, str], list[tuple[int, int, dict[str, Any]]]] = defaultdict(list)
    for index, right_row in enumerate(right):
        by_market[(right_row["coin"], right_row["side"])].append(
            (right_row["ts_ms"], index, right_row)
        )
    timestamps_by_market = {
        market: [item[0] for item in market_rows]
        for market, market_rows in by_market.items()
    }
    for left_row in left:
        market = (left_row["coin"], left_row["side"])
        candidates_for_market = by_market.get(market, [])
        timestamps = timestamps_by_market.get(market, [])
        lower = bisect_left(timestamps, left_row["ts_ms"] - time_window_ms)
        upper = bisect_right(timestamps, left_row["ts_ms"] + time_window_ms)
        candidates = [
            (abs(left_row["ts_ms"] - timestamp), index, right_row)
            for timestamp, index, right_row in candidates_for_market[lower:upper]
            if index not in used
        ]
        if not candidates:
            continue
        _, chosen_index, chosen = min(candidates, key=lambda item: (item[0], item[1]))
        used.add(chosen_index)
        matches.append((left_row, chosen))
    return matches


def _ratio_is_persistent(ratios: list[float], *, min_count: int, tolerance: float) -> bool:
    if len(ratios) < min_count:
        return False
    center = median(ratios)
    if center <= 0:
        return False
    max_relative_error = max(abs(value - center) / center for value in ratios)
    return max_relative_error <= tolerance


def _cadence_is_aligned(
    matches: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    minimum: int,
) -> bool:
    if len(matches) < minimum:
        return False
    left_cadence = [
        matches[index][0]["ts_ms"] - matches[index - 1][0]["ts_ms"]
        for index in range(1, len(matches))
    ]
    right_cadence = [
        matches[index][1]["ts_ms"] - matches[index - 1][1]["ts_ms"]
        for index in range(1, len(matches))
    ]
    if not left_cadence or not right_cadence:
        return False
    difference = abs(median(left_cadence) - median(right_cadence))
    scale = max(1.0, median(left_cadence), median(right_cadence))
    return difference <= max(250.0, scale * 0.10)


def _profile_is_aligned(
    left: list[dict[str, Any]],
    right: list[dict[str, Any]],
) -> bool:
    for field in ("funding_profile", "hedge_profile"):
        left_values = {row[field] for row in left if row[field]}
        right_values = {row[field] for row in right if row[field]}
        if left_values and right_values and left_values.intersection(right_values):
            return True
    return False


def _normalize_side(value: Any) -> str | None:
    side = str(value or "").strip().upper()
    if side in {"B", "BUY", "LONG", "OPEN LONG", "ADD LONG"}:
        return "LONG"
    if side in {"A", "S", "SELL", "SHORT", "OPEN SHORT", "ADD SHORT"}:
        return "SHORT"
    return None


def _positive_float(value: Any) -> float | None:
    try:
        number = abs(float(value))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _empty_result() -> dict[str, Any]:
    return {
        "wallet_count": 0,
        "entity_cluster_count": 0,
        "effective_independent_votes": 0.0,
        "independence_measurable": False,
        "measurable_pair_count": 0,
        "total_pair_count": 0,
        "confidence_penalty": 0.0,
        "clusters": [],
        "pair_evidence": [],
        "warnings": ["NO_PUBLIC_WALLET_EVIDENCE"],
        "shadow": True,
        "real_execution": False,
    }


__all__ = [
    "DEFAULT_CONFIDENCE_PENALTY",
    "DEFAULT_MIN_JOINT_EVENTS",
    "entity_consensus_gate",
    "infer_entity_consensus",
]
