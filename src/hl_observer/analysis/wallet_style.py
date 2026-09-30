from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass


class WalletStyle(StrEnum):
    BREAKOUT_TRADER = "BREAKOUT_TRADER"
    MOMENTUM_TRADER = "MOMENTUM_TRADER"
    MEAN_REVERSION_TRADER = "MEAN_REVERSION_TRADER"
    SCALPER = "SCALPER"
    SWING_TRADER = "SWING_TRADER"
    DCA_TRADER = "DCA_TRADER"
    HIGH_LEVERAGE_RISKY = "HIGH_LEVERAGE_RISKY"
    ALTCOIN_SPECIALIST = "ALTCOIN_SPECIALIST"
    BTC_ETH_MAJOR_ONLY = "BTC_ETH_MAJOR_ONLY"
    HYPE_SPECIALIST = "HYPE_SPECIALIST"
    WHALE_POSITIONAL = "WHALE_POSITIONAL"
    HEDGER_OR_COMPLEX = "HEDGER_OR_COMPLEX"
    UNKNOWN = "UNKNOWN"


def infer_wallet_style(*, coins: list[str], openings: list[str]) -> WalletStyle:
    coin_set = {coin.upper() for coin in coins}
    if coin_set == {"BTC"} or coin_set <= {"BTC", "ETH"} and coin_set:
        return WalletStyle.BTC_ETH_MAJOR_ONLY
    if "HYPE" in coin_set and len(coin_set) <= 3:
        return WalletStyle.HYPE_SPECIALIST
    if any(coin not in {"BTC", "ETH", "SOL", "HYPE"} for coin in coin_set):
        return WalletStyle.ALTCOIN_SPECIALIST
    if any("DCA" in opening for opening in openings):
        return WalletStyle.DCA_TRADER
    if any("MOMENTUM" in opening for opening in openings):
        return WalletStyle.MOMENTUM_TRADER
    return WalletStyle.UNKNOWN
