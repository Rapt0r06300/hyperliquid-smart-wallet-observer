---
name: alina-cross-venue
description: Use for Alina Cross-Venue Dislocation research, executable spread checks, two-leg paper execution, depth/VWAP, capacity, or convergence validation.
---

# Alina Cross-Venue

A midpoint gap is not an opportunity. Require synchronized fresh BBO, L2 depth on both legs, side-correct executable prices, VWAP for the tested notional, venue fees, slippage, latency, tick/lot/min-notional rules, collateral/capital usage, and exit/convergence economics.

Use same-runner receive ordering where feasible. Preserve venue-specific clock uncertainty and instrument identity.

Model both entry and exit legs. Include funding/carry when the holding interval can cross settlement. Reject or mark UNMEASURABLE when either leg lacks required executable evidence.

Do not revive taker-taker or any killed configuration merely because a raw spread is positive; require materially new preregistered evidence.

Paper/read-only only.
