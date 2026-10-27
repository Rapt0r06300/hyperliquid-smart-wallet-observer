# Alina Smart Flow — Copy-Vault research and simulation

> A read-only collection, replay, and paper-simulation project. The repository does not claim proven profitability merely because a positive backtest exists.

## Current mission

**Copy-Vault is the only active economic family.** The work collects public leader/vault events and associated market conditions, reconstructs causal events, then searches for and evaluates copy policies with realistic costs. Other families, including arbitrage, Lead-Lag, Cross-Venue, Carry, market-making, and 3x4, are outside the active scope.

The terminal research objective is **at least $5 net per day on $200 paper capital**, evaluated after technical repairs, quality checks, replay/backtest, OOS, and forward-paper evidence. This is a target, not a forecast or guarantee.

## Operator workflow

- `LANCER_COLLECTEURS_COPY_VAULT.cmd`: runs the Copy-Vault collectors.
- AlinaSync, exposed through `ALINA_SYNC_COMPLETE.cmd`: downloads/restores published SAFE shards and verifies size, SHA-256, and receipts.
- `LANCER_LAB_QUANT_COPY_VAULT.cmd`: uses SAFE shards for backtests and replays and preserves every experiment/candidate, including provisional or weaker results.
- Support launchers live in `tools/launchers/`; only the four main launchers and AlinaSync remain at the repository root.
- `LANCER_HYPERSMART.cmd`: runs the engine with a visible paper simulation; it must enforce Copy-Vault scope.
- `POUSSER-GITHUB-FORCE.cmd`: reconciles and publishes Git code without force. It does not transfer shards.

These filenames record the intended operator roles; their names alone do not certify their actual wiring. The code at HEAD and its receipts are authoritative.

## Method and proof criteria

Candidates are compared across consistent windows and capital limits, with parameters, data identity/hashes, seeds, costs, and results retained. Every improvement remains inspectable when a later one supersedes it. Costs, fills, timestamps, and PnL are never fabricated; missing or uncertain data remains unknown and may make a result `UNMEASURABLE`.

The canonical chain is `IDLE → COLLECT → ANALYZE`, then `DRAIN → QUALITY → REPLAY → BACKTEST → OOS → FORWARD_PAPER → PNL_PROOF → SCOREBOARD → DONE`. Only causal, reproducible results that pass their corresponding gates may be called `PROVEN`. Other honest verdicts are `PROMISING`, `MORE_DATA`, `UNMEASURABLE`, and `REJECTED`.

## Safety

**PAPER / READ-ONLY / FAIL-CLOSED**: no mainnet or testnet orders, signatures, private keys, seeds, deposits, withdrawals, or transfers. A simulation is not execution.

## Historical research notes

Older reports and summaries may include results for general copy-trading, arbitrage, grids, market-making, or other families. They are retained as history; they do not describe the active scope, current status, or current Copy-Vault economic proof. Verify their source artifacts before citing or comparing them.


### Values copied from the previous summary — unverified history

The figures below are retained from the former portfolio document as historical notes. They do not describe the current active strategy and must be matched to source artifacts before reuse.

| Older study | Result stated in the former summary |
|---|---|
| General copy-trading | About 13 bps copy degradation; median edge reported as negative. |
| SL/TP calibration | About 1.4 million scenarios; no robust out-of-sample setting reported. |
| Maker entry | 16% fill rate reported, with adverse selection. |
| Grid / market-making | Breakeven reported in calm markets and large losses during trends. |
| Mean reversion | Raw edge reported at about 0.6 bps, below costs. |
| Random control | 0 positive strategies out of 50 random trials, according to the former summary. |
| Oracle exit | Theoretical ceiling reported at +$50k and explicitly described as unrealizable. |
| Predictive model | Signal reported as about 15 times too weak and subject to regime shifts. |
