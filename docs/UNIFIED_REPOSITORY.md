# Unified Alina Smart Flow repository

The canonical repository is `Rapt0r06300/hyperliquid-smart-wallet-observer` on `main`.

It owns code, tests, GitHub Actions, phase control, campaign manifests, quality catalog,
replay/backtest tooling and future collection metadata. Heavy trades/L2/BBO payloads
are stored as immutable GitHub Release assets in this same repository, not as ordinary
Git blobs.

The former `Rapt0r06300/alina-smartflow-datasets-v2` repository is legacy/inert.
No new collection, analysis or control-plane authority may originate there.

The post-migration dataset state is intentionally fresh. Historical collection runs and
release assets were not required for cutover; new replay-grade data is collected again
from Alina when the operator explicitly switches IDLE -> COLLECT.

Safety invariants remain unchanged: GitHub-hosted only, paper/read-only, no user PC,
no self-hosted runner, no real order, no private key.
