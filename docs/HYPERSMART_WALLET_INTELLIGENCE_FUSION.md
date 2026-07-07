# HyperSmart Wallet Intelligence Fusion

## Objectif

Classer les wallets selon competence apparente, robustesse et copyability sans
confondre chance, concentration de PnL ou activite stale avec un signal.

## Source GitHub inspiratrice

MrFadiAi Polymarket-bot pour filters, Awesome Prediction Market Tools pour
labels, CloddsBot pour whale/copy tracking, polybot pour replication scoring
en DEFER.

## Adaptation Hyperliquid

Metrics:

```text
closed_trade_count
realized_pnl
unrealized_pnl when available
winrate
profit_factor
max_drawdown
consistency_score
one_big_win_ratio
pnl_concentration
recent_activity
wallet_age/activity
copyability_score
smart flag
whale flag
suspicious flag
fresh flag
data_quality_score
```

Shortlist exclusions: insufficient history, one-big-win, PnL overconcentration,
stale wallet, degraded source. Only top wallets can enter WS hot watch.

## Modules cibles

- `hyper_smart_observer/scoring/*`
- `hyper_smart_observer/wallet_discovery/*`
- `src/hl_observer/wallets/*`
- `hyper_smart_observer/copy_mode/leaderboard_selector.py`

## Donnees Hyperliquid utilisees

`userFillsByTime`, `userFills`, `clearinghouseState`, `openOrders` as context
only, `allMids` for mark/reference context.

## Tests requis

- `test_hypersmart_anti_luck_filters.py`
- `test_hypersmart_wallet_intelligence.py`
- `test_scanner_rest_broad_scan_to_shortlist.py`
- `test_scanner_ws_shortlist_max_10_users.py`

## Statut DONE / PARTIAL / TODO / DEFER / BAN

PARTIAL. Existing scoring and discovery modules cover many metrics; WalletScoreV2
as a named consolidated facade remains TODO.

