# AGENTS.md — Alina Smart Flow

Dernière mise à jour : **2026-10-27**.

Contrat compact pour tout agent intervenant dans ce dépôt. Les exigences détaillées ne sont pas dupliquées ici : elles vivent dans les documents d’autorité ci-dessous.

## Autorité et lectures obligatoires

Lire, dans cet ordre :

1. `SECURITY.md`
2. `docs/HYPERSMART_CONSTITUTION.md`
3. `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`
4. `docs/LOIS_MESUREES.md`
5. `CLAUDE.md`
6. les éventuels `AGENTS.md` plus proches du fichier modifié.

En cas de conflit : sécurité et constitution, puis spec canonique, puis HEAD réel, puis ce fichier. La spec canonique est unique et évolue en place. Ne pas créer de spec parallèle.

## Dépôts et runtime

- Principal : `Rapt0r06300/hyperliquid-smart-wallet-observer`, branche `main`.
- Données et code : dépôt unique `Rapt0r06300/hyperliquid-smart-wallet-observer`, branche `main`. L'ancien dépôt Dataset V2 est retiré et ne doit être ni requis ni interrogé.
- Runtime actif : `src/hl_observer/`.
- `hyper_smart_observer/` est une surface legacy/compatibilité, pas un second runtime.

Réutiliser les composants existants. Ne pas créer de deuxième orchestrateur, phase controller, RiskEngine, moteur replay/PnL, ledger, Dataset architecture ou scoreboard.

## Sécurité absolue

Alina reste strictement **PAPER / READ-ONLY / FAIL-CLOSED**.

Interdits : ordre réel ou testnet, endpoint d’exécution, clé privée, seed, mnemonic, signature, dépôt, retrait, transfert et activation indirecte par SDK tiers. Toute donnée absente, stale, incohérente ou non prouvée doit fermer la porte ; ne jamais fabriquer zéro, timestamp, fill, trade ou PnL.

Pour Work/GitHub : cloud et GitHub-hosted uniquement. Aucun self-hosted runner, PC utilisateur, SSH, tunnel, wake-on-LAN ou dépendance à un fichier/service local. Les anciens workflows PC/self-hosted restent désactivés.

## Scope économique

Famille active unique : **Copy-Vault**.

Lead-Lag, Cross-Venue Dislocation, arbitrage, Carry/Funding Carry, shadow/research-only et toute famille économique non attribuée : **DISABLED_BY_SCOPE**. Ce verrou couvre simulation UI/moteur principal, labo, replays/backtests, OOS/forward, preuve PnL, certification et scoreboard. Conserver leur code et leurs preuves historiques sans les exécuter ni les promouvoir; aucune variable d'environnement ne peut élargir le scope.

Cible de recherche : au moins +5 USD net/jour pour Copy-Vault, avec 200 USD de capital paper. États honnêtes : `PROVEN`, `PROMISING`, `MORE_DATA`, `UNMEASURABLE`, `REJECTED`. Aucun résultat ne doit être forcé.

## Repères opérateur permanents

- Pour le travail local de l'opérateur, utiliser directement `C:\Users\flo\Desktop\Projet invest`. Ne jamais créer, attacher ou utiliser un worktree.
- Rôles retenus : `LANCER_COLLECTEURS_COPY_VAULT.cmd` = collecte ; `LANCER_LAB_QUANT_COPY_VAULT.cmd` = cerveau replay/backtest et registre durable des améliorations ; `LANCER_HYPERSMART.cmd` = moteur avec simulation visible ; `POUSSER-GITHUB-FORCE.cmd` = synchronisation prudente du code Git.
- AlinaSync, appelé localement via `ALINA_SYNC_COMPLETE.cmd`, gère les shards SAFE. Le lanceur Git ne les transfère pas.
- À la racine ne restent que ces quatre lanceurs principaux et `ALINA_SYNC_COMPLETE.cmd`; `ALINA_SYNC_COMPLETE.sh` y reste pour les clones Unix. Les commandes de support sont dans `tools/launchers/` et leur index est `tools/launchers/README.md`.
- « Portable » signifie qu'un clone du dépôt fonctionne depuis son chemin local ; ne pas confondre cela avec la création d'une archive autonome.
- Le labo conserve chaque candidat/mesure, même exploratoire ; aucune amélioration n'autorise un PnL inventé. Seule la preuve OOS/forward et comptable canonique peut établir un résultat économique.
- Le rôle attendu d'un lanceur ne certifie pas son implémentation actuelle : contrôler le HEAD et corriger tout écart au scope Copy-Vault/PAPER avant de le déclarer conforme.

## Control plane et données

Le control plane canonique est sous `src/hl_observer/control_plane/`.

Phases : `IDLE -> COLLECT -> ANALYZE`.

Étapes d’analyse : `DRAIN -> QUALITY -> REPLAY -> BACKTEST -> OOS -> FORWARD_PAPER -> PNL_PROOF -> SCOREBOARD -> DONE`.

Respecter strictement les phase epochs, `source_collection_epoch`, cutoff figé, manifests, migrations, leases, checkpoints, resume, watchdogs, anti split-brain et idempotence cross-repo.

Seuls les shards du dépôt principal explicitement `SAFE`, replay-compatible, vérifiés par taille/hash, avec exact counts et unique counts globaux peuvent alimenter les preuves. Les collecteurs/normalizers doivent conserver timestamps source/réception, identité native, provenance, clock sync, L2/BBO/trades, gaps et recovery.

## Discipline d’implémentation

Pour une mission d’implémentation : lire le minimum nécessaire, modifier, câbler, sauvegarder, continuer. Un commit n’est qu’un checkpoint. Ne pas s’arrêter tant qu’un élément réalisable de la spec demande encore code, workflow, schéma, migration, configuration, contrat ou documentation normative.

Un seul agent principal par défaut. Privilégier Git, recherche texte, parsing, hashes et transformations déterministes. Après deux échecs identiques, changer de méthode. Préserver les changements existants et éviter les opérations Git destructives.

## Validation et DONE

Quand la mission exige une validation finale différée, terminer d’abord l’implémentation, puis exécuter ensemble les tests, CI, intégrations, replay/backtest/OOS/forward, recovery/resume, Event Intelligence, sécurité, économique, scoreboard et receipts.

Ne jamais déduire `DONE` d’un fichier présent, d’un workflow vert, d’un shard SAFE, d’un backtest positif ou d’un commit. La fermeture globale exige les contrats de la spec, les deux dépôts cohérents, les preuves économiques honnêtes, PAPER/read-only, et aucune voie d’exécution réelle ou self-hosted atteignable.

Avant toute annonce finale : relire les deux HEAD, vérifier les changements et résultats GitHub réels, puis signaler exactement tout blocage externe restant.
