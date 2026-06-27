"""Fresh multi-wallet cluster detection for leader deltas.

The detector answers a narrow question: did several independent wallets produce
compatible fresh deltas on the same coin and side within a tight time window?
It is read-only research input for paper simulation. It never creates a real
order and it does not turn public flow context alone into a guaranteed signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from hl_observer.position_lifecycle.reconstructor import LifecycleAction
from hl_observer.signals.leader_delta import LeaderDelta


ENTRY_ACTIONS = {
    LifecycleAction.OPEN_LONG,
    LifecycleAction.OPEN_SHORT,
    LifecycleAction.ADD,
    LifecycleAction.INCREASE,
}


@dataclass(frozen=True, slots=True)
class ClusterConfig:
    window_ms: int = 4_000
    max_age_ms: int = 6_000
    min_unique_wallets: int = 2
    min_mean_confidence: float = 0.60


@dataclass(frozen=True, slots=True)
class SignalCluster:
    cluster_id: str
    coin: str
    side: str
    action_family: str
    first_event_ms: int
    last_event_ms: int
    observed_at_ms: int
    age_ms: int
    unique_wallets: tuple[str, ...]
    delta_ids: tuple[str, ...]
    total_abs_delta_size: float
    mean_confidence: float
    consensus_strength: float
    accepted: bool
    reason_codes: tuple[str, ...] = field(default_factory=tuple)


def detect_signal_clusters(
    deltas: list[LeaderDelta],
    *,
    observed_at_ms: int,
    config: ClusterConfig | None = None,
) -> list[SignalCluster]:
    """Detect compatible fresh clusters from leader deltas."""

    cfg = config or ClusterConfig()
    usable = [d for d in deltas if d.action in ENTRY_ACTIONS and d.leader_event_time_ms is not None]
    usable.sort(key=lambda d: (d.coin.upper(), _side_of(d), d.leader_event_time_ms or 0, d.wallet.lower()))

    clusters: list[SignalCluster] = []
    for idx, seed in enumerate(usable):
        side = _side_of(seed)
        if side == "UNKNOWN":
            continue
        start = int(seed.leader_event_time_ms or seed.observed_at_ms)
        group: list[LeaderDelta] = []
        for d in usable[idx:]:
            if d.coin.upper() != seed.coin.upper() or _side_of(d) != side:
                continue
            event_ts = int(d.leader_event_time_ms or d.observed_at_ms)
            if event_ts < start:
                continue
            if event_ts - start > cfg.window_ms:
                break
            group.append(d)
        if group:
            clusters.append(_build_cluster(group, observed_at_ms=observed_at_ms, config=cfg))

    return _dedupe_clusters(clusters)


def _build_cluster(group: list[LeaderDelta], *, observed_at_ms: int, config: ClusterConfig) -> SignalCluster:
    group = sorted(group, key=lambda d: (d.leader_event_time_ms or d.observed_at_ms, d.wallet.lower()))
    wallets = tuple(sorted({d.wallet.lower() for d in group}))
    first_ms = min(int(d.leader_event_time_ms or d.observed_at_ms) for d in group)
    last_ms = max(int(d.leader_event_time_ms or d.observed_at_ms) for d in group)
    age_ms = max(0, observed_at_ms - last_ms)
    mean_conf = sum(max(0.0, min(1.0, d.confidence)) for d in group) / max(1, len(group))
    total_abs = sum(abs(float(d.delta_size)) for d in group)
    side = _side_of(group[0])
    reasons: list[str] = []
    if len(wallets) < config.min_unique_wallets:
        reasons.append("CLUSTER_TOO_FEW_WALLETS")
    if age_ms > config.max_age_ms:
        reasons.append("CLUSTER_STALE")
    if mean_conf < config.min_mean_confidence:
        reasons.append("CLUSTER_CONFIDENCE_TOO_LOW")
    for d in group:
        reasons.extend(d.reason_codes)
    unique_reasons = tuple(dict.fromkeys(reasons))
    strength = _consensus_strength(
        wallet_count=len(wallets),
        mean_confidence=mean_conf,
        age_ms=age_ms,
        total_abs_delta_size=total_abs,
        config=config,
    )
    cluster_id = _cluster_id(group, observed_at_ms)
    return SignalCluster(
        cluster_id=cluster_id,
        coin=group[0].coin.upper(),
        side=side,
        action_family="ENTRY",
        first_event_ms=first_ms,
        last_event_ms=last_ms,
        observed_at_ms=observed_at_ms,
        age_ms=age_ms,
        unique_wallets=wallets,
        delta_ids=tuple(d.delta_id for d in group),
        total_abs_delta_size=round(total_abs, 10),
        mean_confidence=round(mean_conf, 6),
        consensus_strength=round(strength, 6),
        accepted=not unique_reasons,
        reason_codes=unique_reasons,
    )


def _side_of(delta: LeaderDelta) -> str:
    if delta.action is LifecycleAction.OPEN_LONG:
        return "LONG"
    if delta.action is LifecycleAction.OPEN_SHORT:
        return "SHORT"
    if delta.current_size > 0:
        return "LONG"
    if delta.current_size < 0:
        return "SHORT"
    return "UNKNOWN"


def _consensus_strength(
    *,
    wallet_count: int,
    mean_confidence: float,
    age_ms: int,
    total_abs_delta_size: float,
    config: ClusterConfig,
) -> float:
    wallet_component = min(1.0, max(0.0, (wallet_count - 1) / 4.0))
    freshness_component = max(0.0, 1.0 - age_ms / max(1, config.max_age_ms))
    size_component = min(1.0, total_abs_delta_size / 10.0)
    return max(0.0, min(1.0, 0.45 * wallet_component + 0.30 * mean_confidence + 0.20 * freshness_component + 0.05 * size_component)) * 100.0


def _cluster_id(group: list[LeaderDelta], observed_at_ms: int) -> str:
    material = "|".join(
        [
            str(observed_at_ms),
            group[0].coin.upper(),
            _side_of(group[0]),
            *sorted(d.delta_id for d in group),
        ]
    )
    return "cluster:" + sha256(material.encode("utf-8")).hexdigest()


def _dedupe_clusters(clusters: list[SignalCluster]) -> list[SignalCluster]:
    by_wallet_set: dict[tuple[str, str, tuple[str, ...]], SignalCluster] = {}
    for c in clusters:
        key = (c.coin, c.side, c.unique_wallets)
        current = by_wallet_set.get(key)
        if current is None or c.consensus_strength > current.consensus_strength:
            by_wallet_set[key] = c
    return sorted(by_wallet_set.values(), key=lambda c: (-c.consensus_strength, c.coin, c.side, c.first_event_ms))


__all__ = ["ClusterConfig", "SignalCluster", "detect_signal_clusters"]
