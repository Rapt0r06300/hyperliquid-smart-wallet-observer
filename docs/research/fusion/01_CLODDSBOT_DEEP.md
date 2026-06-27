# Fusion — Analyse fine #01 : CloddsBot (alsk1992/CloddsBot)

Source: https://github.com/alsk1992/CloddsBot — MIT, TypeScript, AI trading terminal multi-venues.
Objectif: extraire TOUTES les idées utiles pour notre bot copy-trade-wallet **Hyperliquid, simulation only, branché marché réel**.
Licence MIT = idées réimplémentables proprement (ne pas copier le code TS tel quel).

## A. À GARDER / ADAPTER À HYPERLIQUID (idées en or)

### A1. ⭐ NOUVEAU pour nous — Confidence calibration (Trade Ledger)
- CloddsBot: ledger qui suit "confidence vs accuracy" par **bucket de confiance** (win rate réel par tranche de confiance), stats win/PnL/block-reasons.
- ADAPT: étendre notre `DecisionLedger` avec une **calibration de confiance** : pour chaque signal accepté, comparer la confiance prédite au résultat paper réalisé ; tableau "accuracy par bucket". Mesure DIRECTEMENT si nos scores sont fiables. Module cible: `ledger/calibration.py` (+ panneau dashboard).

### A2. ⭐ NOUVEAU — Risk engine enrichi : VaR/CVaR, régime de volatilité, stress testing
- CloddsBot: unified risk engine = circuit breaker + **VaR/CVaR** + **volatility regime detection** + **stress testing** + Kelly + daily loss limits + kill switch.
- ADAPT (paper-only): ajouter au `risk_engine/` : VaR/CVaR du portefeuille paper, détection de régime de volatilité (LOW/NORMAL/HIGH/EXTREME → resserrer les gates), stress-test (choc de prix) sur les positions paper. Kelly sizing déjà partiel. Module: `risk_engine/var_cvar.py`, `risk_engine/vol_regime.py`, `risk_engine/stress_test.py`.

### A3. ⭐ NOUVEAU — Robustesse "lazy-loaded skills"
- CloddsBot: 119 skills **lazy-loaded** → une dépendance optionnelle manquante NE crashe PAS l'app.
- ADAPT: import paresseux / dégradation gracieuse des modules optionnels (ex: volatility/candles) → si un sous-système échoue, le moteur continue (cohérent avec notre besoin "le moteur doit démarrer"). Pattern transverse.

### A4. ⭐ NOUVEAU — CLI `doctor` + `secure` + `repl`
- `doctor` (diagnostics système), `secure` (durcissement), `repl` (requêtes locales interactives).
- ADAPT: on a déjà `doctor`/`safety-audit` ; ajouter un `secure`-like report (permissions, secrets, garde-fous) et un REPL read-only pour interroger l'état/ledger localement.

### A5. Dashboard "WebChat-like" + historique append-only + context compacting
- CloddsBot: WebChat (sidebar Chats/Artifacts/Code), historique **append-only (1 ligne/msg)**, **context compacting** (résumé des vieux messages), SQLite-backed, pagination.
- ADAPT: panneau "Journal de décisions" append-only + **résumés compactés** des décisions anciennes (pour garder une mémoire lisible sans tout charger), recherche locale. Renforce notre dashboard read-only.

### A6. Trade Ledger → DecisionLedger (déjà aligné) + intégrité SHA-256
- KEEP: audit trail de chaque décision + raisonnement + **hash SHA-256** (on l'a déjà). Garder ; ajouter "block reasons stats".

### A7. Backtesting SL/TP validation + P&L analysis
- KEEP: validation SL/TP en backtest, analyse P&L (on a replay ; ajouter validation explicite SL/TP).

### A8. Copy Trading (CŒUR) + whale tracking + sizing controls + SL/TP
- C'est littéralement notre bot : mirror de wallets gagnants, contrôles de taille, SL/TP. KEEP/CORE — versions **paper** (déjà en place : signal→risk→paper). Whale/large-wallet tracking = notre wallet discovery/scoring.

### A9. Market data layer commun : orderbooks, candles, depth, price feeds temps réel
- KEEP: couche data temps réel (on l'a via /info + WS). Garder l'idée d'un "Common Execution & Data Layer" : Order Builder / Balance Checker / Slippage Estimator / Fee Calculator / real-time P&L / settlement polling → en **paper** (PaperEngine déjà).

### A10. MCP server exposant des tools read-only
- ADAPT: notre `agent_tools/readonly_manifest` peut être exposé en **MCP read-only** (status.read, wallet.leaderboard, decision_ledger.search...). DEFER léger.

## B. À BANNIR (action réelle / hors périmètre — V7 BAN_REAL_ACTION)
- Exécution réelle d'ordres sur 16+ plateformes, perp futures à levier (50x-200x), Solana/EVM DEX swaps, MEV protection, **token launch** (Meteora DBC), **agent marketplace**, **compute API USDC**, **x402 payments**, **Bittensor mining**, **bridging Wormhole**, **onchain anchoring** des hashes, swarm trading multi-wallets, clés privées, credentials de trading chiffrés.
- Multi-venue runtime (Polymarket/Kalshi/Binance/Solana/EVM) → BAN (on reste **Hyperliquid-only**, dYdX isolé).
- 21 canaux de messagerie → BAN/DEFER (au plus un WebChat local read-only).
- LLM dans le hot path décisionnel (CloddsBot est agent-LLM) → BAN (nos décisions restent déterministes locales).

## C. DEFER (idées valables mais non prioritaires)
- Arbitrage cross-plateforme (arXiv:2508.03474) : garder Kelly sizing + liquidity scoring, DEFER l'arbitrage multi-venue.
- Mémoire sémantique LanceDB + hybrid BM25 : DEFER (lourd) — mais l'idée d'une recherche locale sur le ledger est KEEP léger.
- PostgreSQL analytics / 3x replication : DEFER (SQLite local suffit).
- i18n multi-langues : DEFER (FR/EN suffisent).
- External data (FedWatch/538/Odds API) : DEFER (spécifique prediction-markets).

## D. Ce que CloddsBot nous rappelle qu'on avait OUBLIÉ (priorité fusion)
1. **Calibration de confiance** (accuracy par bucket) — mesurer si nos signaux sont fiables. (A1)
2. **VaR/CVaR + régime de volatilité + stress testing** dans le risk engine paper. (A2)
3. **Lazy-load / dégradation gracieuse** — robustesse "le moteur ne crashe jamais sur une dépendance optionnelle". (A3)
4. **`secure` report + REPL read-only**. (A4)
5. **Context compacting + journal append-only** pour la mémoire de décisions. (A5)
6. **Block-reasons stats** dans le ledger (distribution des refus, déjà à moitié via no_trade). (A6)

> Statut: ces points seront intégrés dans la feuille de route fusion finale (V9) une fois tous les GitHub analysés.
