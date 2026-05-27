from __future__ import annotations

from pydantic import BaseModel, Field

from hl_observer.config.settings import Settings
from hl_observer.markets.universe import MarketUniverse


class MarketSelection(BaseModel):
    coins: list[str] = Field(default_factory=list)
    rejected: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


def select_markets_for_scan(
    universe: MarketUniverse,
    settings: Settings,
    *,
    wallet_active_coins: list[str] | None = None,
    positive_pnl_coins: list[str] | None = None,
    max_coins: int | None = None,
    include_altcoins: bool | None = None,
) -> MarketSelection:
    limit = max_coins or settings.market_universe.max_coins_per_scan
    allowed_altcoins = settings.market_universe.altcoins_enabled if include_altcoins is None else include_altcoins
    excluded = {coin.upper() for coin in settings.market_universe.excluded_coins}
    wallet_active = {coin.upper() for coin in wallet_active_coins or []}
    positive_pnl = {coin.upper() for coin in positive_pnl_coins or []}
    selected: list[str] = []
    rejected: dict[str, str] = {}
    ranked = sorted(
        universe.coins,
        key=lambda coin: _selection_priority(
            coin,
            wallet_active=wallet_active,
            positive_pnl=positive_pnl,
            prefer_major=settings.market_universe.prefer_major_coins,
        ),
    )
    for coin in ranked:
        coin = coin.upper()
        if coin in excluded:
            rejected[coin] = "configured_exclusion"
            continue
        if not allowed_altcoins and coin not in {"BTC", "ETH"}:
            rejected[coin] = "altcoins_disabled"
            continue
        if len(selected) >= limit:
            rejected[coin] = "scan_limit"
            continue
        selected.append(coin)
    notes = []
    if selected == ["BTC"] and len(universe.coins) > 1:
        notes.append("btc_only_selection_detected")
    return MarketSelection(coins=selected, rejected=rejected, notes=notes)


def _selection_priority(
    coin: str,
    *,
    wallet_active: set[str],
    positive_pnl: set[str],
    prefer_major: bool,
) -> tuple[int, int, int, str]:
    majors = ["BTC", "ETH", "SOL", "HYPE"]
    active_rank = 0 if coin in wallet_active else 1
    pnl_rank = 0 if coin in positive_pnl else 1
    major_rank = majors.index(coin) if prefer_major and coin in majors else len(majors)
    return (active_rank, pnl_rank, major_rank, coin)

