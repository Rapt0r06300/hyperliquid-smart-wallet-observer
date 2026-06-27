# Fusion #04 : lihanyu81/polymarket_lp_tool (Python) — monitoring/repricing LP passif
Source: https://github.com/lihanyu81/polymarket_lp_tool — surveille des ordres manuels, keep/cancel/reprice selon orderbook + demi-bande d'incitation δ. (Pas un market-maker auto.)

## À GARDER / ADAPTER (recherche, pas le runtime d'ordres)
- **A1. Séparation modulaire propre** : MainLoop / PricePolicy / OrderBookFetcher / RewardMonitor / RiskManager / **FillNotificationTracker** / ConfigManager / AccountPortfolio. → KEEP: frontières de modules nettes (on les a en grande partie).
- **A2. Inférence de fills depuis le polling** (FillNotificationTracker infère côté fill/cancel + notifie) → ADAPT: détection de fills/deltas leader depuis le polling REST quand le WS manque un event (réconciliation), + dédup (on a fill_dedupe).
- **A3. Whitelist + refresh périodique** (token whitelist rafraîchie toutes les 120s) → ADAPT: rafraîchissement borné de la shortlist (déjà proche).
- **A4. Filtre "déjà en position → skip tout le token"** → ADAPT: cooldown/anti-doublon par coin/wallet (on a cooldown).
- **A5. Reason codes lisibles** dans les notifications → KEEP (nos NoTradeReason).
- **A6. PassiveConfig.from_env()** + retries bornés / max_api_errors → cancel_all → KEEP (config env + source_health sur erreurs API répétées).

## BAN (action réelle)
`OrderManager.apply_decision` (cancel/repost/reprice = ordres réels), **post-only**, private key, funder, Telegram trading. δ d'incitation Polymarket = DEFER (spécifique).

## Verdict
Faible nouveauté vs ce qu'on a, sauf **l'inférence de fills par réconciliation polling↔WS** (A2) et la rigueur modulaire. Repo petit (5 commits).
