# HyperSmart Architecture Reconciliation

Date: 2026-05-26

Status: factual reconciliation after archive/content mismatch.

## Decision

`hyper_smart_observer` is the official package for the current HyperSmart
Observer CLI, archive/runtime hygiene, research-only copy mode, dashboard,
audit, local paper mock USDC simulation, and `/info` read-only pipeline.

`src/hl_observer` remains a legacy/parallel codebase. It contains useful older
modules and UI experiments, but it is not the official command surface for the
current HyperSmart delivery. It must not be deleted or reset. Future work may
pull specific implementations into `hyper_smart_observer` through explicit
adapters and tests.

Official CLI:

```powershell
python -m hyper_smart_observer.app.main
```

## Reconciliation Table

| Function | Present in `hyper_smart_observer`? | Present in `src/hl_observer`? | Version to keep | Action |
|---|---:|---:|---|---|
| Copy mode | Yes: `copy_mode/` with copy loop, detector, edge, reports, preflight | Yes: legacy copy/following modules | `hyper_smart_observer` | Keep official copy mode here; treat legacy modules as reference only. |
| Preflight | Yes: `copy_mode/preflight.py`, CLI `copy-preflight` | No official equivalent | `hyper_smart_observer` | Keep and extend with real shortlist/network readiness checks. |
| Leaderboard/import | Yes: `leaderboard_selector.py`, `candidate_importer.py` | Yes: many leaderboard import/browser modules | `hyper_smart_observer` | Keep safe importer; integrate selected legacy parsing later behind tests. |
| REST `/info` | Yes: read-only `hyperliquid_client/info_client.py` | Yes: `hyperliquid/rest_info_client.py` | `hyper_smart_observer` | Official client stays `/info` only; no `/exchange`. |
| WebSocket | Yes: read-only monitor modules and limit tests | Yes: UI/WS legacy modules | `hyper_smart_observer` | Keep read-only shortlist WS; legacy code can inform future adapters. |
| Delta detector | Yes: `copy_mode/delta_detector.py` plus position lifecycle | Yes: signal/position delta modules | `hyper_smart_observer` | Keep official action taxonomy here; import no untested legacy behavior. |
| Edge remaining | Yes: `copy_mode/edge.py`, `signal_candidate.py` | Partial/legacy risk models | `hyper_smart_observer` | Keep mandatory `edge_remaining_bps`; no accepted candidate without it. |
| No-trade report | Yes: `copy_mode/no_trade_report.py`, DB/report exports | Partial via legacy risk/report paths | `hyper_smart_observer` | Keep official refusal log/report here; dashboard reads these tables. |
| Paper executor | Yes: `paper_trading/`, local paper mock USDC only | Yes: paper/follow modules | `hyper_smart_observer` | Keep local-only paper path; legacy execution-like code remains non-official. |
| Backtest | Yes: `backtesting/` replay/report modules | Partial legacy analysis | `hyper_smart_observer` | Keep local replay only; no execution, no promise of future profit. |
| Dashboard | Yes: `dashboard/`, export HTML/CSV read-only | Yes: richer legacy UI modules | `hyper_smart_observer` | Keep official read-only export; consider legacy UI only after safety audit. |
| Archive clean | Yes: `tools/create_clean_archive.*`, root button | No official equivalent | `hyper_smart_observer` plus root/tools | Keep current clean archive flow; output is Desktop only. |
| Safety audit | Yes: `audit/`, CLI `--audit-safety` | Yes: legacy safety scanner | `hyper_smart_observer` | Keep official audit here; scan legacy code as an input, not as command surface. |

## Integration Rule

No module from `src/hl_observer` becomes official merely because it exists.
Integration requires:

- an adapter or direct implementation inside `hyper_smart_observer`;
- tests under `tests/test_hypersmart_*.py`;
- safety audit coverage;
- no mainnet, no `/exchange`, no signature, no private key, no order;
- documentation in the HyperSmart docs.

## Archive Implication

The clean archive may include both `hyper_smart_observer/` and `src/` as source
code, but the release documentation and CLI identify `hyper_smart_observer` as
the official package. Runtime folders, logs, databases, caches and archives are
excluded.
