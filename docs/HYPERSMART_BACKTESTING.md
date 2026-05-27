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
