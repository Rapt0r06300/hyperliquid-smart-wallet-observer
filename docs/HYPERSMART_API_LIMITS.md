# HyperSmart API Limits

Status: conservative read-only implementation notes.

HyperSmart uses Hyperliquid `/info` only for REST reads. No `/exchange`,
signature, private key, order placement or mainnet execution is implemented.

## REST `/info`

Configured defaults:

- `HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT=500`
- `HYPERSMART_USER_FILLS_RECENT_LIMIT=2000`
- `HYPERSMART_USER_FILLS_BY_TIME_MAX_RECENT=10000`
- `HYPERSMART_REST_WEIGHT_LIMIT_PER_MINUTE=1200`
- `HYPERSMART_INFO_WEIGHT_EXTRA_ITEM_BUCKET_SIZE=20`
- `HYPERSMART_MAX_PAGES_PER_WALLET=5`
- `HYPERSMART_MAX_FILLS_PER_RUN=10000`

Official points verified on 2026-06-02:

- Time-range responses return only 500 elements or distinct blocks per response;
  the next request must resume from the last returned timestamp.
- `userFills` returns at most 2000 recent fills.
- `userFillsByTime` returns at most 2000 fills per response and only the 10000
  most recent fills are available.
- REST requests share 1200 aggregated weight per minute per IP.
- `l2Book`, `allMids`, `clearinghouseState`, `orderStatus`,
  `spotClearinghouseState` and `exchangeStatus` have low documented info
  weight; most other info requests are heavier.
- `userFills`, `userFillsByTime`, `historicalOrders` and other large endpoints
  have additional weight per 20 returned items.
- Explorer API requests have weight 40 and must remain secondary/experimental.

The official Hyperliquid rate-limit documentation describes a shared REST
weight limit of 1200 per minute per IP. It also documents extra weight buckets
for response-heavy `/info` methods, including `userFills` and
`userFillsByTime`, per 20 returned items. HyperSmart uses those values as
guardrails but still applies stricter local page and fill caps.

Pagination policy for time ranged fills:

- `startTime` is treated as inclusive.
- next cursor is `last_timestamp + 1`.
- stop on empty response.
- stop if timestamp does not progress.
- stop when max pages is reached.
- stop when max fills per run is reached.
- every stop records a `stopped_reason`.

## WebSocket

Configured defaults:

- `HYPERSMART_WS_MAX_CONNECTIONS=10`
- `HYPERSMART_WS_MAX_NEW_CONNECTIONS_PER_MIN=30`
- `HYPERSMART_WS_MAX_SUBSCRIPTIONS=1000`
- `HYPERSMART_WS_MAX_UNIQUE_USERS=10`

WebSocket monitoring is disabled by default and must stay read-only. User
specific streams are restricted to shortlist/watchlist users only.

## Explorer

Configured default:

- `HYPERSMART_EXPLORER_WEIGHT=40`

Explorer observation remains experimental and disabled by default. HyperSmart
does not bypass protections and does not depend on undocumented private routes.
