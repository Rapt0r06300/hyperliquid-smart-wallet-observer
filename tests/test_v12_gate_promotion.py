from hl_observer.signals.gate_promotion import ACCEPT_MARKER, merge_authoritative_decision


def test_shadow_default_never_changes_decision():
    # authoritative OFF -> score reason untouched even if v12 rejects
    assert merge_authoritative_decision(
        score_reason=ACCEPT_MARKER, v12_accepted=False, v12_reason="STALE_SIGNAL",
        authoritative=False,
    ) == ACCEPT_MARKER


def test_authoritative_can_only_tighten_an_accept():
    # authoritative ON + score accepts + v12 rejects -> binding reject (cleaner)
    assert merge_authoritative_decision(
        score_reason=ACCEPT_MARKER, v12_accepted=False, v12_reason="LIQUIDITY_TOO_LOW",
        authoritative=True,
    ) == "LIQUIDITY_TOO_LOW"


def test_authoritative_never_creates_a_trade():
    # score already rejects -> stays rejected regardless of v12 accept
    assert merge_authoritative_decision(
        score_reason="REJECT_TOO_LATE", v12_accepted=True, v12_reason=None,
        authoritative=True,
    ) == "REJECT_TOO_LATE"


def test_authoritative_accept_when_both_accept():
    # score accepts + v12 accepts -> stays accepted
    assert merge_authoritative_decision(
        score_reason=ACCEPT_MARKER, v12_accepted=True, v12_reason=None,
        authoritative=True,
    ) == ACCEPT_MARKER


def test_missing_v12_reason_falls_back():
    assert merge_authoritative_decision(
        score_reason=ACCEPT_MARKER, v12_accepted=False, v12_reason=None,
        authoritative=True,
    ) == "REJECT_V12_GATE"
