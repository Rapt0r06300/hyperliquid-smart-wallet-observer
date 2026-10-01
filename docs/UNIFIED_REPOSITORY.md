# Unified Alina Smart Flow repository

The active control plane, campaign catalog, collection workflows, tests,
replay/backtest tooling, and future Dataset V2 releases live in this repository.

Manual phase contract:
- IDLE: no new heavy work.
- COLLECT: collection only; autonomous same-epoch relay is allowed.
- ANALYZE: entered only by an explicit operator request; collection drains,
  then replay/backtest/OOS/forward/PNL proof/scoreboard execute.

Heavy market-data shards are stored as GitHub Release assets, not committed
as ordinary Git blobs. The former Dataset V2 repository is retained only as
migration provenance until historical release mirroring is verified complete.
