# Alina Smart Flow — index unique Codex des 3 120 tâches (extension INT + RIG)

> Création du 3 novembre 2026 à partir de 2 100 tâches historiques réellement retrouvées dans le dépôt et de 1 020 **nouvelles obligations**. Cette extension ne prétend pas retrouver mot pour mot les 1 020 descriptions historiques absentes. **Aucune de ces nouvelles tâches ne vaut DONE.**

## Autorité de la feuille de route consolidée

- **1 100 tâches sources** : [ASF/AUD/ECO/LCH/PNL/BUG](2026-11-02-alina-audit-roadmap-190.md) — 150 ASF, 72 AUD, 200 ECO, 300 LCH, 78 PNL, 300 BUG.
- **1 000 tests HVR historiques** : [HVR-0001..HVR-1000](2026-11-02-alina-audit-roadmap-190-hvr-1000.md) — contrôles de module, pas 1000 bugs prouvés.
- **1 000 tests d'intégration nouveaux** : 10 lots de 100 `ASF-HVR-INT-0001..1000`, listés ci-dessous.
- **20 contrôles transversaux nouveaux** : `ASF-RIG-001..020` détaillés ici.

**Total unique : 1 100 + 1 000 + 1 000 + 20 = 3 120 tâches.** Chaque ID a une case GitHub, une priorité, des chemins d’audit, une action et un reçu. Les fichiers sont complémentaires : aucune duplication de registre.

**Règles impératives :** dépôt unique `Rapt0r06300/hyperliquid-smart-wallet-observer`, branche `main`; une spec canonique `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`; sécurité PAPER/READ-ONLY/FAIL-CLOSED; CopyVault seule famille économique active; cloud GitHub-hosted seulement, sans toucher au PC; un agent principal; maintenir la collecte. Ne pas créer une architecture parallèle.

**Codex :** lire `AGENTS.md`, puis la source principale, HVR, les dix lots INT et les 20 RIG ; traiter tous les IDs et saisir un reçu vérifiable par tag. Une piste HVR/INT/BUG est une hypothèse à falsifier, pas un bug d’emblée. Statuts : `TODO`, `IN_PROGRESS`, `PARTIAL`, `BLOCKED`, `VERIFIED_DONE`, `DUPLICATE`, `SUPERSEDED`, `HISTORICAL`, `OUT_OF_SCOPE`. Cocher `[x]` seulement avec `VERIFIED_DONE` et test, SHA, preuve de branchement, exit code. Classer les hypothèses non pertinentes avec motif sans les compter comme implémentées.

**Export en un seul fichier pour Codex :** `python tools/roadmap_722_progress.py --export-md ALINA_ROADMAP_3120.md`. L'export regroupe les 13 fichiers sources sans changer leurs IDs ni statuts. Il n'est généré que si le registre passe le contrôle d'intégrité.

**Progression :** `python tools/roadmap_722_progress.py` — afficher `VERIFIED_DONE/3120` et `traitées/3120`, ainsi que P0 non vérifiés, anomalies et groupes. Les 775 optimisations historiques scellées restent un registre distinct; aucune ancienne certification n’est recopiée automatiquement.

## Dix lots INT (100 scénarios chacun)

- [INT lot 01 — ASF-HVR-INT-0001..0100](2026-11-02-alina-audit-roadmap-190-int-01.md)
- [INT lot 02 — ASF-HVR-INT-0101..0200](2026-11-02-alina-audit-roadmap-190-int-02.md)
- [INT lot 03 — ASF-HVR-INT-0201..0300](2026-11-02-alina-audit-roadmap-190-int-03.md)
- [INT lot 04 — ASF-HVR-INT-0301..0400](2026-11-02-alina-audit-roadmap-190-int-04.md)
- [INT lot 05 — ASF-HVR-INT-0401..0500](2026-11-02-alina-audit-roadmap-190-int-05.md)
- [INT lot 06 — ASF-HVR-INT-0501..0600](2026-11-02-alina-audit-roadmap-190-int-06.md)
- [INT lot 07 — ASF-HVR-INT-0601..0700](2026-11-02-alina-audit-roadmap-190-int-07.md)
- [INT lot 08 — ASF-HVR-INT-0701..0800](2026-11-02-alina-audit-roadmap-190-int-08.md)
- [INT lot 09 — ASF-HVR-INT-0801..0900](2026-11-02-alina-audit-roadmap-190-int-09.md)
- [INT lot 10 — ASF-HVR-INT-0901..1000](2026-11-02-alina-audit-roadmap-190-int-10.md)

## Vingt contrôles transversaux RIG

