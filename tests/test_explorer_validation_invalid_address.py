from hl_observer.explorer.explorer_validation import validate_explorer_wallet_address


def test_rejects_non_wallet_address_without_treating_it_as_truncated() -> None:
    ok, reason = validate_explorer_wallet_address("not-a-wallet")

    assert ok is False
    assert reason == "INVALID_ADDRESS_REJECTED"
