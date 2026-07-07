# HyperSmart V23 - Engine Conflict Resolution

| Conflict | Repos concerned | Existing HyperSmart files | Chosen final module | Decision |
|---|---|---|---|---|
| Raw copy vs license risk | GPL/AGPL/unknown repos | `docs/research/*` | behavior porting | No raw copy unless license is permissive and attribution/tests are added. |
| Fresh session PnL zero vs historical decision loss | runtime logs | `analysis/negative_pnl_auditor.py` | PnL truth mode | Expose both; use non-zero session snapshot first, then embedded decision cache, then decision files. |
| Copy-wallet entry vs overtrading | copy repos | `risk/risk_engine_v3.py`, `copy_wallet/*` | RiskEngineV3 gate | Entries require edge after costs; no PaperIntent on blocked risk. |
| Arbitrage source mismatch | arbitrage repos | `arbitrage/*` | paper opportunity only | No CEX execution; cross-source comparisons are research/paper. |
| Funding signal vs real hedge | funding repos | `funding/*` | funding paper signal | Funding E2E produces signal only, no hedge order. |
| Dashboard truth vs fixture examples | dashboard repos | `dashboard/*`, `refactor_fusion/runner.py` | source labels | Fixtures remain explicitly labeled and cannot be UI live truth. |

Safety boundary: Paper/local simulation only; `real_execution=false` for every conflict outcome; real external trading, wallet connect, private key, signature, live order and operational `/exchange` remain forbidden.
