# HyperSmart Multi-Wallet Follow Simulation

Local historical replay only. This is not a trading signal, not an order, and historical performance is not future profit.

- scenario: `multi_wallet_follow_closed_pnl`
- requested_wallets: 2
- simulated_wallets: 0
- notional_per_trade: 50.00
- delay_seconds: 300.00
- total_usable_trades: 0
- total_skipped_actions: 0
- gross_pnl: 0.0000
- total_costs: 0.0000
- net_pnl: 0.0000
- max_drawdown: 0.0000

## Wallets

| Wallet | Usable | Skipped | Gross | Costs | Net | Winrate | Max DD | Warnings |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `0x1111111111111111111111111111111111111111` | 0 | 0 | 0.0000 | 0.0000 | 0.0000 |  | 0.0000 | insufficient closedPnl/price/size data for replay |
| `0x2222222222222222222222222222222222222222` | 0 | 0 | 0.0000 | 0.0000 | 0.0000 |  | 0.0000 | insufficient closedPnl/price/size data for replay |

## Warnings

- 0x1111111111111111111111111111111111111111: no usable closedPnl points
- 0x2222222222222222222222222222222222222222: no usable closedPnl points
