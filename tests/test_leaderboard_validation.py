from hl_observer.wallets.leaderboard_validation import (
    is_full_wallet_address,
    is_truncated_wallet_display,
    validate_leaderboard_wallet_address,
)


VALID = "0x" + "a" * 40


def test_is_full_wallet_address_accepts_42_char_hex():
    assert is_full_wallet_address(VALID)


def test_is_full_wallet_address_rejects_truncated():
    assert not is_full_wallet_address("0x393d...2109")
    assert is_truncated_wallet_display("0x393d...2109")


def test_is_full_wallet_address_rejects_short_address():
    assert not is_full_wallet_address("0x123")


def test_is_full_wallet_address_rejects_non_hex():
    assert not is_full_wallet_address("0x" + "g" * 40)


def test_leaderboard_does_not_invent_full_address():
    result = validate_leaderboard_wallet_address("0x393d...2109")

    assert result.normalized_value is None
    assert result.is_truncated


def test_no_truncated_address_completion_logic():
    import inspect
    import hl_observer.wallets.leaderboard_validation as validation

    source = inspect.getsource(validation)
    assert "random" not in source
    assert "zfill" not in source
