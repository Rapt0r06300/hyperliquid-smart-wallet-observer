# Fusion #11 : evan-kolberg/prediction-market-backtesting (Python/Rust, 858★) — moteur sur NautilusTrader
Source: https://github.com/evan-kolberg/prediction-market-backtesting. ⚠️ Licences MIXTES (GPL-3.0 + LGPL + MIT) → idées/architecture seulement, AUCUN code copié.

## ⭐ OR oublié / très haute valeur (backtest, calibration, exec modeling)
- **A1. ⭐ Account Ledger Replay → "Copy-Trading Interpretation"** + section **"Why Exact Reproduction Fails"** + External Source Check + Observed Result. → C'est EXACTEMENT notre approche : rejouer le ledger d'un wallet leader, l'interpréter en copy-trading, et **reconnaître honnêtement que la reproduction exacte échoue** (latence, slippage, file d'attente). À documenter/implémenter comme cadre de notre backtest copy. Module: `backtesting/account_ledger_replay.py`.
- **A2. ⭐ Execution modeling profond** : Fees (+ **maker rebates**), Slippage, **Passive orders & queue position**, Latency, Limits, **Vendor L2 behavior**. → ADAPT: enrichir notre modèle de coûts paper (file d'attente passive, maker rebate, comportement L2) au-delà de fee/spread/slippage/latence.
- **A3. ⭐ Suite de charting** : equity (total + par marché), **P&L ticks**, P&L periodic bars, market allocation, YES price avec fills buy/sell, **drawdown**, **Sharpe (ombrage au-dessus/sous)**, cash/equity, **monthly returns**, **cumulative Brier advantage**. → ADAPT (Lightweight Charts) : nos charts paper = equity/drawdown/Sharpe/monthly/PnL-ticks + **Brier**.
- **A4. ⭐ Brier score / "cumulative brier advantage"** = métrique de **calibration de probabilité**. → ADAPT: ajouter le **Brier score** à notre calibration de confiance (lie A1-CloddsBot + PolyWeather). Module: `scoring/calibration.py` (brier).
- **A5. Data loading étagé + caches matérialisés + bus unifié cache/local/archive/API + "failure semantics"** + **book replay (orderbook deltas + trade ticks)**. → ADAPT: notre replay event-driven (fills+deltas+books) + staged loading + sémantique d'échec explicite (on a event_replay).
- **A6. Runner contract / EXPERIMENT objects + runtime/backtest parity** + notebooks. → KEEP (parité runtime/backtest, déjà ; formaliser un "EXPERIMENT/runner contract").
- **A7. Research: scoring, joint-portfolio multi-replay, samplers random-grid + TPE (Optuna), caveats.** → DEFER mais précieux: **optimisation de paramètres** (TPE/Optuna) pour calibrer honnêtement les seuils, **multi-wallet joint replay**, avec caveats anti-overfit.
- **A8. Testing: repo gate standard + smoke checks + docs validation.** → KEEP (nos gates de test + safety).

## BAN
- Live sandbox/execution path (le repo a "live sandbox plumbing" → on reste paper).
- Copie de code (licences copyleft GPL/LGPL).
- Dépendance NautilusTrader lourde → DEFER (on garde notre moteur léger ; s'inspirer de l'architecture).

## Verdict
Le repo le plus mûr pour **backtest + exec modeling + calibration**. Apports majeurs : **account-ledger replay interprété en copy-trading (+ honnêteté sur la repro)**, **Brier score**, **exec modeling (queue/maker rebate/L2)**, **charting equity/drawdown/sharpe/monthly/brier**, **optimisation TPE anti-overfit**. Tout adaptable en paper Hyperliquid.
