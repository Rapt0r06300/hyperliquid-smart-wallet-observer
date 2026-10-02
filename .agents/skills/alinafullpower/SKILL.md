---
name: alinafullpower
description: Use when a clearly authorized Alina Smart Flow implementation, repair, completion, or long-running GitHub task must be carried through to a verified terminal state without premature stopping, repeated dead ends, scope drift, or false DONE claims.
---

# Alina Full Power

## Mission contract

At entry, derive a private completion contract: exact objective, explicit exclusions, files/systems likely affected, required proof, and remaining work. The canonical repository is `Rapt0r06300/hyperliquid-smart-wallet-observer`, branch `main`; the canonical design is `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`.

A user authorization to implement/repair/finish is authorization to continue the whole feasible mission. Do not stop to ask permission between already-authorized steps.

## Terminal loop

Repeat until no requested feasible work remains:

1. **STATE** — read current HEAD and only the relevant files/delta.
2. **WORK** — make the smallest complete functional change.
3. **VERIFY** — run the cheapest deterministic proof that can falsify it.
4. **REMAINING** — recompute the gap against the completion contract.
5. If remaining work exists, immediately return to WORK.

Reading, planning, commentary, an empty commit, or a test-only change is not progress when runtime behavior is still missing.

Before final response, ask internally: **Is any requested, feasible, unblocked work still undone?** If yes, continue.

## Progress proof

Count progress only when at least one verifiable artifact exists: real diff, changed runtime behavior, passing deterministic test, replay/backtest result, validated data artifact, measurable economic result, or corrected wiring.

For every GitHub write:
- re-read the target file/ref before replacing it;
- tolerate concurrent bot commits by refreshing state and reapplying the minimal patch;
- verify final HEAD;
- verify changed files/diff against the parent;
- never count or report an empty commit as saved work.

Prefer implementation over documentation. Tests prove behavior; they do not substitute for missing behavior.

## Blockage watchdog and self-recovery

Treat any of these as a blockage signal: same failure twice, repeated identical tool calls, no new artifact after several operations, stale assumptions after HEAD moved, research without implementation, or a patch that produces no diff.

Recovery protocol:
1. snapshot the last verified HEAD, changed files, successful proofs, failure and remaining queue;
2. classify the blocker: code/test, stale Git state, tool/API, permission/auth, external service, missing evidence, or context loss;
3. after two same failures, abandon that method;
4. choose a materially different route: narrower reproduction, direct file/API read, deterministic script, alternate existing code path, smaller patch, or independent task;
5. reload authoritative state and continue;
6. while one item is blocked, finish every independent feasible item.

Never loop indefinitely. Never claim asynchronous/background work. A skill cannot revive a platform-terminated session; on the next invocation, resume from authoritative Git state and the checkpoint rather than trusting prose memory.

Only stop on a genuine external/platform/safety blocker after exhausting independent work. Report exact verified state, blocker, completed work, remaining work, and next executable action.

## Scope and architecture locks

Default to one main agent. Do not create swarms/subagents unless explicitly requested.

Modify existing architecture before adding a parallel system. Do not create V2/V3/spec copies merely to avoid editing canonical files. Preserve compatibility and minimize duplication.

Dynamic user exclusions override defaults. In particular, if CI is postponed, do not spend the mission on CI; if Carry is excluded, do not create a Carry strategy.

Never touch, wake, depend on, or create automation for the user's PC. Cloud automation is GitHub-hosted only. Never create a self-hosted runner.

Alina is strictly paper/read-only: no private keys, signing, deposits/withdrawals, real orders, or real transactions.

## Deterministic-first budget

Use model reasoning only where it changes a technical decision. Prefer, in order: existing Python/scripts, structured JSON/JSONL/CSV, grep/search, checksums/manifests/receipts, targeted tests, replays, backtests, calculations, then GitHub-hosted validation when it is in scope.

Do not repeatedly rescan the repository. Read the relevant delta and reuse established state.

External research is conditional: use it only when a real unknown blocks progress or a new economic hypothesis needs evidence. Convert research into a falsifiable hypothesis and then into code/replay/backtest; do not stop at research notes.

## Economic fail-closed ladder

Never collapse these states:
`IMPLEMENTED -> WIRED -> TESTED -> REPLAYED -> BACKTESTED -> OOS/FORWARD_VALIDATED -> ECONOMICALLY_PROVEN`.

The target of +4 USD NET/day per canonical family is a measurement target, never a result to force. Include fees, spread, slippage, latency, depth/capacity and closed-cycle/position evidence as applicable. Missing required evidence means UNMEASURABLE/NOT_PROVEN, not zero-cost or assumed success.

Avoid overfitting: fixed/predeclared search spaces, all tried variants counted, TRAIN-only selection, disjoint OOS/forward proof, multiple-testing control where applicable, and no retuning on held-out evidence without refreezing and collecting new proof.

For Cross-Venue, missing synchronization/transport/depth evidence must fail closed. For Lead-Lag, preserve causal timing and measured execution evidence. For Copy-Vault, preserve observed leader lifecycle, leader-exit handling and observed-book execution evidence.

## Drift detector

Periodically compare current operations with the mission contract. If work has drifted into old roadmaps, cosmetic cleanup, unrelated CI, documentation, duplicate architecture, or tests that do not unlock requested behavior, return to the highest-value unfinished functional item.

Maintain a private dependency queue. Work blockers first only when they gate many downstream items; otherwise finish independent items in parallel sequence (single agent, no swarm).

## Context recovery

After interruption or context loss:
1. fetch current `main` HEAD;
2. read the canonical spec sections relevant to the mission;
3. inspect commits/diffs since the last verified SHA;
4. inspect only relevant current files and test/replay artifacts;
5. reconstruct completed vs remaining work from evidence;
6. resume the terminal loop without asking the user to restate already-recoverable context.

## Final response gate

Do not say DONE/terminé unless the result exists and was concretely verified. Final response should be concise and contain only: what is actually completed, verification evidence (including final SHA when GitHub changed), what remains, and any exact blocker.

**Central rule:** ALINAFULLPOWER does not maximize elapsed work time. It maximizes useful, verified work completed before returning control.
