from __future__ import annotations

from math import ceil

# Official Hyperliquid API contracts verified 2026-07-29:
# https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
# https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
# https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
#
# The generic time-range response contract is 500 elements/distinct blocks.
# userFills and userFillsByTime explicitly allow 2,000 fills per response and
# expose only the 10,000 most recent fills. Keep the endpoint names attached to
# every number so the limits cannot be accidentally interchanged.
HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT = 500
HYPERSMART_USER_FILLS_RECENT_LIMIT = 2_000
HYPERSMART_USER_FILLS_BY_TIME_MAX_RECENT = 10_000
HYPERSMART_USER_TWAP_SLICE_FILLS_RECENT_LIMIT = 2_000
HYPERSMART_MAX_PAGES_PER_WALLET = 3
HYPERSMART_MAX_FILLS_PER_RUN = 1_500
HYPERSMART_WS_MAX_CONNECTIONS = 10
HYPERSMART_WS_MAX_NEW_CONNECTIONS_PER_MIN = 30
HYPERSMART_WS_MAX_SUBSCRIPTIONS = 1_000
HYPERSMART_WS_MAX_UNIQUE_USERS = 10
HYPERSMART_WS_MAX_MESSAGES_PER_MIN = 2_000
HYPERSMART_WS_MAX_INFLIGHT_POST_MESSAGES = 100
HYPERSMART_WS_IDLE_TIMEOUT_SECONDS = 60
HYPERSMART_EXPLORER_WEIGHT = 40
HYPERSMART_REST_WEIGHT_PER_MIN_PER_IP = 1_200
HYPERSMART_INFO_LIGHT_WEIGHT = 2
HYPERSMART_INFO_DEFAULT_WEIGHT = 20
HYPERSMART_INFO_USER_ROLE_WEIGHT = 60
HYPERSMART_INFO_EXTRA_ITEM_BUCKET_SIZE = 20
HYPERSMART_INFO_EXTRA_ITEM_WEIGHT = 1
HYPERSMART_CANDLE_EXTRA_ITEM_BUCKET_SIZE = 60

HYPERSMART_INFO_LIGHT_TYPES = frozenset(
    {
        "l2Book",
        "allMids",
        "clearinghouseState",
        "orderStatus",
        "spotClearinghouseState",
        "exchangeStatus",
    }
)
HYPERSMART_INFO_EXTRA_ITEM_TYPES = frozenset(
    {
        "recentTrades",
        "historicalOrders",
        "userFills",
        "userFillsByTime",
        "fundingHistory",
        "userFunding",
        "nonUserFundingUpdates",
        "twapHistory",
        "userTwapSliceFills",
        "userTwapSliceFillsByTime",
        "delegatorHistory",
        "delegatorRewards",
        "validatorStats",
    }
)


def hyperliquid_info_weight(
    request_type: str,
    *,
    returned_items: int = 0,
) -> int:
    """Return the documented IP weight for one read-only ``/info`` response."""

    request_type = str(request_type)
    if request_type in HYPERSMART_INFO_LIGHT_TYPES:
        base = HYPERSMART_INFO_LIGHT_WEIGHT
    elif request_type == "userRole":
        base = HYPERSMART_INFO_USER_ROLE_WEIGHT
    else:
        base = HYPERSMART_INFO_DEFAULT_WEIGHT

    count = max(0, int(returned_items))
    if request_type in HYPERSMART_INFO_EXTRA_ITEM_TYPES:
        base += (
            ceil(count / HYPERSMART_INFO_EXTRA_ITEM_BUCKET_SIZE)
            * HYPERSMART_INFO_EXTRA_ITEM_WEIGHT
        )
    elif request_type == "candleSnapshot":
        base += (
            ceil(count / HYPERSMART_CANDLE_EXTRA_ITEM_BUCKET_SIZE)
            * HYPERSMART_INFO_EXTRA_ITEM_WEIGHT
        )
    return base


def hyperliquid_extra_item_weight(returned_items: int) -> int:
    """Additional weight for an item-weighted ``/info`` endpoint response."""

    return (
        ceil(max(0, int(returned_items)) / HYPERSMART_INFO_EXTRA_ITEM_BUCKET_SIZE)
        * HYPERSMART_INFO_EXTRA_ITEM_WEIGHT
    )


__all__ = [
    "HYPERSMART_CANDLE_EXTRA_ITEM_BUCKET_SIZE",
    "HYPERSMART_EXPLORER_WEIGHT",
    "HYPERSMART_INFO_DEFAULT_WEIGHT",
    "HYPERSMART_INFO_EXTRA_ITEM_BUCKET_SIZE",
    "HYPERSMART_INFO_EXTRA_ITEM_TYPES",
    "HYPERSMART_INFO_EXTRA_ITEM_WEIGHT",
    "HYPERSMART_INFO_LIGHT_TYPES",
    "HYPERSMART_INFO_LIGHT_WEIGHT",
    "HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT",
    "HYPERSMART_INFO_USER_ROLE_WEIGHT",
    "HYPERSMART_MAX_FILLS_PER_RUN",
    "HYPERSMART_MAX_PAGES_PER_WALLET",
    "HYPERSMART_REST_WEIGHT_PER_MIN_PER_IP",
    "HYPERSMART_USER_FILLS_BY_TIME_MAX_RECENT",
    "HYPERSMART_USER_FILLS_RECENT_LIMIT",
    "HYPERSMART_USER_TWAP_SLICE_FILLS_RECENT_LIMIT",
    "HYPERSMART_WS_MAX_CONNECTIONS",
    "HYPERSMART_WS_MAX_INFLIGHT_POST_MESSAGES",
    "HYPERSMART_WS_MAX_MESSAGES_PER_MIN",
    "HYPERSMART_WS_MAX_NEW_CONNECTIONS_PER_MIN",
    "HYPERSMART_WS_MAX_SUBSCRIPTIONS",
    "HYPERSMART_WS_MAX_UNIQUE_USERS",
    "HYPERSMART_WS_IDLE_TIMEOUT_SECONDS",
    "hyperliquid_extra_item_weight",
    "hyperliquid_info_weight",
]
