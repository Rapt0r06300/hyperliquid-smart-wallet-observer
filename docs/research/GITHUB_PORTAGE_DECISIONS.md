# GitHub Portage Decisions

Decision labels:

- `COPY_DIRECT`: exact code can be copied after license approval and adaptation tests.
- `COPY_ADAPTED`: small algorithm can be ported with attribution and tests.
- `PORT_BEHAVIOR`: reproduce behavior without copying implementation.
- `INSPIRE_ONLY`: use architecture idea only.
- `RESEARCH_ONLY`: diagnostics/docs/offline analysis only.
- `BAN_RUNTIME`: never run in hot path.
- `DEFER`: not Phase 0.

## Current decisions
| Area | Decision | Reason |
|---|---|---|
| Real executors from any repo | BAN_RUNTIME | Real external money action is forbidden. |
| Wallet mirror behavior | PORT_BEHAVIOR | Useful, but must pass Hyperliquid data and paper ledger. |
| Funding payment accounting | COPY_ADAPTED | Small formula can be implemented locally and tested. |
| Connector/strategy architecture | INSPIRE_ONLY | Hummingbot-style architecture is useful, full framework import is too heavy. |
| Backtest lookahead checks | PORT_BEHAVIOR | Required for honest simulation. |
| Agent/LLM strategy decisions | RESEARCH_ONLY | Explanations only, never hot path. |
| Dashboard chart rendering | INSPIRE_ONLY | Existing UI must be preserved. |
