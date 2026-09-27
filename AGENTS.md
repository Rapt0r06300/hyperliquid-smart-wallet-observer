# AGENTS.md — Alina Smart Flow

Dernière mise à jour : **2026-09-27**.

Ce fichier est volontairement compact : il route l'agent vers la spec canonique et évite de gaspiller du contexte.

## Autorité

Ordre de priorité :

1. `SECURITY.md`
2. `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`
3. code + tests + workflows + manifests + receipts du **HEAD courant**
4. ce fichier
5. `CLAUDE.md` et documentation ciblée

Les anciens README, rapports, addenda et noms de versions ne peuvent pas contredire la spec canonique ou le HEAD réel.

## Repositories

Code principal :

- `Rapt0r06300/hyperliquid-smart-wallet-observer`
- branche source de vérité : `main`
- runtime actif : `src/hl_observer/`

Dataset/data plane :

- `Rapt0r06300/alina-smartflow-datasets-v2`
- branche source de vérité : `main`

Dataset V2 possède l'état durable des campagnes cloud lourdes. Le repo principal possède l'intention opérateur, l'orchestration, la logique économique et la surface utilisateur. Ne jamais créer deux copies mutables concurrentes d'un même état de campagne.

## Mission

Familles économiques actives uniquement :

- `copy_vault`
- `lead_lag`
- `cross_venue_dislocation`

`carry/funding_carry = DISABLED_BY_SCOPE`.

Cible finale : **>= +4.00 USD NET/jour PROUVÉS par famille, séparément**, sans compensation et seulement après coûts, capacité, causalité, OOS/forward et qualité de données.

États honnêtes autorisés : `PROVEN`, `MORE_DATA`, `UNMEASURABLE`, `KILL`.

## Sécurité absolue

Alina est **PAPER / READ-ONLY / FAIL-CLOSED**.

Interdit :

- ordre réel ou testnet
- `/exchange` opérationnel
- clé privée, seed, mnemonic
- signature
- dépôt/retrait/transfert
- activation d'un chemin d'exécution réelle

Donnée stale/incomplète/contradictoire/incertaine => refus explicite, jamais invention.

## Cloud / PC utilisateur

Pour ChatGPT Work, GitHub Actions et toute automatisation cloud :

- GitHub-hosted uniquement
- aucun self-hosted runner
- ne jamais réveiller/utiliser/dépendre du PC utilisateur
- aucun SSH/tunnel/agent local vers le PC
- aucun fichier local utilisateur comme source requise

Un calcul local n'est permis que lorsqu'un utilisateur lance explicitement un agent/runtime local. Une mission Work Cloud ne doit jamais basculer vers ce chemin.

## Contrat de travail agent

Par défaut : **un seul agent principal**.

Pas de subagents, swarm ou multi-agent sauf demande explicite.

Pour reprendre un chantier :

1. lire le HEAD actuel ;
2. lire `SECURITY.md` ;
3. lire ce fichier ;
4. lire la spec canonique une fois pour identifier le prochain travail ;
5. ensuite n'ouvrir que les sections/fichiers nécessaires au bloc courant.

Ne pas rescanner l'historique Git complet, les gros logs ou les anciennes roadmaps pour reconstruire un état déjà disponible dans le HEAD/receipts.

Réutiliser l'existant avant de créer un nouveau système.

Si une action échoue deux fois de la même manière, changer de méthode.

## Mode quota minimal

Le modèle sert aux décisions de code qui exigent du raisonnement.

Privilégier pour le reste :

- `git`
- `rg/grep`
- parsers/scripts Python
- JSON/jq
- checksums
- calculs déterministes
- replays/backtests
- tests/lint/static analysis
- GitHub API/Actions quand le cloud est nécessaire

Batcher les lectures. Ne pas relire la spec entière après chaque changement. Pas de rapport intermédiaire long si l'utilisateur demande une implémentation.

## Mode « implémentation totale puis tests finaux »

Si la mission explicite demande :

**implémenter toute la spec d'abord, puis lancer une validation globale à la fin**

alors :

- écrire/modifier le code et les tests nécessaires ;
- ne pas exécuter tests, CI, replays/backtests/OOS/forward intermédiaires sauf blocage de compréhension ;
- sauvegarder régulièrement de vrais diffs ;
- continuer immédiatement au bloc suivant ;
- lancer la validation globale seulement après épuisement du backlog d'implémentation.

Cela change l'ordre d'exécution, **pas** la Definition of Done finale : preuves/tests/gates restent obligatoires avant fermeture globale.

## Control plane actuel

Le runtime actif contient `src/hl_observer/control_plane/` avec notamment :

- `phase_state.py`
- `phase_controller.py`
- `phase_cli.py`
- `resumable_campaign.py`
- `dispatch_receipt.py`
- `campaign_adapters.py`
- `module_pnl_proof.py`

Le contrat cible reste :

- `IDLE`
- `COLLECT`
- `ANALYZE`

Pendant ANALYZE :

`DRAIN -> QUALITY -> REPLAY -> BACKTEST -> OOS -> FORWARD_PAPER -> PNL_PROOF -> SCOREBOARD -> DONE`

La présence de ces fichiers ne signifie pas que tous les `OPEN-*`/`WKR-*` sont fermés. La spec décide du travail restant.

## Architecture

Ne pas étendre `hyper_smart_observer/` comme nouvelle architecture.

Ne pas créer de deuxième :

- orchestrateur
- phase controller
- PnL truth engine
- ledger
- replay engine
- RiskEngine
- scoreboard
- Dataset system

Préférer de petits modules importables sous `src/hl_observer/` et du wiring mince vers les callers existants.

## Données et PnL

Jamais de donnée synthétique présentée comme preuve réelle.

**Missing != 0. Unknown != healthy.**

Une preuve doit utiliser, selon le chemin :

- timestamps exchange/receive/monotonic
- clock offset/RTT/uncertainty
- BBO/L2/trades reconstructibles
- gaps/out-of-order/duplicates
- frais/spread/slippage/latence
- partial/missed fills
- profondeur/VWAP/capacité
- tick/lot/min-notional/multiplier
- exits/funding pertinents
- causalité/no-lookahead
- OOS/forward
- effective-N
- provenance + manifests + hashes

## Git

`main` est l'état final.

- préserver le travail existant
- pas de `reset --hard`, clean destructeur ou rebase destructif comme méthode normale
- éviter branches/systèmes parallèles inutiles
- un commit doit contenir un vrai diff
- ne jamais annoncer « sauvegardé » sans vérifier le vrai commit/diff
- si une plateforme impose une PR, utiliser une branche courte ciblant `main`

Un commit n'est pas une condition d'arrêt : continuer tant que la mission autorisée contient du travail réalisable.

## Definition of Done

Une feature n'est DONE que si elle est réellement codée, câblée et finalement validée selon la spec.

La mission globale n'est DONE que si la matrice de fermeture canonique est satisfaite, les deux repos sont cohérents, la sécurité reste paper/read-only et les résultats économiques sont prouvés ou classés honnêtement.
