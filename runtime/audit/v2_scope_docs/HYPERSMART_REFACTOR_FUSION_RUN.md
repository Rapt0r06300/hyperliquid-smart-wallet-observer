# HyperSmart refactor fusion run

Scope: runtime actif `src/hl_observer`, simulation locale paper only.

## PnL audit

- Logs: `logs\logs à envoyer`
- PnL net effectif: 0.000000 USDC
- Protection mode: false

## Wallet mirror E2E

- HYPE LONG: accepted=True paper_intent=True edge=62.4 reasons=OK
  - Entry cost guard: accepted=True min_notional=25.0 min_edge=0.0 observed_notional=67.5 observed_edge=62.4 reasons=OK

## Arbitrage cross-source E2E

- HYPE: decision=ACCEPT_PAPER_ARBITRAGE net_edge=128.0 funding_adjusted=128.0 reasons=OK

## Dashboard payload

- `runtime\audit\v2_scope\refactor_fusion_dashboard_payload.json`

## Safety

- paper_only=true
- real_execution=false
- external_order=false
- signature=false
- private_key=false
- fixtures are labeled as fixtures when live source is absent.

## Multi-leader / risk / replay

- Conflict resolver: FOLLOW side=LONG reasons=OK
- Liquidity cliff: blocked=False reason=OK
- Concentration: blocked=False share=0.4
- Replay paper PnL: 0.809646 USDT on 1 fixture trade(s)
- Dual venue hedge: accepted=True reason=ACCEPT_PAPER_HEDGE real_execution=False

## Secondary ports

- Copy session: RUNNING, watchlist=2, paper_only=True
- Latency profile: p50=2450ms, stale=1/4
- Paper connector: accepted=True, id=paper:09c3541acdeda94a621ced39, real_execution=False
- Funding signals: 1
- WS price discrepancies: 1
- Triangular opportunities: 2
- Fusion runtime paper orders: 1, no-trades=7
