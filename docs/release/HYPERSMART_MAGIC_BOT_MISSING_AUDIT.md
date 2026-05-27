# HyperSmart Magic Bot Coverage Audit

Status date: 2026-05-25.

This audit maps the product Markdown to the actual local implementation. Any
accepted copy action remains research/paper only. A score is not a signal, a
paper trade is not an order, and historical PnL is not future profit.

| Exigence du Markdown | Statut reel | Fichier(s) | Test(s) | Ce qui manque | Priorite | Prochaine correction |
|---|---|---|---|---|---|---|
| Smart Leaderboard + Auto-Select | Delivered | `hyper_smart_observer/copy_mode/leaderboard_selector.py` | `tests/test_hypersmart_copy_mode.py` | Larger real data imports can be added | High | Add more import fixtures |
| Validation adresse complete 0x + 40 hex | Delivered | `leaderboard_selector.py`, `validation.py` | `test_hypersmart_copy_mode.py` | None | High | Keep strict |
| Refus adresse tronquee avec `...` | Delivered | `leaderboard_selector.py` | `test_hypersmart_copy_mode.py` | None | High | Keep strict |
| Consistency score | Delivered | `leaderboard_selector.py`, scoring modules | `test_hypersmart_copy_mode.py` | More per-coin history | Medium | Add richer fixtures |
| Max drawdown | Delivered | `leaderboard_selector.py`, scoring modules | scoring tests | None | High | Keep conservative |
| PnL concentration / one_big_win | Delivered | `leaderboard_selector.py`, patterns | `test_hypersmart_copy_mode.py`, pattern tests | None | High | Tune thresholds only with data |
| Per-coin ROI stability | Partial | `leaderboard_selector.py`, `patterns/coin_patterns.py` | pattern tests | Needs more real per-coin samples | Medium | Add import reports |
| Execution quality | Partial | `leaderboard_selector.py` | copy mode tests | Maker/taker quality needs more fill samples | Medium | Expand fills metrics |
| Sample confidence | Delivered | scoring and leaderboard modules | scoring tests | None | High | Keep minimums |
| Copyability | Delivered | `leaderboard_selector.py` | copy mode tests | More calibration | Medium | Backtest calibration |
| Delta detector | Delivered | `copy_mode/delta_detector.py` | copy mode tests | Flip remains UNKNOWN by design | High | Add future flip model only if safe |
| SignalCandidate | Delivered | `copy_mode/signal_candidate.py` | copy mode and network read tests | None | High | Add more market context |
| `edge_remaining_bps` obligatoire | Delivered | `copy_mode/edge.py`, `signal_candidate.py` | copy mode tests | None | Critical | Keep fail-closed |
| no_trade_report | Delivered | `copy_mode/no_trade_report.py` | copy mode tests | More French templates possible | High | Add per-component details |
| leaderboard_shortlist.json | Delivered | `copy_loop.py`, `leaderboard_selector.py` | copy mode tests | Runtime file is not archived | High | Keep in data/ |
| Position/fill/openOrders snapshots | Delivered | `copy_mode/snapshot_engine.py`, `schema.sql` | network read tests | More order fields can be normalized | High | Add historicalOrders snapshot |
| Resume cursor userFillsByTime | Delivered | `snapshot_engine.py`, `info_client.py` | API limit tests | Cursor persistence is simple | Medium | Add resume table per wallet |
| Dedupe hash/tid/oid/time | Delivered | `snapshot_engine.py`, `fill_dedupe` | network read tests | None | High | Keep deterministic |
| Source health / collection_runs / api_health | Delivered | `snapshot_engine.py`, `schema.sql` | network read tests | api_health is basic | Medium | Add CLI status view |
| WebSocket shortlist read-only | Delivered as bounded planner/mockable manager | `realtime_monitor/` | WS tests | Real connection remains explicit only | High | Add transport integration tests |
| Max 10 users uniques | Delivered | `subscriptions.py`, `websocket_manager.py` | WS limit tests | None | Critical | Keep strict |
| Duration limitee / no infinite monitor | Delivered | `websocket_manager.py`, CLI | WS tests | None | Critical | Keep strict |
| Replay/backtest depuis deltas historiques | Partial delivered | `backtesting/`, `copy_mode/repository.py` | backtest tests | More direct delta-to-trade scenarios needed | High | Expand replay engine |
| 5m / 60s / WS delay scenarios | Partial | `backtesting/execution_delay_model.py` | backtest tests | CLI scenario selector can be richer | Medium | Add scenario flags |
| Missed/partial fills | Partial | `backtesting/`, paper models | backtest tests | Needs more fixtures | Medium | Add L2/slippage fixtures |
| Paper mock USDC portfolio | Delivered | `paper_trading/`, dashboard | paper tests | None | High | Keep local only |
| Dashboard copy status / activity / no-trade / edge | Delivered | `dashboard/exporter.py` | dashboard tests | More CSV exports possible | High | Add richer CSV |
| Safety audit | Delivered | `audit/`, CLI | audit tests | Deep report generated as doc | Critical | Keep scanning |
| Batch 6 testnet locked only | Delivered locked | `testnet_exchange_client.py`, docs | safety tests | No executor active | Critical | Future sprint only |
