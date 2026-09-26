---
name: alina-quota-minimal
description: Use for Alina coding, research, testing, replay, or backtest work where model quota and GitHub Actions usage must be minimized.
---

# Alina Quota-Minimal Execution

Use one LLM controller. Never spawn a second LLM, subagent, swarm, debate agent, or reviewer agent unless the user explicitly changes policy.

Preferred cadence:

`1 model decision -> largest safe deterministic batch -> compact summary -> next model decision`

Prefer exact-file reads, diffs, manifests, machine summaries, and scripts over whole-repository rescans or giant logs.

When the user explicitly starts Codex or another coding agent in a local checkout, run deterministic work locally as much as practical: tests, lint, type/static checks, replay, backtests, bootstrap/permutation/Monte-Carlo, profiling, aggregation, fixtures, and data validation.

Local means user-initiated. Never wake or remotely use the user's PC and never configure a self-hosted runner.

Use GitHub-hosted Actions for cloud-native collectors/orchestration, essential integration/release gates, or checks that cannot be established adequately on the current local tree. Avoid duplicate CI for an identical tree without a material reason.
