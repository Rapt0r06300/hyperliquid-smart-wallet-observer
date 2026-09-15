# Alina SmartFlow — Data Expansion

The data plane has four explicit layers:

- **Native live:** Hyperliquid, Binance, Bybit, OKX, Gate.io and Bitget. These public, read-only collectors feed the existing `MultiVenueMarketStore`, Cross-Venue and Lead-Lag.
- **CCXT discovery:** `CCXTUniverseScout` scans the configured 15+ exchanges and writes a bounded JSON snapshot. CCXT prices are never used in the hot path; markets without a native collector remain `DISCOVERY_ONLY`.
- **Historical/replay:** `HistoricalBackfillHub` accepts bounded official/API, JSON/JSONL/CSV and optional Tardis files. Canonical records carry venue, symbol, data type, exchange time, optional receive time, source and provenance.
- **Specialized context:** existing Coinbase, Kraken, Deribit, Glassnode, DefiLlama, Dune and Nansen normalizers remain research/context sources. Key-gated sources are marked `REQUIRES_KEY`.

`determine_replay_quality()` classifies datasets as `BRONZE` (OHLCV/funding), `SILVER` (trades/BBO/funding/OI) or `GOLD` (tick/L2/timestamps/sequences/mark/index/liquidations). Missing or invalid data is `UNMEASURABLE`; `order_point_in_time()` excludes information not known at the decision timestamp.

Useful commands:

```bash
python -m hl_observer discover-ccxt-universe
python -m hl_observer data-coverage --snapshot data/ccxt_universe.json
python -m hl_observer replay-quality path/to/records.jsonl
```
