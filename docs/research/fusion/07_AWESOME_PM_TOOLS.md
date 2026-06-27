# Fusion #07 : aarora4/Awesome-Prediction-Market-Tools — liste-benchmark de l'écosystème
Source: https://github.com/aarora4/Awesome-Prediction-Market-Tools — "AI Agents, Analytics, APIs, Dashboards, Copy Trading, Alerting, Tracking and More".

## Valeur = BENCHMARK PRODUIT (ce qu'un outil "complet" propose) → cartographie vers nous (HL-sim)
Catégories de la liste → équivalent HyperSmart à viser :
- **Analytics & dashboards** → notre dashboard read-only (équité paper, edge, source_health, lifecycle, patterns, backtests).
- **APIs / data feeds** → `/info` + WS Hyperliquid read-only, exports JSON/CSV.
- **Copy Trading** → CŒUR : observation + scoring + signaux + paper.
- **Wallet analytics / leaderboards** → WalletScoreV2, CopyabilityScore, leaderboard shortlist, labels smart/whale/suspicious/fresh.
- **Alerting / tracking** → alertes **désactivées par défaut** (read-only), tracking de positions = paper only.
- **Historical snapshots** → snapshots locaux + backtests.
- **Live odds/spreads/liquidity/orderbook depth** → MarketSignalFeatures (mid/spread/liquidity/microprice/depth).

## ADAPT (idées à viser pour un produit "complet")
- Watchlists avec validation d'adresse (on a normalize_wallet_address).
- Étiquettes de wallet **fondées sur des preuves** (label = exige evidence_count).
- Portfolio tracking = **paper only**.
- Alertes **off par défaut** (jamais d'action).

## BAN
One-click replication, wallet connect, betting autonome, faux charts/mockups.

## Verdict
Pas du code à fusionner — c'est une **checklist produit**. Sert à vérifier qu'on couvre toutes les catégories d'un outil de référence : analytics, dashboards, copy-trading, wallet intelligence, leaderboards, alerting (off), tracking, historique, microstructure. On les couvre déjà en grande partie ; manque surtout des **labels evidence-based** + watchlists.
