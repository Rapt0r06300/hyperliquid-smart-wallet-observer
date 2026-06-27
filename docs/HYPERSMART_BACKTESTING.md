# HyperSmart Backtesting

Le backtesting est local.

Il simule:

- fees;
- spread;
- slippage;
- latency;
- actions sautees;
- drawdown.

Un backtest positif ne garantit rien. Il sert a invalider ou explorer une hypothese.

Les commandes `--backtest-wallet` et `--backtest-top-wallets` ecrivent aussi un
rapport JSON dans `data/reports/` au format
`backtest_<wallet>_<scenario>.json`.
## Docs-to-code checklist

- [x] Backtest local only, no order.
- [x] Costs model exists in active package.
- [ ] Replay 300s vs 60s vs WS from large historical deltas.
- [ ] Missed fills and partial fills persisted in report.
- [ ] Dedicated dashboard section wired to latest replay.
- [ ] Contract test proving historical PnL is not reported as future profit.
