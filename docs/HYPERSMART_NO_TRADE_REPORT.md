# HyperSmart No-Trade Report

Le `no_trade_report` explique chaque refus en francais simple:

- ce qui a ete observe;
- pourquoi ce n'est pas simulable;
- quelle donnee manque;
- quelle action suivante est recommandee.

Emplacements:

- `data/reports/no_trade_report.md`;
- `data/reports/no_trade_report.json`;
- table SQLite `no_trade_decisions`;
- section dashboard `No-Trade Report`.

Raisons principales:

- `NETWORK_READ_DISABLED`;
- `SOURCE_UNAVAILABLE`;
- `UNKNOWN_DELTA`;
- `EDGE_UNMEASURABLE`;
- `EDGE_REMAINING_TOO_LOW`;
- `STALE_SIGNAL`;
- `LIQUIDITY_TOO_LOW`;
- `COPY_DEGRADATION_TOO_HIGH`;
- `NO_MATCHING_PAPER_POSITION_FOR_CLOSE`;
- `DUPLICATE_FILL`.

Un refus n'est pas une erreur: c'est une decision de securite et de qualite.
