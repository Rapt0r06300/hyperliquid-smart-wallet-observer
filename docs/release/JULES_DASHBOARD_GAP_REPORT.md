# HyperSmart Dashboard Gap Report

| Section dashboard | Source DB attendue | Présente ? | Données réelles ? | Placeholder ? | Action Codex |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Runtime/archive readiness | `runtime_checks` | Oui | Oui | Non | Maintenir |
| Data collection status | `collection_runs` | Oui | Oui | Non | Maintenir |
| Copy status | `copy_runs` | Oui | Oui | Non | Améliorer UI |
| Top wallets followed | `leaderboard_shortlist` | Oui | Oui | Non | Maintenir |
| Leaderboard shortlist | `leaderboard_shortlist` | Oui | Oui | Non | Ajouter filtres |
| Leader activity | `leader_snapshots` | Oui | Oui | Non | Ajouter graphiques |
| Latest deltas | `leader_deltas` | Oui | Oui | Non | Maintenir |
| Signal candidates | `signal_candidates` | Oui | Oui | Non | Maintenir |
| No-trade report | `no_trade_decisions` | Oui | Oui | Non | Traduction FR OK |
| Edge remaining | `signal_candidates` | Oui | Oui | Non | Maintenir |
| Copy degradation | `signal_candidates` | Oui | Oui | Non | Maintenir |
| Source failures | `source_health` | Oui | Oui | Non | Alerte visuelle |
| Position lifecycle | `positions` | Partiel | Partiel | Oui | Relier au moteur src |
| Backtests/replays | `backtest_results` | Partiel | Non | Oui | Intégrer moteur src |
| Paper portfolio | `paper_positions` | Oui | Oui | Non | Maintenir |

**Résumé :**
Le squelette `hyper_smart_observer` est fonctionnel pour l'observation. Le gap principal réside dans l'intégration des fonctionnalités avancées de `src/hl_observer` (backtest complet, cycle de vie position complexe).
