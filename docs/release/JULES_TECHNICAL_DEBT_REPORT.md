# Rapport sur la Dette Technique (Handoff Jules -> Codex)

Ce document répertorie les stubs, les incohérences et les zones nécessitant une attention immédiate de Codex.

## 1. Stubs à implémenter

| Emplacement | Statut | Ce qui manque |
| :--- | :--- | :--- |
| `hyper_smart_observer/backtesting/replay_engine.py` | STUB | La méthode `replay_deltas` renvoie un rapport vide. Codex doit brancher la logique de simulation basée sur les deltas. |
| `hyper_smart_observer/copy_mode/edge.py` | PARTIEL | Les pénalités pour `crowding` et `liquidity` sont à 0. Codex doit importer les modèles de `src/hl_observer/edge/edge_remaining.py`. |
| `hyper_smart_observer/copy_mode/delta_detector.py` | RÉEL | Les "flips" (LONG -> SHORT) sont classés en `UNKNOWN`. Codex peut ajouter un modèle de flip s'il est jugé sécurisé. |

## 2. Incohérences d'Architecture

- **Double Dossier** : `src/hl_observer` contient 80% de la logique technique avancée, tandis que `hyper_smart_observer` contient le CLI et la sécurité. Codex doit fusionner techniquement sans casser les garde-fous.
- **Base de Données** : Les schémas de `src` et `hyper` sont légèrement différents. Codex doit privilégier les tables de `hyper_smart_observer` pour la production et y migrer les colonnes utiles de `src`.

## 3. Priorités pour Codex (Sprint 1)

1. **Fusion du Client REST** : Le client dans `src` gère mieux les timeouts et le rate-limiting. Le migrer vers `hyper_smart_observer`.
2. **Confidence Score** : Brancher `src/hl_observer/wallets/skill_vs_luck.py` dans le processus de sélection de la shortlist.
3. **Validation de la Simulation** : S'assurer que `PaperTradingSimulator` utilise bien les `all_mids` en temps réel pour le prix de référence au lieu du prix du leader uniquement.

## 4. Sécurité Permanente

- Ne jamais introduire de `private_key` dans `AppConfig`.
- Ne jamais retirer le flag `--network-read` obligatoire pour les appels HL.
