# Fusion #02 : Harrier — Prediction-Markets-Trading-Bot-Toolkits (Rust, MIT)
Source: https://github.com/HarrierOnChain/... — "One execution core. One risk layer. Every venue." 10 stratégies sur un moteur unique + adaptateurs venue-agnostic.

## ⭐ OR oublié / haute valeur
- **A1. On-Chain Whale Signal (3–30s d'AVANCE sur l'API publique des positions)** : décode les entrées des leaders depuis les blocs/calldata AVANT que l'API publique ne les montre. → ADAPT: exploiter notre **firehose** (~800k fills WS) comme **source de signal PRIMAIRE et la plus fraîche** (détecter l'OPEN d'un leader via les fills bruts, pas via une API lente). C'est LE levier de fraîcheur pour passer le gate des 6s. Module: `signals/whale_fill_signal.py`.
- **A2. Orderbook Imbalance (OBI) comme signal autonome, refresh 500ms** : "le signal EST le carnet". → ADAPT: feature OBI dédiée (on a depth_imbalance ; en faire un signal/score rafraîchi à ~500ms).
- **A3. Venue-agnostic adapter stack** : "ajouter un marché = écrire UN adaptateur, pas reconstruire le bot". → ADAPT (revoir le DEFER): `venues/base.py` + `HyperliquidReadOnlyAdapter` + `MockAdapter` (+ dYdX isolé). Propre et utile même mono-venue.
- **A4. Safety layer** : **Circuit Breaker** (halt après N gros trades dans une fenêtre), **Depth Guard** (valider la liquidité du carnet AVANT chaque entrée), **Trade Floor** (taille min vs micro-trades EV-négatifs), **Dry Run** (chemin complet sans ordre réel = notre paper). → KEEP tout (depth guard + trade floor à ajouter/renforcer).
- **A5. Semaphore rate limiting** (25 req/10s) + budget perf (<1ms/event, ~200ms/wallet polling). → ADAPT: limiteur à sémaphore + budget de poids REST.

## Stratégies (filtre)
- KEEP/CORE: **Copy Trading** (multi-wallet, circuit breaker). 
- ADAPT en features/signaux: OBI, whale-fill signal, Direction (5m/15m avec TP/SL auto), Spread (microstructure).
- DEFER/BAN: cross-market arb (multi-venue), market making, sports execution, resolution sniper, FAK/GTD réels, <50ms execution.

## BAN
Exécution réelle, FAK/GTD ordres réels, self-custody/clé, market making réel, multi-venue runtime, enable_trading:true.
