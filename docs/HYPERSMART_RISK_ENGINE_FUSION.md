# HyperSmart Risk Engine Fusion

## Objectif

Garantir un moteur deny-by-default: tout signal incomplet, stale, non mesure,
trop couteux, trop illiquide ou source-degraded devient NoTradeDecision.

## Source GitHub inspiratrice

Harrier toolkits pour risk layer unique, MrFadiAi Polymarket-bot pour mock
halts, polymarket_lp_tool pour cooldown/dedupe, CloddsBot pour risk engine and
ledger.

## Adaptation Hyperliquid

RiskEngine outputs:

```text
ALLOW_PAPER_INTENT
REJECT_NO_TRADE
```

Required no-trade reasons include SOURCE_UNAVAILABLE, SOURCE_CONTRADICTION,
STALE_SIGNAL, EDGE_UNMEASURABLE, EDGE_REMAINING_TOO_LOW,
COPY_DEGRADATION_TOO_HIGH, LIQUIDITY_TOO_LOW, INCOMPLETE_HISTORY,
UNKNOWN_DELTA, FLIP_UNKNOWN, NO_MATCHING_PAPER_POSITION_FOR_CLOSE,
RATE_LIMIT_GUARD, WALLET_SCORE_TOO_LOW, INSUFFICIENT_HISTORY,
OPEN_ORDERS_CONTEXT_ONLY, OPEN_ORDERS_ONLY_NOT_EVIDENCE, DUPLICATE_SIGNAL,
CROWDED_OR_LATE_SIGNAL, ONE_BIG_WIN_RISK.

## Modules cibles

- `hyper_smart_observer/risk_engine/*`
- `hyper_smart_observer/copy_mode/copy_models.py`
- `hyper_smart_observer/copy_mode/signal_candidate.py`
- `hyper_smart_observer/copy_mode/sizing.py`
- `src/hl_observer/risk/*`

## Donnees Hyperliquid utilisees

`userFillsByTime`, `clearinghouseState`, `allMids`, `l2Book`, `source_health`.
`openOrders` and `frontendOpenOrders` never create a PaperIntent by themselves.

## Tests requis

- `test_no_open_orders_only_paper_intent.py`
- `test_risk_engine_deny_by_default_all_failure_modes.py`
- `test_edge_remaining_uses_spread_fee_slippage_latency_copy_degradation.py`
- `test_dashboard_stale_signal_not_paper_ready.py`

## Statut DONE / PARTIAL / TODO / DEFER / BAN

PARTIAL. openOrders-only proof, signal deny-by-default, execution/mainnet
refusals and paper-intent failure-mode table are covered by tests. Remaining
TODO: map every copy-mode `NoTradeReason` into one dashboard-visible grouped
distribution.
