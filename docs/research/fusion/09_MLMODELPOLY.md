# Fusion #09 : txbabaxyz/mlmodelpoly (Python, MIT) — collecteur temps-réel + features microstructure
Source: https://github.com/txbabaxyz/mlmodelpoly. ⭐ Le plus riche pour les FEATURES marché.

## ⭐ OR oublié / haute valeur (à ADAPTER en features Hyperliquid read-only)
- **A1. Features microstructure riches** (à ajouter à `MarketSignalFeatures`) : **CVD** (cumulative volume delta = pression achat/vente), **RVOL** (volume relatif vs moyenne glissante), **impulse detection** (spikes de momentum), **microprice** (déjà), **anchored VWAP + déviation**, **basis** (perp vs spot — pour HL: perp vs index/oracle), **liquidation tracking** (grosses liquidations forcées). → Modules: `market_signals/cvd.py`, `rvol.py`, `anchored_vwap.py`, `impulse.py`, `liquidations.py`.
- **A2. Fair Value Model + edge en bps** : estimation de probabilité (modes **fast/smooth**), **spike/dip detection**, **edge calculation (bps)** + **EDGE_BUFFER_BPS=25** (buffer d'edge requis). → ADAPT: notre `edge_calculator` + un `fair_model` (prob), edge_remaining_bps avec buffer.
- **A3. Bias model multi-timeframe** (biais directionnel 1m/5m/15m/1h via bootstrap HTF klines `CONTEXT_TFS`). → ADAPT: contexte de tendance multi-TF depuis candleSnapshot (déjà candles, ajouter le biais multi-TF).
- **A4. Volatility fast/slow/blend sigma** → ADAPT: enrichir `volatility.py` (sigma rapide/lente/mélangée, pas qu'un range).
- **A5. ⭐ Quality Mode OK/DEGRADED/BAD** par flux → KEEP/renforcer notre `data_quality` + source_health (3 niveaux explicites).
- **A6. REST read-only `/latest/features`, `/latest/bars`, `/latest/edge`, `/state`, `/health`** → ADAPT: exposer "dernières features / dernier edge / derniers bars" en lecture seule (super pour debug + agent tools).
- **A7. Gates d'exécution** : `STALE_THRESHOLD_SEC=5`, `MIN_DEPTH=200` (profondeur min, sinon veto), `MAX_SPREAD_BPS=500` (veto), `COOLDOWN_SEC`, **`MAX_SLICES_PER_WINDOW=30` + `MAX_USD_PER_WINDOW`** (plafonds par fenêtre). → KEEP: min-depth veto + max-slices/USD par fenêtre (on a stale/spread/liquidity, ajouter min-depth + slices/window).
- **A8. decision_logger structuré + event recording (replay)** + Prometheus metrics + JSON logging. → KEEP (DecisionLedger + replay + /metrics).
- **A9. Architecture propre** : pipeline / features / bars / edge_engine / fair_model / bias_model / volatility / accumulate_engine / decision_logger / http_api / metrics + config pydantic-settings. → KEEP (frontières nettes).

## BAN
Binance hot-path runtime, **TAAPI.io** (clé/secret externe dans le hot path), Polymarket CLOB, exécution réelle, slices d'ordres réels. (Binance→Polymarket = arb latence, hors périmètre.)

## Verdict
Repo CLÉ pour la qualité du signal. Gros apport : **CVD, RVOL, anchored VWAP, impulse, liquidations, basis, fair-value prob, bias multi-TF, quality-mode 3 niveaux, /latest/* read-only, min-depth veto + max-slices/window**. Tout adaptable en read-only Hyperliquid.
