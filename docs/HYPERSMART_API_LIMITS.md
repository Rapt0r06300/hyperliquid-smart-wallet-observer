# Hyperliquid API Limits for HyperSmart

## REST Info Client Limits

| Endpoint | Weight | Description |
| :--- | :--- | :--- |
| `allMids` | 2 | Current mid prices for all coins. |
| `clearinghouseState` | 2 | Position and margin summary for a wallet. |
| `userFills` | 20 | Recent fills for a wallet (last 2000). |
| `userFillsByTime` | 20 | Fills in a time range (max 2000 per page). |
| `openOrders` | 2 | Currently open orders. |
| `frontendOpenOrders`| 2 | Orders opened via frontend. |

## HyperSmart Configuration Limits

Défini dans `hyper_smart_observer.app.config.AppConfig`:

- `copy_max_leaders_per_run = 3`: Maximum de leaders traités par cycle de polling.
- `copy_min_edge_required_bps = 8.0`: Edge minimal après dégradation pour accepter une simulation paper.
- `HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT = 500`: Limite recommandée pour Codex pour la pagination.

## WebSocket Limits

- Maximum 10 connexions WebSocket simultanées.
- Maximum 1000 subscriptions par connexion.
- Maximum 10 utilisateurs uniques pour les subscriptions `userFills` / `userEvents`.
- Maximum 30 nouvelles connexions par minute.

## Sécurité API

- **Interdiction Formelle** : N'utilisez JAMAIS `/exchange`.
- Les requêtes sont en lecture seule (`read-only`).
- Le polling par défaut est de 300 secondes.
