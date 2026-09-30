# Codex Discovery V3.2 — Compact Research Control Plane

## Status

Approved by the user on 2026-09-10. This design extends Discovery V3.1 without changing the three canonical economic families, the paper/read-only safety contract, or the final daily certification target.

## Goal

Maximize useful quantitative progress per Codex quota unit by moving deterministic context reconstruction, historical-memory retrieval, semantic candidate expansion, duplicate/failure filtering, trial accounting, and research-budget heuristics onto the local CPU. The LLM remains a single high-reasoning research controller that invents, selects and interprets; the PC performs the bulk of repeatable computation.

## Non-goals

- No new trading family.
- No replacement of the existing V3.1 hypothesis ledger.
- No real/testnet execution or weakening of economic/safety gates.
- No large new dependency stack; V3.2 must run with the existing Python 3.11 project dependencies and preferably the standard library for control-plane logic.
- No automatic claim that a discovered candidate is profitable. Search ranking is research prioritization only.

## Architecture

### 1. Compact `AGENTS.md`

`AGENTS.md` becomes a short router containing only authority order, economic target, safety invariants, one-command research resume, local-compute/quota rules, scientific proof invariants and Done. Detailed model families, search operators and discovery mechanics stay in the research skill/runbook and are loaded only when needed.

### 2. Historical research memory

Add `src/hl_observer/research/process_memory.py` with a compact append-only process-memory schema. Each record captures family, semantic mechanism signature, context, edit/change motif, outcome, evidence count, failure reason, success evidence, provenance and retest condition. Negative memory is asymmetric: repeated high-confidence failure patterns can veto an equivalent candidate; positive memory only adds a bounded soft boost.

Runtime path: `runtime/codex_research/PROCESS_MEMORY.jsonl`.

A versioned seed file, `docs/quant/HISTORICAL_EXPERIMENT_MEMORY.jsonl`, records only high-confidence historical lessons that are stable enough to prevent repeated mistakes. It is not economic proof and must never overwrite the append-only runtime ledger.

### 3. One-command context pack

Add `tools/codex_research_context.py`. It emits a compact JSON object from local files only. It must include exact HEAD if available, the selected/auto-selected family, hypothesis-ledger status, process-memory summaries, high-confidence veto motifs, recent useful experiments, research-trial totals, available data-surface hints, rediscovery/challenger state where derivable, and a small admissible-next-action set.

Default output is compact JSON to stdout; `--out` writes an artifact under `runtime/codex_research/`. It must not invoke network APIs or an LLM.

### 4. Semantic discovery engine

Add `src/hl_observer/research/semantic_discovery.py` plus `tools/codex_semantic_discovery.py`.

A semantic plan is a deterministic tuple over:

`event × context × data_surface × temporal_operator × regime × target × execution`

The engine can generate thousands of local combinations from a versioned component catalog, reject invalid combinations, deduplicate exact/near-semantic duplicates against the V3.1 hypothesis ledger/process memory, apply high-confidence negative vetoes, score under-covered regions, and return a diverse shortlist. The engine does not implement or backtest a strategy by itself.

### 5. Local research-priority scorer

V3.2 initially uses an explainable empirical scorer rather than adding LightGBM/scikit-learn dependencies. It estimates research priority from novelty, historical outcome evidence, archetype coverage, data feasibility, falsification cost and executable-headroom hints when present. After enough records exist, the score learns bounded empirical priors from process memory. The design deliberately leaves room for a future optional learned surrogate without making it a dependency now.

### 6. Trial/search accounting

Extend local control-plane summaries so every evaluated hypothesis/variant contributes to search-pressure accounting. The context pack must report at least total ledger trials, unique hypotheses, parameter-only trials when inferable, rejected/failed lineages and semantic candidates filtered before LLM realization. Final evidence remains disjoint from adaptive search feedback.

### 7. Retrieval and quota discipline

The default resume flow becomes:

`python tools/codex_research_context.py --auto`

Codex reads that compact pack first. It reads the detailed V3.2 discovery reference only on Discovery/Pivot/champion-challenger events. It must not rescan the full Git history, the 775 sealed optimizations or large raw logs merely to reconstruct state.

When Discovery is required, Codex may ask the semantic engine to produce a broad local pool (for example 1,000-20,000 plans) and receive only a small diverse shortlist for LLM review. Large deterministic candidate generation therefore costs CPU, not model turns.

## Scientific rules

- All adaptive search windows are feedback/train once observed.
- Every evaluated variant counts toward search intensity.
- Held-out/OOS/final forward evidence stays disjoint and is not used for retuning without invalidating its held-out status.
- Positive process memory is a soft prior only.
- High-confidence negative process memory can veto only when the candidate matches the failed mechanism/context closely enough and no documented retest condition is satisfied.
- A veto never prevents a retest justified by genuinely new data, a new surface, a materially different causal mechanism, or contradictory fresh evidence.
- Search scores are not economic certification.

## Safety

All new modules are offline/context-only. They must never create a paper intent, sign, route, submit or simulate a real exchange request. Existing `SECURITY.md`, `docs/HYPERSMART_CONSTITUTION.md` and machine gates retain higher authority.

## Success criteria

V3.2 is implemented when:

1. the compact context command runs locally and is deterministic enough for tests;
2. process memory validates, appends and applies asymmetric negative/positive evidence correctly;
3. semantic generation can create a broad pool locally and return a deterministic, diverse, deduplicated shortlist;
4. existing V3.1 ledger remains compatible;
5. `AGENTS.md`, runbook and skill route Codex through the context pack instead of repeated bootstrap scans;
6. regression tests lock quota, safety, no-network and scientific invariants;
7. the final economic objective remains unchanged: each canonical family must independently certify >= +4.00 USD NET/day under the machine gates of the exact HEAD.
