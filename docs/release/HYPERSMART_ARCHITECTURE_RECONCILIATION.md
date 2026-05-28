# HyperSmart Architecture Reconciliation (Updated by Jules)

Date: 2026-05-28

## Decision
`hyper_smart_observer` est le package officiel pour le CLI HyperSmart, l'archivage, le mode copie (recherche), le dashboard et la simulation paper mock USDC.
`src/hl_observer` est considéré comme un réservoir de modules avancés (legacy/parallèle) mais non officiels pour le cycle actuel.

## Tableau de Réconciliation

| Fonction | hyper_smart_observer | src/hl_observer | Version la plus complète | Action recommandée pour Codex |
|---|---|---|---|---|
| App main / CLI | `app/main.py` | `__main__.py`, `cli.py`, `autoscan.py` | `hyper_smart_observer` | Garder le CLI unifié dans `hyper_smart_observer`. |
| Config | `app/config.py` | `config/settings.py` | `hyper_smart_observer` | Maintenir la config simplifiée. |
| `/info` client | `hyperliquid_client/info_client.py` | `hyperliquid/rest_info_client.py` | `src/hl_observer` | Fusionner la robustesse de `src` vers `hyper_smart_observer`. |
| WebSocket | `realtime_monitor/` | `hyperliquid/ws_client.py` | `src/hl_observer` | Utiliser le client WS de `src` comme base technique. |
| Copy mode | `copy_mode/` | `copying/` | `hyper_smart_observer` | Priorité à la logique de `hyper_smart_observer`. |
| Preflight | `copy_mode/preflight.py` | N/A | `hyper_smart_observer` | Conserver tel quel. |
| Candidate importer | `copy_mode/candidate_importer.py`| `wallets/leaderboard_importer.py`| `src/hl_observer` | `src` est beaucoup plus riche (DOM, network probe). À migrer. |
| Leaderboard selector| `copy_mode/leaderboard_selector.py`| `copying/leaderboard_autoselect.py`| `src/hl_observer` | `src` possède des filtres plus fins. À fusionner. |
| Delta detector | `copy_mode/delta_detector.py` | `wallets/position_delta_engine.py`| `src/hl_observer` | `src` est plus mature (scorecard, proofs). À migrer. |
| Signal candidate | `copy_mode/signal_candidate.py` | `signals/signal_builder.py` | `hyper_smart_observer` | `hyper_smart_observer` est plus "Magic Bot" compliant. |
| Edge remaining | `copy_mode/edge.py` | `edge/edge_remaining.py` | `src/hl_observer` | `src` est très complet sur les pénalités. À migrer. |
| No_trade_report | `copy_mode/no_trade_report.py` | `validation/no_trade_analyzer.py`| `hyper_smart_observer` | `hyper_smart_observer` a les messages FR clairs. |
| Paper trading | `paper_trading/` | `paper/` | `src/hl_observer` | `src` gère mieux la latence et les fills partiels. |
| Backtest | `backtesting/` | `backtest/` | `src/hl_observer` | `src` possède un moteur de replay plus puissant. |
| Dashboard | `dashboard/` | `ui/` | `src/hl_observer` | `src` a une vraie app FastAPI/JS. `hyper_smart_observer` est minimal. |
| Archive clean | `tools/` | N/A | `hyper_smart_observer` | Conserver. |
| Safety audit | `audit/` | `security/` | `hyper_smart_observer` | Plus récent et spécifique au bot. |
| Tests | `tests/test_hypersmart_*.py` | `tests/test_*.py` | `src/hl_observer` | `src` a une couverture massive. |

## Recommandation Globale Codex
Fusionner le cerveau technique de `src/hl_observer` (collecte, détection, edge, paper engine) dans le squelette de contrôle et de sécurité de `hyper_smart_observer`.
Le dashboard de `src/hl_observer/ui` doit devenir l'interface officielle en pointant vers les données produites par `hyper_smart_observer`.
