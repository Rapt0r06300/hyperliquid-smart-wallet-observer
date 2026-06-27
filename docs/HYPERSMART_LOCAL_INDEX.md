# HyperSmart Local Index

The local index is the safe way to analyze many wallets quickly.

Implemented:

- `src/hl_observer/local_index/wallet_index.py`
- `src/hl_observer/local_index/index_benchmark.py`
- `python -m hl_observer benchmark-local-scan --wallets 2000`
- `python -m hl_observer scan-local --limit 2000`

The benchmark is local-only and never calls Hyperliquid.

