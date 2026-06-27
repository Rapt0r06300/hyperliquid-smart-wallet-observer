# Fusion #10 : txbabaxyz/polyrec (Python, MIT) — dashboard temps-réel + CSV 70+ colonnes + backtests
Source: https://github.com/txbabaxyz/polyrec.

## ⭐ OR oublié / haute valeur
- **A1. `scan_features` CSV ultra-riche (70+ colonnes)** par marché : timestamps + **`seconds_till_end`** (temps avant résolution), **`lag`** (oracle vs feed = mesure de latence/qualité), returns multi-fenêtres (1s/5s), volume + **volma**, **ATR multi-fenêtres (5s/30s)**, **rvol_30s**, **5 niveaux d'orderbook**, spread, imbalance, **microprice**, **slope (depth_slope)**, **eat-flow/trade-flow** (flux agressif). → ADAPT: enrichir notre `scan_features` (on a déjà mid/spread/microprice/depth_imbalance/depth_slope/volatility) avec **lag**, **ATR multi-fenêtres**, **rvol**, **trade-flow/eat-flow**, **seconds_till_end** quand pertinent. Module: `market_signals/scan_features` (exporter).
- **A2. Logging CSV automatique par "marché"/fenêtre** → KEEP (exports CSV/JSON par run, déjà).
- **A3. Backtests dédiés** : `replicate_balance.py` (réplication de balance d'un wallet), `fade_impulse_backtest.py` (fade d'impulsion), visualisation. → ADAPT: scénarios de backtest "réplication d'un wallet leader" (= copy paper) + fade-impulse comme stratégie de recherche.

## BAN / DEFER
- BAN: Chainlink/Binance runtime, subprocess Node pour le feed, logs comme DB primaire.
- Le "lag oracle vs feed" → chez nous: lag entre `source_ts` et `local_received_ts` (latence WS) = source_health (déjà). 

## Verdict
Apport concret = **enrichir le vecteur de features** (lag, ATR multi-fenêtres, rvol, trade-flow/eat-flow, seconds_till_end) + scénario backtest "réplication de wallet". Confirme notre direction microstructure.
