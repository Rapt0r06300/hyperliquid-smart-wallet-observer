# HyperSmart Scanner Architecture

Scanner tiers:

1. Cold: imports, local DB, public discovery.
2. Warm: bounded `/info` read-only, default 3 leaders.
3. Hot: WebSocket read-only, max 10 user-specific users.
4. Local: high-throughput wallet index scanning.

Implemented:

- `scanner-priority-report`
- `hot-watch`
- `missed-opportunities`
- `benchmark-local-scan`

