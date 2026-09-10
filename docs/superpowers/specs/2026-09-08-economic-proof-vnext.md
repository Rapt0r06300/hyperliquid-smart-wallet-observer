# Economic Proof VNext Design

## Objective

Prove independently for `copy_vault`, `lead_lag` (Cross-Venue), and
`cross_venue_dislocation_v2` (Arbitrage) that liquidatable net PnL is at least
4 USD on every proof day. PnL may never be aggregated across families.

## Evidence contract

- Every proof uses observed, causal prices and explicit fee, spread, slippage,
  latency, and capacity receipts.
- Selection uses TRAIN only. Validation is evaluated after selection. OOS stays
  unopened until the mechanism and parameters are frozen. Forward evidence is
  strictly post-freeze.
- Daily success means `min(daily_net_pnl_usd) >= 4.0`, with at least two proof
  days and liquidatable closed positions on every included day.
- Scaling notional cannot rescue a mechanism whose executable edge is negative
  or whose observed capacity cannot support the size.
- A duplicated checkpoint makes its entire Copy-Vault metaorder ineligible.
- Paper/read-only only: zero real orders, money, private keys, signatures,
  deposits, or withdrawals.

## Copy-Vault design

Elect exactly one checkpoint writer. The campaign companion owns bound
`REFERENCE`, `ENTRY`, and `EXIT_*` checkpoints because it persists pending work
across restarts. `userfills-live` continues collecting fills and unbound WS L2
samples but does not schedule or append bound checkpoints while the companion
protocol is enabled. An exclusive owner marker fails closed if a second writer
attempts to start.

The book loader performs a complete checkpoint-ID census before admitting
checkpoint rows. If any ID occurs more than once, every bound row for that
metaorder is quarantined. The audit reports duplicate IDs, duplicate physical
rows, quarantined metaorders, and quarantined rows. The replay never silently
chooses one price from duplicate receipts.

After the clean epoch, the 1-hour wallet-identity challenger is selected using
TRAIN-only shrinkage and minimum observation requirements. It must pass
validation across independent days and held-out wallets before OOS is opened.

## Cross-Venue design

Simple TFI continuation, the prior multiasset grids, and an L2-only maker proof
are killed hypotheses. The next bounded study may combine divergence, returns,
book imbalance, trade-flow imbalance, volatility, and liquidity in a nonlinear
TRAIN-only model. Every selected trade must clear the measured 9-bps taker fee
hurdle plus observed spread and latency costs before validation is opened.

## Arbitrage design

The existing frozen basis-convergence mechanism remains killed. Build a
two-tier atomic BBO universe: the current full-channel core plus BBO-only extras
selected from TRAIN liquidity, frozen before validation. Re-estimate executable
opportunity multiplicity and only formulate a new mechanism if the expanded
universe produces enough positive two-leg edges after all costs.

