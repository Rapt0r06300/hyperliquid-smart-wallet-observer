from hl_observer.patterns.pattern_detector import PatternType, detect_wallet_patterns
from hl_observer.scoring.wallet_score_v2 import WalletPerformanceSample


def _sample(wallet: str, i: int, pnl: float, coin: str = "BTC", hold_ms: int | None = None):
    return WalletPerformanceSample(
        wallet=wallet,
        coin=coin,
        closed_pnl_usdc=pnl,
        timestamp_ms=1_700_000_000_000 + i * 60_000,
        holding_time_ms=hold_ms,
    )


def test_pattern_detector_refuses_insufficient_data():
    wallet = "0x" + "a" * 40
    patterns = detect_wallet_patterns(wallet, [_sample(wallet, 0, 10.0)], min_samples=3)
    assert patterns[0].pattern_type == PatternType.INSUFFICIENT_DATA
    assert "INSUFFICIENT_CLOSED_PNL" in patterns[0].warnings


def test_pattern_detector_flags_one_big_win_and_coin_specialist():
    wallet = "0x" + "b" * 40
    samples = [_sample(wallet, 0, 500.0, "HYPE")]
    samples += [_sample(wallet, i + 1, 5.0, "HYPE") for i in range(10)]
    samples += [_sample(wallet, 20, -10.0, "BTC")]

    patterns = detect_wallet_patterns(wallet, samples, min_samples=12)
    types = {p.pattern_type for p in patterns}
    assert PatternType.ONE_BIG_WIN in types
    assert PatternType.COIN_SPECIALIST in types
    assert any("ONE_BIG_WIN_RISK" in p.risk_flags for p in patterns)


def test_pattern_detector_detects_loss_cutting_and_winner_holding():
    wallet = "0x" + "c" * 40
    samples = []
    for i in range(6):
        samples.append(_sample(wallet, i, -5.0, "BTC", hold_ms=5 * 60_000))
    for i in range(6):
        samples.append(_sample(wallet, i + 6, 20.0, "ETH", hold_ms=2 * 60 * 60_000))

    patterns = detect_wallet_patterns(wallet, samples, min_samples=12)
    types = {p.pattern_type for p in patterns}
    assert PatternType.CUTS_LOSSES in types
    assert PatternType.LETS_WINNERS_RUN in types
    assert all("future profit" in p.research_only_message for p in patterns)
