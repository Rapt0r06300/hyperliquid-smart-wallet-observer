from hl_observer.copy_mode.reentry_cooldown import ReentryCooldown


def test_seconds_remaining_is_zero_without_recorded_exit() -> None:
    cooldown = ReentryCooldown(cooldown_seconds=1800.0)

    assert cooldown.seconds_remaining("SOL", 1_000_000) == 0.0
