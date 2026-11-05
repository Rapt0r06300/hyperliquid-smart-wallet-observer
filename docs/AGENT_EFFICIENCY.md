# Local agent-efficiency layer

This layer reduces repository re-reading and redundant verification without
changing the Copy-Vault runtime, economic scope, or paper/read-only gates.

## What is implemented

1. `repo_index.py` keeps a hashable incremental index of tracked source files.
2. `context_bundle.py` compiles only ranked, budgeted file excerpts.
3. `output_compactor.py` compresses repetitive tool output while preserving the
   original digest and omitted line ranges.
4. `test_impact.py` selects affected tests and falls back to the full suite when
   the dependency evidence is uncertain.
5. `model_routing.py` chooses a bounded FAST/REVIEW/DEEP execution policy; it
   does not call a model or change provider settings.
6. `loop_guard.py` stops repeated no-progress actions and avoids rerunning a
   passing test when its source fingerprint is unchanged.
7. `parallel_reads.py` parallelizes bounded read-only file reads inside the
   repository root.
8. `experience_memory.py` stores append-only, local, reusable engineering
   outcomes and retrieves only high-overlap records.
9. `telemetry.py` emits deterministic, provider-neutral efficiency receipts.
10. `prompt_cache.py` builds stable prefixes and cache keys from policy, tools,
    model family, and repository fingerprint.

## Usage

```powershell
py -3 tools/agent_efficiency_plan.py `
  --task "fix the incremental repository index" `
  --changed src/hl_observer/agent_tools/efficiency/repo_index.py
```

The command is local-only and reports a JSON plan containing the index
fingerprint, bounded context, impacted tests, routing tier, and receipt hash.
The index is stored under `runtime/agent_efficiency/`, which is intentionally
ignored by Git because it is a regenerated cache.

`tools/codex_research_context.py` also accepts `--task`, `--changed`,
`--context-budget`, and `--repo-index` to add a bounded code context to its
existing research pack.

The layer never fabricates evidence, treats missing data as success, enables
execution, accesses external services, or changes SAFE data.
