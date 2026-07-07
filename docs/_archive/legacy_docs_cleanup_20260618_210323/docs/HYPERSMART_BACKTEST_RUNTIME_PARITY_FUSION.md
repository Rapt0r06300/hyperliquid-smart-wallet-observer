# HyperSmart Backtest Runtime Parity Fusion

## Objectif

Faire passer backtests et replays par les memes modeles, EdgeCalculator,
RiskEngine and PaperEngine que le runtime read-only.

## Source GitHub inspiratrice

prediction-market-backtesting pour replay/book/trades/equity/drawdown/Sharpe,
polyrec pour CSV features and backtesting, mlmodelpoly pour feature pipeline.

## Adaptation Hyperliquid

Backtest/replay must model:

```text
fees
spread
slippage
latency
liquidity
missed fills
stale signals
copy degradation
no-trade distribution
confidence calibration
```

No live sandbox execution path is allowed.

## Modules cibles

- `hyper_smart_observer/backtesting/replay_engine.py`
- `hyper_smart_observer/backtesting/backtest_report.py`
- `src/hl_observer/backtest/replay_engine.py`
- `src/hl_observer/simulation/*`

## Donnees Hyperliquid utilisees

Cached read-only fills, l2 snapshots, mids, trade ticks, source health and
DecisionLedger/no-trade rows.

## Tests requis

- `test_backtest_runtime_parity_same_models.py`
- `test_hypersmart_backtesting.py`
- `test_edge_remaining_uses_spread_fee_slippage_latency_copy_degradation.py`

## Statut DONE / PARTIAL / TODO / DEFER / BAN

PARTIAL. Replay/backtesting modules exist and the explicit same-model parity
contract is implemented in `hyper_smart_observer/backtesting/runtime_parity.py`.
Full replay of book deltas/trade ticks and confidence calibration remains TODO.
