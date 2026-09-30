# H—T-37 — Data truth / Hyperliquid transport / provenance completion

Status: **TECHNICALLY COMPLETE / READY FOR REVIEW**  
Scope: V5 §6 + P0-010 / P0-100 / P0-105.  
Done is technical only; no financial target is a completion gate.

## Canonical evidence map

| Requirement | State | Evidence |
| --- | --- | --- |
| Unified Event Contract | IMPLEMENTED | `src/hl_observer/data_contract/unified_event.py` defines venue/source/symbol/event type, exchange/receive/write clocks, monotonic receive clock, event/connection IDs, sequence, schema version and raw evidence reference |
| Snapshot vs economic delta | IMPLEMENTED + TESTED | INITIAL/BBO/L2 snapshots cannot create economic deltas; covered by `tests/test_v5_unified_event_data_quality.py` |
| Reconnect / restart idempotence | IMPLEMENTED + TESTED | `EventReplayGuard` dedupe key is independent of connection ID; reconnect and restart duplicates are rejected; `tests/test_master_repair_realtime_truth.py` also exercises snapshot reconnect idempotence |
| Sequence / gap / out-of-order | IMPLEMENTED + FAIL-CLOSED | sequence gap requires explicit reconciliation; out-of-order events are rejected without advancing state |
| Clock contract / missing timestamps | IMPLEMENTED + FAIL-CLOSED | exchange, receive-wall, receive-monotonic and write clocks are explicit non-negative integers; missing timestamps are rejected instead of replaced with `now` |
| Data Quality Gate | IMPLEMENTED + TESTED | V5 data-quality contract distinguishes PASS / BLIND / CONFLICTED / STALE / INCOMPLETE and refuses tradeability when required evidence is missing |
| Freshness / clock skew / coverage | IMPLEMENTED + TESTED | freshness, max freshness, clock skew, completeness, duplicate/gap counts, symbol mapping, days/coins/wallet-vault coverage are explicit inputs; unknown coverage is BLIND, not silently zero |
| Source provenance | IMPLEMENTED + FAIL-CLOSED | UnifiedEvent requires `source` and `raw_evidence_ref`; data-quality gate refuses missing source provenance |
| Pagination / caps | IMPLEMENTED + TESTED | `src/hl_observer/hyperliquid/info_readonly.py` exposes bounded pagination; `src/hl_observer/hyperliquid/pagination_completeness.py` makes natural completion vs truncation observable; `tests/test_pagination_completeness.py` covers completion/truncation semantics |
| Hyperliquid `/info` contract | IMPLEMENTED | `docs/HYPERLIQUID_API_CONTRACT_CURRENT.md`, `info_readonly.py` and current clients keep read-only request/response/pagination behavior explicit |
| WebSocket provenance / reconnect | IMPLEMENTED + TESTED | `WsSupervisor` is covered by V9/V12 WS supervisor tests including provenance; reconnect/idempotence is covered by realtime-truth tests |
| Runtime-mode / missing-value integrity | IMPLEMENTED | missing data is represented as missing/blind/unmeasurable rather than fabricated; snapshot state is separated from economic deltas |
| Decision / refusal observability | IMPLEMENTED BY CONTRACT | replay decisions carry explicit accepted/reason/gap/out-of-order state; data-quality reports expose state/reasons/tradeability |
| Parallel architecture | NOT INTRODUCED | existing Hyperliquid read-only collectors/WS supervisor and the canonical V5 event/data-quality contracts are reused |

## Positive and negative contracts

`tests/test_v5_unified_event_data_quality.py` proves both happy-path and fail-closed behavior for:

- complete canonical event schema;
- snapshot non-economic semantics;
- reconnect/restart duplicate rejection;
- sequence-gap reconciliation requirement;
- out-of-order rejection;
- missing timestamp rejection;
- full-quality PASS;
- missing provenance => BLIND/non-tradeable;
- clock conflict, stale evidence and incomplete coverage as distinct states;
- unknown coverage => BLIND rather than a fabricated zero.

Pagination completeness and realtime reconnect tests add independent transport-level coverage.

## Verification boundary

The repository-wide 32-shard pytest matrix completed all test shards successfully at `4c6152f8e3c97d2fe44bdcba6a4deabc29ef3f9c`. Changes after that point up to this receipt are limited to Task Graph hardening, coverage workflow discovery and documentation maps; the data-contract/Hyperliquid transport surfaces above were not relaxed.

External data availability, rate limits or future market observations are runtime evidence concerns and are not unfinished implementation. When those inputs are absent/stale/incomplete, the canonical behavior is to fail closed or report BLIND/STALE/INCOMPLETE.

## Completion decision

All H—T-37 acceptance criteria are satisfied. Technical scope is complete without using PnL as a gate.
