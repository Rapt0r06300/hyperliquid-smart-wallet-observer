# Guide de Migration pour Codex (HL Observer -> HyperSmart)

Ce guide détaille les composants de `src/hl_observer` qui doivent être migrés ou adaptés dans `hyper_smart_observer` pour atteindre la parité de fonctionnalités.

## 1. Client Hyperliquid & Collecte

| Composant | Source (src/hl_observer) | Destination (hyper_smart_observer) | Note |
| :--- | :--- | :--- | :--- |
| Client REST Robuste | `hyperliquid/rest_info_client.py` | `hyperliquid_client/info_client.py` | Ajouter le support de retry et le logging avancé de `src`. |
| Client WebSocket | `hyperliquid/ws_client.py` | `realtime_monitor/ws_manager.py` | Migrer la gestion des abonnements multi-wallets (max 10). |
| Snapshot Multi-Assets | `collection/collector.py` | `copy_mode/snapshot_engine.py` | Intégrer la collecte parallèle de `clearinghouseState`. |

## 2. Détection & Analyse

| Composant | Source (src/hl_observer) | Destination (hyper_smart_observer) | Note |
| :--- | :--- | :--- | :--- |
| Scorecard Deltas | `wallets/snapshot_engine.py` | `copy_mode/delta_detector.py` | Intégrer les 9 preuves de confiance (confidence scorecard). |
| Pénalités Edge | `edge/edge_remaining.py` | `copy_mode/edge.py` | Migrer les calculs de `liquidity_penalty` et `crowding_penalty`. |
| Filtres Leaders | `wallets/discovery_filters.py` | `copy_mode/leaderboard_selector.py` | Ajouter les filtres de ROI par coin et stabilité. |
| Skill vs Luck | `wallets/skill_vs_luck.py` | `scoring/confidence.py` | Intégrer les calculs de borne inférieure de Wilson. |

## 3. Simulation & Paper Trading

| Composant | Source (src/hl_observer) | Destination (hyper_smart_observer) | Note |
| :--- | :--- | :--- | :--- |
| Moteur de Replay | `backtest/replay_engine.py` | `backtesting/replay.py` | Adapter le moteur pour lire les `LeaderDelta` de la nouvelle DB. |
| Fills Partiels | `paper/partial_fill_model.py` | `paper_trading/simulator.py` | Ajouter la simulation de profondeur de carnet (L2). |
| Latence Variable | `paper/latency_model.py` | `paper_trading/latency.py` | Utiliser les modèles de délais observés de `src`. |

## 4. Interface Utilisateur (Dashboard)

| Composant | Source (src/hl_observer) | Destination (hyper_smart_observer) | Note |
| :--- | :--- | :--- | :--- |
| App FastAPI | `ui/app.py` | `dashboard/web_app.py` | Remplacer l'export statique par la vraie app FastAPI. |
| Metagraphe JS | `ui/static/js/app.js` | `dashboard/static/` | Maintenir le rendu Heikin-Ashi et la cyan equity trend line. |
| Mode Expert | `ui/templates/` | `dashboard/templates/` | Conserver la séparation Expert/Simplifié (#expertView). |

## 5. Sécurité

- **Maintenir impérativement** le `preflight.py` de `hyper_smart_observer`.
- **Ne jamais migrer** les fichiers d'exécution (`execution/live_executor.py`) s'ils contiennent des appels `/exchange`.
- **Vérifier** que les boutons UI respectent l'allowlist de `src/hl_observer/ui/safe_actions.py`.