Ces 20 tâches sont des contrôles indépendants d'intégration et de preuve. Pour chaque preuve : SHA HEAD, commandes/tests et code retour, fichiers réels, constat contradictoire et diff réel. Une présence de code n’est jamais une preuve de fonctionnement.

- [ ] **[ASF-RIG-001] Exhaustivité 3120 IDs** (P0). **Action :** Valider continuité exacte des plages, unicité globale, métadonnées, 3120 cases et reçus. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `tools/roadmap_722_progress.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-002] Autorités et SHA du code** (P1). **Action :** Lire HEAD, spec unique, sécurité, constitution et supprimer les contradictions normatives réellement constatées. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P1` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `AGENTS.md`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-003] Aucune transaction même testnet** (P0). **Action :** Exécuter audit des routes d’ordre, signatures, SDK et launchers; vérifier interdiction absolue. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `SECURITY.md`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-004] CopyVault seul actif** (P0). **Action :** Tester allowlist du runtime, labo, UI, replay, OOS, scoreboard et absence de contournement env. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/strategies/active_scope.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-005] Continuité des collecteurs** (P1). **Action :** Mesurer liveness avant, pendant et après corrections sûres; ne pas interrompre la collecte. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P1` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/control_plane/phase_state.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-006] Identité unique du dataset** (P0). **Action :** Contrôler Releases, provenance, repo unique, absence d’ancienne dépendance Dataset V2. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/datasets/v2_pipeline.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-007] Exhaustivité des comptes exacts** (P1). **Action :** Comparer record count, trade count et unique global sur shards et overlaps; refuser comptes estimés. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P1` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/datasets/replay_coverage.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-008] Certification L2 exécutable** (P0). **Action :** Valider snapshot+delta, séquences, checksums, BBO, profondeur et incapacité à inventer un fill. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/market_data/live_l2_service.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-009] Pare-feu SAFE strict** (P0). **Action :** Réparer PARTIAL si démontré; sinon exclure PARTIAL/REJECT des entrées de preuve. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/datasets/dataset_untrusted_guard.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-010] AlinaSync clone et restauration** (P1). **Action :** Tester SHA, octets, décompression, sortie, reprise et replay d’un corpus SAFE vérifié. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P1` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `tools/sync_complete_clone.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-011] Parité moteur runtime / replay** (P1). **Action :** Comparer événements, décisions, fills, coûts et reason-codes sur mêmes entrées/seed. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P1` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/backtest/runtime_parity.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-012] Conservation du ledger PAPER** (P1). **Action :** Exercer frais, funding, cash, marge, expositions, clôtures partielles et liquidation. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P1` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/simulation/paper_ledger.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-013] Ordre causal et anti-lookahead** (P0). **Action :** Falsifier décision future, délais, heures venue, holdout réutilisé et cutoffs de phase. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/backtest/no_lookahead_guard.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-014] Coûts complets et sortie liquidable** (P1). **Action :** Prouver spreads, profondeur, slippage, frais, latence, capacité, funding et equity liquidable. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P1` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/simulation/cost_components.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-015] Statistiques anti-faux positif** (P1). **Action :** Exécuter placebo, ablation, walk-forward, correction essais multiples et stabilité des paramètres. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P1` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/backtest/walk_forward.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-016] Gels positifs append-only** (P1). **Action :** Prouver code SHA, data digest, fenêtres, seed, configuration, coût et historique non réécrit. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P1` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/simulation/economic_freeze_registry.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-017] Champion OOS + forward indépendant** (P0). **Action :** Vérifier OOS gelé, forward paper post-freeze disjoint, receipts et refus de promotion. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `src/hl_observer/simulation/scoreboard_promotion.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-018] Cloud GitHub-hosted seulement** (P0). **Action :** Vérifier absence d’activation self-hosted/PC/SSH et permissions minimales des workflows. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `docs/normative-gate-registry.json`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-019] Portabilité des lanceurs** (P1). **Action :** Tester CMD officiels, bash, chemins relatifs, sync code séparée de sync SAFE, codes d’erreurs. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P1` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `ALINA_SYNC_COMPLETE.cmd`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.

- [ ] **[ASF-RIG-020] Clôture prouvée des 3120** (P0). **Action :** Exiger 3120 verdicts et preuves par tâche; réconcilier P0, diff, HEAD, tests et rendement non inventé. **Oracle :** une vérification reproductible sur le chemin actif, avec décision fail-closed en cas de manque.
  - **Suivi Codex :** `TODO` · **Priorité :** `P0` · **Fichiers vérifiés HEAD (points d'entrée à examiner) :** `tools/roadmap_722_progress.py`. **Correctif attendu :** corriger uniquement les écarts reproduits, tests positifs/négatifs et absence de régression; documenter les écarts externes. **Reçu de clôture :** `PENDING`.
