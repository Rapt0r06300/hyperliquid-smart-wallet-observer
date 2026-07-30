from __future__ import annotations

from hl_observer.following.entity_consensus import (
    entity_consensus_gate,
    infer_entity_consensus,
)


def _vote(
    wallet: str,
    ts_ms: int,
    size: float,
    *,
    entity: str | None = None,
    coin: str = "HYPE",
    side: str = "LONG",
) -> dict:
    return {
        "wallet": wallet,
        "coin": coin,
        "side": side,
        "ts_ms": ts_ms,
        "size": size,
        "public_entity_id": entity,
    }


def test_public_entity_labels_normalize_raw_wallet_count():
    votes = [
        _vote("0xa", 1_000, 10, entity="desk-one"),
        _vote("0xb", 1_100, 20, entity="desk-one"),
        _vote("0xc", 1_200, 15, entity="desk-two"),
    ]
    result = infer_entity_consensus(votes)
    assert result["wallet_count"] == 3
    assert result["entity_cluster_count"] == 2
    assert result["effective_independent_votes"] == 2.0
    assert result["independence_measurable"] is True
    assert sorted(cluster["wallet_count"] for cluster in result["clusters"]) == [1, 2]


def test_repeated_synchronization_and_persistent_size_ratio_link_wallets():
    votes = []
    for index, size in enumerate((10, 20, 30)):
        votes.append(_vote("0xa", 1_000 + index * 2_000, size))
        votes.append(_vote("0xb", 1_100 + index * 2_000, size / 2))
        votes.append(_vote("0xc", 20_000 + index * 4_000, size * 3))
    result = infer_entity_consensus(votes, time_window_ms=500)
    assert result["independence_measurable"] is True
    assert result["entity_cluster_count"] == 2
    linked = next(
        evidence
        for evidence in result["pair_evidence"]
        if {evidence["wallet_a"], evidence["wallet_b"]} == {"0xa", "0xb"}
    )
    assert linked["same_entity_candidate"] is True
    assert "PERSISTENT_SIZE_RATIO" in linked["reasons"]


def test_one_coincident_fill_does_not_prove_independence_or_common_entity():
    votes = [_vote("0xa", 1_000, 10), _vote("0xb", 1_100, 20)]
    result = infer_entity_consensus(votes)
    assert result["entity_cluster_count"] == 2
    assert result["independence_measurable"] is False
    assert result["effective_independent_votes"] == 1.0
    gate = entity_consensus_gate(votes, min_independent_votes=2, strict=True)
    assert gate["decision"] == "ABSTAIN_SHADOW"
    assert "INDEPENDENCE_UNMEASURABLE_CONFIDENCE_PENALTY" in gate["reasons"]


def test_entity_inference_is_deterministic_and_ignores_rows_after_as_of():
    prefix = [
        _vote("0xa", 1_000, 10, entity="desk-a"),
        _vote("0xb", 1_100, 20, entity="desk-b"),
    ]
    future = [
        _vote("0xa", 9_000, 5, entity="future-shared"),
        _vote("0xb", 9_100, 5, entity="future-shared"),
    ]
    expected = infer_entity_consensus(prefix, as_of_ms=2_000)
    with_future = infer_entity_consensus(
        list(reversed(prefix + future)),
        as_of_ms=2_000,
    )
    assert with_future == expected
    assert expected["entity_cluster_count"] == 2
    assert expected["effective_independent_votes"] == 2.0


def test_strict_gate_uses_entity_count_when_independence_is_measurable():
    votes = [
        _vote("0xa", 1_000, 10, entity="desk-one"),
        _vote("0xb", 1_100, 20, entity="desk-one"),
        _vote("0xc", 1_200, 15, entity="desk-two"),
    ]
    allowed = entity_consensus_gate(votes, min_independent_votes=2, strict=True)
    rejected = entity_consensus_gate(votes, min_independent_votes=3, strict=True)
    assert allowed["decision"] == "ALLOW_SHADOW"
    assert rejected["decision"] == "ABSTAIN_SHADOW"
    assert rejected["reasons"] == ["ENTITY_CLUSTER_QUORUM_TOO_LOW"]
    assert rejected["real_execution"] is False
