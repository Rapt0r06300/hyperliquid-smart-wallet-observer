# H—T-38 — Paper execution / accounting / microstructure completion

Status: **TECHNICALLY COMPLETE / READY FOR REVIEW**  
Scope: V5 §§7→8 + P0-070 / P0-080 / P0-090.  
Done is technical only; no target PnL is required.

## Canonical execution chain

The strict paper path is shared rather than duplicated:

`ExecutionTruth` → `CausalMarketSnapshot` → `PaperExecutionIntent` → `execute_paper_intent` → position/accounting events.

`PaperSimConnector`, `PaperEngine`, Cross-Venue paper execution and executable replay consume the same execution-truth primitives instead of inventing independent fill logic.

## Requirement map

| Requirement | State | Canonical evidence |
| --- | --- | --- |
| PAPER-only canonical pipeline | IMPLEMENTED + TESTED | `paper_trading/canonical_execution.py`, `paper_connector.py`, `paper_engine.py`, `tests/test_canonical_paper_execution_v2.py` |
| Executable bid/ask and causal L2 | IMPLEMENTED + FAIL-CLOSED | `execution_truth.py`; strict execution requires observed fresh L2, valid two-sided book and snapshot identity |
| Taker depth consumption | IMPLEMENTED + TESTED | `exec_model.py`, `liquidity_consumption.py`, `tests/test_liquidity_consumption_ledger_v2.py`; taker fills walk observed book levels |
| Partial/missed fills | IMPLEMENTED + TESTED | requested/filled/missed notional and fill ratio are first-class; insufficient depth remains partial/missed rather than fabricated |
| Fees / spread / depth slippage | IMPLEMENTED | execution result and executable replay carry measured/explicit cost components; absent strict evidence becomes UNMEASURABLE |
| Latency | IMPLEMENTED | scalar latency is stress-only; causal mode does not double count latency already embedded in the causal book |
| Maker / queue | IMPLEMENTED WITH MEASURABILITY GATE | maker fills require observed queue depletion or traded-through evidence; no queue evidence means no strict maker proof |
| Reality/stress separation | IMPLEMENTED | strict `ExecutionTruth` path is authoritative; approximate scalar models are explicitly labelled approximate/stress and cannot be promoted as strict PnL |
| Liquidity consumption ledger | IMPLEMENTED + TESTED | shared ledger prevents silent reuse/double consumption of the same executable depth |
| Accounting | IMPLEMENTED + TESTED | canonical execution emits explicit position mutation and equity/accounting events; realized PnL stays pending until position accounting owns it |
| Cross-module consistency | IMPLEMENTED + TESTED | canonical test proves direct core, connector and main PaperEngine resolve to the same fill truth |
| Markouts / adverse selection | IMPLEMENTED + TESTED | `market_truth/executable_replay.py`, causal markout helpers and `tests/test_market_truth_pipeline.py` / P0 execution-ledger tests |
| Staleness / refresh | IMPLEMENTED + FAIL-CLOSED | stale execution books return no fill with `STALE_EXECUTION_BOOK` / UNMEASURABLE; missing strict book returns `NO_LIVE_EXECUTABLE_BOOK` |
| Capacity / dynamic depth | IMPLEMENTED | execution capacity is constrained by actual observed book levels and filled notional; capacity cannot exceed consumable depth |
| Slicing / throughput | IMPLEMENTED AS EXECUTION POLICY / DIAGNOSTIC | execution-realism and guardrail tooling preserve per-slice fills/cost propagation and throughput/capacity diagnostics; no real-order endpoint is introduced |
| Inventory / tilt / hedge policy / fill-to-hedge | IMPLEMENTED IN PAPER/DIAGNOSTIC LAYER | paper position lifecycle, risk/hedge policies and execution-realism diagnostics consume canonical fills; none may bypass PAPER scope or strict execution evidence |

## Fail-closed invariants

`exec_model.py` explicitly states and implements:

- strict execution consumes a causal `ExecutionTruth` and never invents liquidity;
- taker orders walk the observed book;
- maker fills require queue depletion or traded-through evidence;
- strict paper with no live executable book is refused as UNMEASURABLE;
- stale books are refused;
- requested and filled notionals are separate;
- approximate depth/cost logic is not authoritative strict evidence.

`tests/test_canonical_paper_execution_v2.py` additionally proves the canonical core, connector and engine share the same fill price/notional/evidence, preventing silent replay/paper divergence and duplicate accounting semantics.

## Verification boundary

At `4c6152f8e3c97d2fe44bdcba6a4deabc29ef3f9c`, all 32 pytest shards completed successfully after the last structural split of oversized backtesting files. The only aggregate red was repository-wide coverage percentage, tracked by H—T-50/H—T-21. No subsequent commit before this receipt relaxes the canonical paper-execution or market-truth contracts.

## Completion decision

All H—T-38 acceptance criteria are satisfied. Maker/queue remains admissible only when measurable; lack of such evidence is a runtime UNMEASURABLE outcome, not an unfinished technical implementation. No financial-return target is used for Done.
