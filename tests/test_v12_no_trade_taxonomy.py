import pytest

from hl_observer.signals.no_trade_taxonomy import (
    ALIASES,
    TAXONOMY,
    NoTradeCode,
    NoTradeReason,
    Severity,
    all_codes,
    by_category,
    is_retriable,
    reason,
    resolve,
)

_V10_6 = {
    "INSUFFICIENT_DATA", "SOURCE_STALE", "SOURCE_DEGRADED", "SOURCE_CONFLICT", "RATE_LIMITED",
    "WALLET_NOT_SCORED", "WALLET_SCORE_TOO_LOW", "COPYABILITY_TOO_LOW", "ONE_BIG_WIN_RISK",
    "PNL_CONCENTRATION_RISK", "HIGH_DRAWDOWN_RISK", "INACTIVE_WALLET", "SUSPICIOUS_WALLET",
    "LIFECYCLE_UNKNOWN", "ORPHAN_CLOSE", "AMBIGUOUS_FLIP", "DUPLICATE_SIGNAL", "SIGNAL_TOO_OLD",
    "OPEN_ORDERS_CONTEXT_ONLY", "MID_MISSING", "L2BOOK_MISSING", "SPREAD_TOO_WIDE",
    "LIQUIDITY_TOO_LOW", "DEPTH_TOO_LOW", "VOLATILITY_TOO_HIGH", "EDGE_UNMEASURABLE",
    "EDGE_REMAINING_TOO_LOW", "COPY_DEGRADATION_TOO_HIGH", "COOLDOWN_ACTIVE",
    "PORTFOLIO_EXPOSURE_TOO_HIGH", "MAX_OPEN_POSITIONS", "BLOCKED_ASSET", "LOSS_HALT_ACTIVE",
    "CIRCUIT_BREAKER_ACTIVE", "PAPER_ENGINE_CANNOT_MODEL", "NO_MATCHING_PAPER_POSITION",
    "BACKTEST_CONTEXT_ONLY", "DASHBOARD_EMPTY_STATE",
}
_V11_11 = {
    "DATA_NOT_PAGINATED_ENOUGH", "BACKFILL_INCOMPLETE", "SOURCE_NOT_AUTHENTICATED_PUBLIC_ONLY",
    "PROXY_POOL_DEGRADED", "FETCH_PROVENANCE_MISSING", "RAW_HASH_MISSING", "FEATURE_HASH_MISSING",
    "WALLET_EVIDENCE_TOO_LOW", "COPY_DELAY_TOO_HIGH", "EXIT_NOT_FOLLOWABLE",
    "QUEUE_PROBABILITY_TOO_LOW", "MAKER_REBATE_UNAVAILABLE", "FUNDING_UNKNOWN",
    "LEVERAGE_RISK_TOO_HIGH", "MARGIN_RISK_TOO_HIGH", "CLUSTER_TOO_CROWDED",
    "CORRELATION_TOO_HIGH", "STRATEGY_SHADOW_ONLY", "MODEL_NOT_CALIBRATED",
}
_V12_CLUSTER = {
    "CLUSTER_TOO_FEW_WALLETS", "CLUSTER_STALE", "CLUSTER_CONFIDENCE_TOO_LOW",
}


def test_taxonomy_covers_both_doc_blocks_exactly():
    expected = _V10_6 | _V11_11 | _V12_CLUSTER
    actual = set(all_codes())
    assert actual == expected, "missing=%s extra=%s" % (expected - actual, actual - expected)
    assert len(all_codes()) == len(_V10_6) + len(_V11_11) + len(_V12_CLUSTER) == 60


def test_every_code_has_complete_seven_attribute_metadata():
    valid_sev = {s.value for s in Severity}
    for code in all_codes():
        r = TAXONOMY[code]
        assert r.reason_code == code
        assert r.severity in valid_sev
        assert isinstance(r.is_retriable, bool)
        assert r.category and isinstance(r.category, str)
        assert r.dashboard_message.strip(), code + " empty dashboard_message"
        assert r.next_action.strip(), code + " empty next_action"
        assert set(r.to_dict()) == {
            "reason_code", "severity", "is_retriable",
            "missing_data", "next_action", "evidence_refs", "dashboard_message",
        }


def test_enum_member_access_and_value():
    assert NoTradeCode("SIGNAL_TOO_OLD") == NoTradeCode.SIGNAL_TOO_OLD
    assert NoTradeCode.SIGNAL_TOO_OLD.value == "SIGNAL_TOO_OLD"


def test_aliases_resolve_to_real_canonical_codes():
    for alias, canonical in ALIASES.items():
        assert canonical in _V10_6 | _V11_11 | _V12_CLUSTER
        assert resolve(alias) == NoTradeCode(canonical)


@pytest.mark.parametrize("literal", [
    "REJECT_TOO_LATE", "STALE_SIGNAL", "PRICE_MISSING", "PRICE_MISSING_EXIT",
    "LIQUIDITY_TOO_LOW", "EDGE_REMAINING_TOO_LOW", "MAX_EXPOSURE_REACHED",
    "EXOTIC_MARKET_SKIPPED", "UNKNOWN_DELTA", "REJECT_KELLY_NO_EDGE",
])
def test_runtime_literals_are_all_covered(literal):
    code = resolve(literal)
    assert code.value in TAXONOMY


def test_resolve_is_case_insensitive_and_trims():
    assert resolve("  signal_too_old ") == NoTradeCode.SIGNAL_TOO_OLD


def test_unknown_code_raises():
    with pytest.raises(ValueError):
        resolve("TOTALLY_MADE_UP_REASON")


def test_reason_builder_fills_defaults_and_allows_overrides():
    r = reason("REJECT_TOO_LATE")
    assert r.reason_code == "SIGNAL_TOO_OLD"
    assert r.severity == "BLOCK"
    assert r.is_retriable is False
    assert r.dashboard_message
    r2 = reason("MID_MISSING", missing_data=["allMids:BTC"], evidence_refs=["fetch:abc123"], dashboard_message="Mid BTC absent")
    assert r2.missing_data == ("allMids:BTC",)
    assert r2.evidence_refs == ("fetch:abc123",)
    assert r2.dashboard_message == "Mid BTC absent"
    assert r2.blocks_trade is True


def test_is_retriable_helper():
    assert is_retriable("SOURCE_STALE") is True
    assert is_retriable("BLOCKED_ASSET") is False
    assert is_retriable("EXOTIC_MARKET_SKIPPED") is False


def test_by_category_groups_every_code():
    groups = by_category()
    total = sum(len(v) for v in groups.values())
    assert total == len(all_codes())
    assert "MARKET" in groups and "RISK" in groups and "EVIDENCE" in groups


def test_taxonomy_has_no_execution_surface():
    import hl_observer.signals.no_trade_taxonomy as m
    pub = [n for n in dir(m) if not n.startswith("_")]
    for bad in ("submit", "place", "order", "sign", "send", "execute", "deposit"):
        assert not any(bad in n.lower() for n in pub)
