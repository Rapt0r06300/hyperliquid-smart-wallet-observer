from hyper_smart_observer.copy_mode.copy_models import CopySizingInput, DeltaAction, NoTradeReason
from hyper_smart_observer.copy_mode.sizing import calculate_paper_copy_sizing


GOOD_ADDRESS = "0x" + "d" * 40


def _input(**kwargs) -> CopySizingInput:
    payload = {
        "leader_wallet": GOOD_ADDRESS,
        "coin": "BTC",
        "action_type": DeltaAction.OPEN_LONG,
        "leader_position_size": 2.0,
        "leader_reference_price": 100.0,
        "leader_account_value": 10_000.0,
        "follower_equity": 1_000.0,
        "max_notional": 100.0,
        "min_notional": 10.0,
    }
    payload.update(kwargs)
    return CopySizingInput(**payload)


def test_copy_sizing_uses_leader_follower_equity_ratio():
    result = calculate_paper_copy_sizing(_input())

    assert result.accepted
    assert result.copy_ratio == 0.1
    assert result.leader_position_notional == 200.0
    assert result.requested_notional == 20.0


def test_copy_sizing_caps_notional_locally():
    result = calculate_paper_copy_sizing(_input(leader_position_size=20.0, max_notional=50.0))

    assert result.accepted
    assert result.requested_notional == 50.0
    assert NoTradeReason.COPY_NOTIONAL_CAPPED.value in result.warnings


def test_copy_sizing_refuses_missing_leader_equity():
    result = calculate_paper_copy_sizing(_input(leader_account_value=None))

    assert not result.accepted
    assert NoTradeReason.LEADER_EQUITY_MISSING.value in result.refusal_reasons


def test_copy_sizing_refuses_unmeasurable_position_notional():
    result = calculate_paper_copy_sizing(_input(leader_position_size=None))

    assert not result.accepted
    assert NoTradeReason.LEADER_POSITION_NOTIONAL_UNMEASURABLE.value in result.refusal_reasons


def test_copy_sizing_refuses_too_small_notional():
    result = calculate_paper_copy_sizing(_input(leader_position_size=0.1))

    assert not result.accepted
    assert NoTradeReason.COPY_NOTIONAL_TOO_SMALL.value in result.refusal_reasons


def test_copy_sizing_refuses_blocked_asset():
    result = calculate_paper_copy_sizing(_input(blocked_assets={"BTC"}))

    assert not result.accepted
    assert NoTradeReason.BLOCKED_ASSET.value in result.refusal_reasons
