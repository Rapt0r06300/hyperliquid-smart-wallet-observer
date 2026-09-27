# CLAUDE.md — Alina Smart Flow

> Compatibilité pour les agents qui chargent automatiquement `CLAUDE.md`.
> Les anciens addenda de juillet 2026 sont supersédés par ce fichier, `AGENTS.md`, `SECURITY.md` et la spec canonique.

Dernière mise à jour : **2026-09-27**.

## Source de vérité

Spec canonique unique :

`docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`

Ne pas créer de nouvelle V6.x/final/vNext spec. Toute clarification normative se fait dans ce fichier en place.

Ordre d'autorité :

`SECURITY.md > spec canonique > HEAD réel (code/tests/workflows/manifests/receipts) > AGENTS.md > CLAUDE.md`.

## Repos et runtime

Repo principal :

`Rapt0r06300/hyperliquid-smart-wallet-observer` — `main`

Runtime actif :

`src/hl_observer/`

Dataset V2 :

`Rapt0r06300/alina-smartflow-datasets-v2` — `main`

Ne pas développer une nouvelle architecture dans `hyper_smart_observer/`; ce répertoire est legacy/compatibilité.

## Sécurité

Alina reste strictement **paper/read-only**.

Aucun :

- ordre réel
- ordre testnet
- `/exchange` opérationnel
- clé privée/seed/mnemonic
- signature
- dépôt/retrait/transfert
- argent réel

`HL_ENABLE_MAINNET_EXECUTION=0` et `HL_ENABLE_TESTNET_EXECUTION=0` restent la doctrine du runtime officiel.

Ne jamais présenter une donnée synthétique, une valeur par défaut ou un zéro inventé comme preuve réelle.

## Cloud uniquement pour les missions Work/GitHub

Une mission ChatGPT Work Cloud ou GitHub :

- ne doit jamais utiliser le PC utilisateur ;
- ne doit jamais réveiller le PC ;
- ne doit jamais dépendre d'un service/fichier/processus local utilisateur ;
- ne doit jamais créer ou utiliser un self-hosted runner ;
- utilise GitHub-hosted pour l'automatisation cloud.

Un chemin local n'est valable que si l'utilisateur lance explicitement une session/runtime local.

## Périmètre économique

Actif :

1. Copy-Vault
2. Lead-Lag
3. Cross-Venue Dislocation

Désactivé :

`Carry / Funding Carry = DISABLED_BY_SCOPE`.

Objectif final : **>= +4.00 USD NET/jour prouvés pour chacune des trois familles séparément**.

Aucune compensation entre familles.

Un résultat non prouvé doit rester `MORE_DATA`, `UNMEASURABLE` ou `KILL`, jamais être maquillé en succès.

## Control plane

Le contrat canonique est fondé sur :

- `IDLE`
- `COLLECT`
- `ANALYZE`

Le HEAD contient une fondation sous `src/hl_observer/control_plane/` :

- phase state/controller
- phase CLI
- resumable campaign schema v2
- dispatch receipt
- campaign adapters
- module PnL proof

L'analyse cible suit :

`DRAIN -> QUALITY -> REPLAY -> BACKTEST -> OOS -> FORWARD_PAPER -> PNL_PROOF -> SCOREBOARD -> DONE`.

Ne déduire aucun `DONE` du simple fait qu'un module existe. Utiliser les `OPEN-*`, `WKR-*`, le runbook et les contrats de fermeture de la spec.

## Ownership cross-repo

Repo principal :

- intention opérateur
- orchestration sémantique
- stratégie/économie
- surface utilisateur

Dataset V2 :

- état durable des campagnes cloud
- leases/checkpoints
- actifs Dataset V2 immuables
- evidence/receipts lourds

Interdit de maintenir deux progress stores mutables concurrents.

Tout dispatch cross-repo doit être idempotent et lié à des SHA/ids/hashes explicites.

## Règles d'ingénierie

- un seul agent principal par défaut ;
- pas de swarm/subagents/multi-agent sauf demande explicite ;
- réutiliser l'existant avant de créer une abstraction ;
- ne pas dupliquer orchestrateur, PnL engine, ledger, replay engine, RiskEngine, scoreboard ou Dataset system ;
- privilégier les petits modules sous `src/hl_observer/` et le wiring mince ;
- ne pas inventer ce qui n'a pas été vérifié ;
- après deux échecs identiques, changer de méthode.

## Quota minimal

Pour une mission longue :

1. lire le HEAD courant ;
2. charger `SECURITY.md`, `AGENTS.md` et la spec ;
3. construire un petit backlog interne ;
4. travailler par sections ciblées ;
5. utiliser grep/parsers/scripts/calculs déterministes au lieu de multiplier les appels modèle ;
6. éviter rapports intermédiaires et relectures inutiles.

Si l'utilisateur demande explicitement **implémentation totale puis tests à la fin**, respecter cet ordre :

- coder/câbler/configurer toute la spec ;
- écrire ou adapter les tests sans forcément les exécuter pendant cette phase ;
- sauvegarder des diffs réels ;
- poursuivre jusqu'à épuisement du backlog implémentable ;
- ensuite exécuter une seule campagne de validation finale et corriger ce qu'elle révèle.

## Vérité des données

Les chemins officiels doivent préserver ce qui est nécessaire à une preuve replay-grade, notamment :

- timestamps exchange/receive/monotonic
- clock sync, RTT, offset, uncertainty
- BBO/L2/trades et snapshot/delta
- séquences/gaps/out-of-order/duplicates
- fee provenance
- tick/lot/min-notional/contract multiplier
- depth/VWAP/capacity/quote age
- provenance/manifests/checksums

Venues/sources à conserver ou vérifier selon la spec : Hyperliquid, Binance, Bybit, OKX, Gate, Bitget.

CCXT reste discovery-only tant qu'un chemin natif d'exécution/replay n'est pas explicitement défini.

## Vérité du PnL

Une preuve économique doit intégrer les coûts et contraintes réellement applicables :

fees + spread + slippage + latency + partial/missed fills + liquidity + capacity + funding pertinent + exits + drawdown + causality + no-lookahead + OOS + forward + effective-N.

Un backtest brut positif n'est jamais une certification.

## Git

`main` est la source de vérité finale.

- préserver le travail existant ;
- éviter branches parallèles inutiles ;
- ne pas utiliser `reset --hard`/clean destructeur/rebase destructif comme méthode normale ;
- vérifier qu'un commit annoncé contient un vrai diff ;
- un commit intermédiaire n'est pas une raison de s'arrêter.

## Definition of Done

La fermeture globale est celle de la spec canonique, pas celle de ce fichier.

Avant de dire DONE, il faut notamment une cohérence vérifiée entre les deux repos, le respect strict du paper/read-only, les stages OOS/forward/scoreboard/receipts requis et un statut économique honnête pour chaque famille.
