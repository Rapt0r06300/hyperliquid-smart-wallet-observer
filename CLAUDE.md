# CLAUDE.md — Alina Smart Flow

Dernière mise à jour : **2026-09-27**.

Ce fichier est volontairement **court**. Claude Code le charge à chaque session ; les détails permanents communs à tous les agents vivent dans `AGENTS.md` et la spec canonique.

## Avant toute modification

Lis dans cet ordre :

1. `SECURITY.md`
2. `AGENTS.md`
3. `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`
4. le HEAD courant et uniquement les fichiers/callers/tests/workflows utiles au bloc traité

Ne reconstruis pas l'état du projet depuis de vieux rapports ou conversations si le HEAD, les manifests ou les receipts fournissent l'état réel.

## Autorité

Ordre pratique :

`SECURITY.md > spec canonique > HEAD réel > AGENTS.md > CLAUDE.md > README.md`

La spec canonique est unique et se met à jour **en place**.

Ne crée jamais de nouvelle spec `V6.x`, `final`, `vNext`, `bis` ou parallèle.

## Repositories

Principal :

`Rapt0r06300/hyperliquid-smart-wallet-observer` — `main`

Runtime actif :

`src/hl_observer/`

Dataset/data plane :

`Rapt0r06300/alina-smartflow-datasets-v2` — `main`

`hyper_smart_observer/` est legacy/compatibilité : ne pas y construire une nouvelle architecture.

## Mission et scope

Familles économiques actives :

- Copy-Vault
- Lead-Lag
- Cross-Venue Dislocation

`Carry / Funding Carry = DISABLED_BY_SCOPE`.

Objectif final : **>= +4.00 USD NET/jour PROUVÉS par famille séparément**.

Les statuts honnêtes restent :

`PROVEN / MORE_DATA / UNMEASURABLE / KILL`.

Ne jamais modifier les coûts, les gates ou la méthodologie pour fabriquer un résultat positif.

## Sécurité non négociable

Alina reste :

**PAPER / READ-ONLY / FAIL-CLOSED**

Interdit :

- ordre réel ;
- ordre testnet ;
- `/exchange` opérationnel ;
- clé privée / seed / mnemonic ;
- signature ;
- dépôt / retrait / transfert ;
- activation d'un chemin réel par SDK tiers.

Doctrine runtime :

`HL_ENABLE_MAINNET_EXECUTION=0`

`HL_ENABLE_TESTNET_EXECUTION=0`

Une donnée absente, stale, contradictoire ou incertaine reste inconnue/partielle : jamais de zéro ou timestamp inventé.

## Work/GitHub : cloud uniquement

Pour une mission Work Cloud ou GitHub :

- GitHub-hosted uniquement ;
- aucun self-hosted runner ;
- ne jamais utiliser, réveiller ou dépendre du PC utilisateur ;
- aucun SSH/tunnel/service/fichier local utilisateur requis.

Les anciens workflows self-hosted/PC présents dans l'historique sont des artefacts désactivés : ne jamais les réactiver.

## Architecture à réutiliser

Le control plane existe déjà sous :

`src/hl_observer/control_plane/`

avec notamment phase state/controller, phase CLI, resumable campaigns, dispatch receipts, campaign adapters, typed events et module PnL proof.

Phases :

`IDLE -> COLLECT -> ANALYZE`

Analyse :

`DRAIN -> QUALITY -> REPLAY -> BACKTEST -> OOS -> FORWARD_PAPER -> PNL_PROOF -> SCOREBOARD -> DONE`

Ne crée pas de deuxième orchestrateur, phase controller, replay engine, PnL engine, ledger, RiskEngine, scoreboard ou Dataset system.

## Quota minimal

Par défaut : **un seul agent principal**.

Pas de swarm/subagents/multi-agent sauf demande explicite de l'utilisateur.

Privilégie :

- `git`
- `rg/grep`
- scripts/parsers
- JSON/jq
- hashes/checksums
- calculs déterministes
- tests/replays/backtests déterministes

Ne relis pas la spec entière après chaque étape. Travaille par sections ciblées.

## Mission longue

Quand l'utilisateur demande d'implémenter/finir/continuer :

- considère la demande comme une mission complète ;
- ne t'arrête pas après un plan, un fichier, un test, un commit ou une PR ;
- continue tant qu'il reste du travail autorisé et réalisable ;
- après deux échecs identiques, change de méthode ;
- si une vraie limite persiste, finis tout le travail indépendant puis laisse un checkpoint exact.

Si l'utilisateur demande explicitement **implémentation totale puis tests à la fin**, respecte cet ordre : code/wiring d'abord, campagne de validation globale ensuite. Cela ne supprime jamais les exigences finales de preuve.

## Git

`main` est la source de vérité finale.

Avant d'annoncer un travail sauvegardé ou terminé :

- relis le HEAD ;
- vérifie les fichiers réellement modifiés ;
- vérifie le diff réel ;
- refuse tout commit vide.

Évite `reset --hard`, clean/rebase destructifs et branches parallèles inutiles.

## Definition of Done

Ne déduis jamais `DONE` de la présence d'un fichier, d'un workflow vert, d'un SAFE, d'un backtest positif ou d'un commit.

La fermeture globale est celle de la spec canonique : cohérence des deux repos, data/replay evidence, OOS/forward, PnL proof, scoreboard, receipts, paper/read-only, aucun self-hosted et aucune exécution réelle atteignable.

Pour tous les détails opérationnels, suis `AGENTS.md` puis la spec canonique.
