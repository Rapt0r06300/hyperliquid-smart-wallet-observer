# Alina Smart Flow — feuille de route auditée (190 tâches)

> Plan d'exécution Codex; création du plan ≠ réparation du logiciel. Audit source du 2 novembre 2026, HEAD initial `8be80f71ac0bad22bb5166882d6d59c7c59c82d1`. Relire le HEAD avant chaque correction.

**Source unique** `Rapt0r06300/hyperliquid-smart-wallet-observer`, `main` ; spec unique `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md` (à actualiser en place). **PAPER/READ-ONLY/FAIL-CLOSED**, Copy-Vault seul; pas de self-hosted, PC distant, ordre réel, clé ou signature. Un agent principal, pas de worktree, cloud uniquement GitHub-hosted; tests locaux uniquement si Codex est lancé localement par l'opérateur.

**Objectif économique :** plus de seuil fixe +4/+5 USD nets/jour. Geler toute amélioration nette observée avec provenance/seed/coûts/config, même petite; ne promouvoir un **champion validé** qu'après OOS/forward post-freeze, preuves nettes, causalité, liquidatabilité et gates intactes. Après un gel, recommencer la découverte. Les anciennes preuves et essais ne s'effacent jamais.

**Anti-saut :** statut par tag `TODO`, `IN_PROGRESS`, `PARTIAL`, `BLOCKED`, `VERIFIED_DONE`, `HISTORICAL`, `DUPLICATE`, `SUPERSEDED`, `OUT_OF_SCOPE`; à chaque tâche associer fichiers, tests positifs/négatifs, commande et exit code, diff réel, evidence et SHA exact. Pas de DONE pour simple présence de code, rapport ancien ou job vert. Ne pas supprimer ou renuméroter le registre ancien 136 tâches. Maintenir collecte en fonctionnement pendant les corrections sûres.

## 150 tâches principales


### 01 autorités, inventaire et gouvernance

- [ ] **[ASF-001] Vérifier le véritable HEAD** (P0, ancien T001). **Action :** Réconcilier autorités, fichiers et chemins réellement appelés. Sujet précis : Vérifier le véritable HEAD. **Preuve :** Matrice de couverture SHA et non-doublon.
- [ ] **[ASF-002] Lire la hiérarchie des autorités** (P0, ancien T002). **Action :** Réconcilier autorités, fichiers et chemins réellement appelés. Sujet précis : Lire la hiérarchie des autorités. **Preuve :** Matrice de couverture SHA et non-doublon.
- [ ] **[ASF-003] Reconstituer l'architecture réelle** (P0, ancien T003). **Action :** Réconcilier autorités, fichiers et chemins réellement appelés. Sujet précis : Reconstituer l'architecture réelle. **Preuve :** Matrice de couverture SHA et non-doublon.
- [ ] **[ASF-004] Réconcilier les 775 exigences historiques** (P0, ancien T004). **Action :** Réconcilier autorités, fichiers et chemins réellement appelés. Sujet précis : Réconcilier les 775 exigences historiques. **Preuve :** Matrice de couverture SHA et non-doublon.
- [ ] **[ASF-005] Réconcilier V5 et 776+** (P0, ancien T005). **Action :** Réconcilier autorités, fichiers et chemins réellement appelés. Sujet précis : Réconcilier V5 et 776+. **Preuve :** Matrice de couverture SHA et non-doublon.
- [ ] **[ASF-006] Inventorier les idées complémentaires** (P0, ancien T006). **Action :** Réconcilier autorités, fichiers et chemins réellement appelés. Sujet précis : Inventorier les idées complémentaires. **Preuve :** Matrice de couverture SHA et non-doublon.
- [ ] **[ASF-007] Créer la matrice de couverture** (P0, ancien T007). **Action :** Réconcilier autorités, fichiers et chemins réellement appelés. Sujet précis : Créer la matrice de couverture. **Preuve :** Matrice de couverture SHA et non-doublon.
- [ ] **[ASF-008] Réconcilier la documentation** (P0, ancien T008). **Action :** Réconcilier autorités, fichiers et chemins réellement appelés. Sujet précis : Réconcilier la documentation. **Preuve :** Matrice de couverture SHA et non-doublon.

### 02 sécurité, scope et orchestration

- [ ] **[ASF-009] Tester PAPER/READ-ONLY** (P0, ancien T009). **Action :** Tracer les garde-fous jusqu'aux effets et injecter un usage interdit. Sujet précis : Tester PAPER/READ-ONLY. **Preuve :** Tests PAPER/read-only/CopyVault-only fail-closed.
- [ ] **[ASF-010] Vérifier Copy-Vault-only** (P0, ancien T010). **Action :** Tracer les garde-fous jusqu'aux effets et injecter un usage interdit. Sujet précis : Vérifier Copy-Vault-only. **Preuve :** Tests PAPER/read-only/CopyVault-only fail-closed.
- [ ] **[ASF-011] Vérifier les anciens flags expérimentaux** (P0, ancien T011). **Action :** Tracer les garde-fous jusqu'aux effets et injecter un usage interdit. Sujet précis : Vérifier les anciens flags expérimentaux. **Preuve :** Tests PAPER/read-only/CopyVault-only fail-closed.
- [ ] **[ASF-012] Vérifier le fail-closed** (P0, ancien T012). **Action :** Tracer les garde-fous jusqu'aux effets et injecter un usage interdit. Sujet précis : Vérifier le fail-closed. **Preuve :** Tests PAPER/read-only/CopyVault-only fail-closed.
- [ ] **[ASF-013] Auditer les phases** (P0, ancien T013). **Action :** Tracer les garde-fous jusqu'aux effets et injecter un usage interdit. Sujet précis : Auditer les phases. **Preuve :** Tests PAPER/read-only/CopyVault-only fail-closed.
- [ ] **[ASF-014] Vérifier leases et epochs** (P0, ancien T014). **Action :** Tracer les garde-fous jusqu'aux effets et injecter un usage interdit. Sujet précis : Vérifier leases et epochs. **Preuve :** Tests PAPER/read-only/CopyVault-only fail-closed.
- [ ] **[ASF-015] Garantir la collecte continue** (P0, ancien T015). **Action :** Tracer les garde-fous jusqu'aux effets et injecter un usage interdit. Sujet précis : Garantir la collecte continue. **Preuve :** Tests PAPER/read-only/CopyVault-only fail-closed.
- [ ] **[ASF-016] Éliminer les voies cloud non autorisées** (P0, ancien T016). **Action :** Tracer les garde-fous jusqu'aux effets et injecter un usage interdit. Sujet précis : Éliminer les voies cloud non autorisées. **Preuve :** Tests PAPER/read-only/CopyVault-only fail-closed.

### 03 bloqueurs actuels et campagnes GitHub

- [ ] **[ASF-017] Réconcilier le rapport de clôture** (P0, ancien T017). **Action :** Réconcilier campaigns, logs, receipts et compteurs. Sujet précis : Réconcilier le rapport de clôture. **Preuve :** Preuve SHA-bound, identités uniques, absence de clôture fictive.
- [ ] **[ASF-018] Corriger le comptage global unique des trades** (P0, ancien T018). **Action :** Réconcilier campaigns, logs, receipts et compteurs. Sujet précis : Corriger le comptage global unique des trades. **Preuve :** Preuve SHA-bound, identités uniques, absence de clôture fictive.
- [ ] **[ASF-019] Corriger la preuve globale de clôture** (P0, ancien T019). **Action :** Réconcilier campaigns, logs, receipts et compteurs. Sujet précis : Corriger la preuve globale de clôture. **Preuve :** Preuve SHA-bound, identités uniques, absence de clôture fictive.
- [ ] **[ASF-020] Réconcilier la preuve du scoreboard** (P0, ancien T020). **Action :** Réconcilier campaigns, logs, receipts et compteurs. Sujet précis : Réconcilier la preuve du scoreboard. **Preuve :** Preuve SHA-bound, identités uniques, absence de clôture fictive.
- [ ] **[ASF-021] Vérifier les campagnes d'analyse non terminales** (P0, ancien T021). **Action :** Réconcilier campaigns, logs, receipts et compteurs. Sujet précis : Vérifier les campagnes d'analyse non terminales. **Preuve :** Preuve SHA-bound, identités uniques, absence de clôture fictive.
- [ ] **[ASF-022] Auditer les campagnes marché PARTIAL** (P0, ancien T022). **Action :** Réconcilier campaigns, logs, receipts et compteurs. Sujet précis : Auditer les campagnes marché PARTIAL. **Preuve :** Preuve SHA-bound, identités uniques, absence de clôture fictive.
- [ ] **[ASF-023] Auditer les échecs Event Intelligence** (P0, ancien T023). **Action :** Réconcilier campaigns, logs, receipts et compteurs. Sujet précis : Auditer les échecs Event Intelligence. **Preuve :** Preuve SHA-bound, identités uniques, absence de clôture fictive.
- [ ] **[ASF-024] Renforcer recovery et publication** (P0, ancien T024). **Action :** Réconcilier campaigns, logs, receipts et compteurs. Sujet précis : Renforcer recovery et publication. **Preuve :** Preuve SHA-bound, identités uniques, absence de clôture fictive.

### 04 collecte multi-venues replay-grade

- [ ] **[ASF-025] Auditer Hyperliquid** (P0, ancien T025). **Action :** Tester flux REST/WS, source native, récupération, timestamps et limites. Sujet précis : Auditer Hyperliquid. **Preuve :** Fixture API, gap, backfill, rate-limit et dédup vérifiés.
- [ ] **[ASF-026] Auditer Binance** (P0, ancien T026). **Action :** Tester flux REST/WS, source native, récupération, timestamps et limites. Sujet précis : Auditer Binance. **Preuve :** Fixture API, gap, backfill, rate-limit et dédup vérifiés.
- [ ] **[ASF-027] Auditer Bybit** (P0, ancien T027). **Action :** Tester flux REST/WS, source native, récupération, timestamps et limites. Sujet précis : Auditer Bybit. **Preuve :** Fixture API, gap, backfill, rate-limit et dédup vérifiés.
- [ ] **[ASF-028] Auditer OKX** (P0, ancien T028). **Action :** Tester flux REST/WS, source native, récupération, timestamps et limites. Sujet précis : Auditer OKX. **Preuve :** Fixture API, gap, backfill, rate-limit et dédup vérifiés.
- [ ] **[ASF-029] Auditer Gate et Bitget** (P0, ancien T029). **Action :** Tester flux REST/WS, source native, récupération, timestamps et limites. Sujet précis : Auditer Gate et Bitget. **Preuve :** Fixture API, gap, backfill, rate-limit et dédup vérifiés.
- [ ] **[ASF-030] Auditer les autres venues présentes** (P0, ancien T030). **Action :** Tester flux REST/WS, source native, récupération, timestamps et limites. Sujet précis : Auditer les autres venues présentes. **Preuve :** Fixture API, gap, backfill, rate-limit et dédup vérifiés.
- [ ] **[ASF-031] Renforcer la couche d'acquisition** (P0, ancien T031). **Action :** Tester flux REST/WS, source native, récupération, timestamps et limites. Sujet précis : Renforcer la couche d'acquisition. **Preuve :** Fixture API, gap, backfill, rate-limit et dédup vérifiés.
- [ ] **[ASF-032] Certifier les contrats par venue** (P0, ancien T032). **Action :** Tester flux REST/WS, source native, récupération, timestamps et limites. Sujet précis : Certifier les contrats par venue. **Preuve :** Fixture API, gap, backfill, rate-limit et dédup vérifiés.

### 05 qualification SAFE et réconciliation historique

- [ ] **[ASF-033] Vérifier l'identité des données** (P0, ancien T033). **Action :** Contrôler SHA, provenance, L2/BBO, séquences, timestamps et éligibilité SAFE. Sujet précis : Vérifier l'identité des données. **Preuve :** Aucun PARTIAL ou REJECT admis au replay.
- [ ] **[ASF-034] Vérifier L2/BBO** (P0, ancien T034). **Action :** Contrôler SHA, provenance, L2/BBO, séquences, timestamps et éligibilité SAFE. Sujet précis : Vérifier L2/BBO. **Preuve :** Aucun PARTIAL ou REJECT admis au replay.
- [ ] **[ASF-035] Vérifier l'intégrité** (P0, ancien T035). **Action :** Contrôler SHA, provenance, L2/BBO, séquences, timestamps et éligibilité SAFE. Sujet précis : Vérifier l'intégrité. **Preuve :** Aucun PARTIAL ou REJECT admis au replay.
- [ ] **[ASF-036] Réparer les PARTIAL réparables** (P0, ancien T036). **Action :** Contrôler SHA, provenance, L2/BBO, séquences, timestamps et éligibilité SAFE. Sujet précis : Réparer les PARTIAL réparables. **Preuve :** Aucun PARTIAL ou REJECT admis au replay.
- [ ] **[ASF-037] Exclure les PARTIAL irréparables** (P0, ancien T037). **Action :** Contrôler SHA, provenance, L2/BBO, séquences, timestamps et éligibilité SAFE. Sujet précis : Exclure les PARTIAL irréparables. **Preuve :** Aucun PARTIAL ou REJECT admis au replay.
- [ ] **[ASF-038] Exclure les REJECT** (P0, ancien T038). **Action :** Contrôler SHA, provenance, L2/BBO, séquences, timestamps et éligibilité SAFE. Sujet précis : Exclure les REJECT. **Preuve :** Aucun PARTIAL ou REJECT admis au replay.
- [ ] **[ASF-039] Réconcilier les données historiques** (P0, ancien T039). **Action :** Contrôler SHA, provenance, L2/BBO, séquences, timestamps et éligibilité SAFE. Sujet précis : Réconcilier les données historiques. **Preuve :** Aucun PARTIAL ou REJECT admis au replay.
- [ ] **[ASF-040] Vérifier le corpus SAFE final** (P0, ancien T040). **Action :** Contrôler SHA, provenance, L2/BBO, séquences, timestamps et éligibilité SAFE. Sujet précis : Vérifier le corpus SAFE final. **Preuve :** Aucun PARTIAL ou REJECT admis au replay.

### 06 AlinaSync, clone et restauration intégrale

- [ ] **[ASF-041] Auditer les quatre surfaces principales** (P0, ancien T041). **Action :** Tester clone froid, inventaire Release, téléchargement, décompression et index. Sujet précis : Auditer les quatre surfaces principales. **Preuve :** Restitution byte-à-byte des shards SAFE et premier replay.
- [ ] **[ASF-042] Réconcilier le comportement sans argument** (P0, ancien T042). **Action :** Tester clone froid, inventaire Release, téléchargement, décompression et index. Sujet précis : Réconcilier le comportement sans argument. **Preuve :** Restitution byte-à-byte des shards SAFE et premier replay.
- [ ] **[ASF-043] Vérifier l'inventaire Releases** (P0, ancien T043). **Action :** Tester clone froid, inventaire Release, téléchargement, décompression et index. Sujet précis : Vérifier l'inventaire Releases. **Preuve :** Restitution byte-à-byte des shards SAFE et premier replay.
- [ ] **[ASF-044] Certifier les téléchargements** (P0, ancien T044). **Action :** Tester clone froid, inventaire Release, téléchargement, décompression et index. Sujet précis : Certifier les téléchargements. **Preuve :** Restitution byte-à-byte des shards SAFE et premier replay.
- [ ] **[ASF-045] Certifier la décompression** (P0, ancien T045). **Action :** Tester clone froid, inventaire Release, téléchargement, décompression et index. Sujet précis : Certifier la décompression. **Preuve :** Restitution byte-à-byte des shards SAFE et premier replay.
- [ ] **[ASF-046] Vérifier budgets et stockage** (P0, ancien T046). **Action :** Tester clone froid, inventaire Release, téléchargement, décompression et index. Sujet précis : Vérifier budgets et stockage. **Preuve :** Restitution byte-à-byte des shards SAFE et premier replay.
- [ ] **[ASF-047] Certifier les rapports et index** (P0, ancien T047). **Action :** Tester clone froid, inventaire Release, téléchargement, décompression et index. Sujet précis : Certifier les rapports et index. **Preuve :** Restitution byte-à-byte des shards SAFE et premier replay.
- [ ] **[ASF-048] Tester le parcours opérateur complet** (P0, ancien T048). **Action :** Tester clone froid, inventaire Release, téléchargement, décompression et index. Sujet précis : Tester le parcours opérateur complet. **Preuve :** Restitution byte-à-byte des shards SAFE et premier replay.

### 07 Copy-Vault et reconstruction des wallets

- [ ] **[ASF-049] Auditer discovery et leaderboard** (P1, ancien T049). **Action :** Tracer discovery→wallet→fill→position→signal→sortie. Sujet précis : Auditer discovery et leaderboard. **Preuve :** Tests OPEN/ADD/REDUCE/CLOSE/UNKNOWN sans faux fill.
- [ ] **[ASF-050] Auditer les vaults** (P1, ancien T050). **Action :** Tracer discovery→wallet→fill→position→signal→sortie. Sujet précis : Auditer les vaults. **Preuve :** Tests OPEN/ADD/REDUCE/CLOSE/UNKNOWN sans faux fill.
- [ ] **[ASF-051] Renforcer le scoring des wallets** (P1, ancien T051). **Action :** Tracer discovery→wallet→fill→position→signal→sortie. Sujet précis : Renforcer le scoring des wallets. **Preuve :** Tests OPEN/ADD/REDUCE/CLOSE/UNKNOWN sans faux fill.
- [ ] **[ASF-052] Certifier les observations** (P1, ancien T052). **Action :** Tracer discovery→wallet→fill→position→signal→sortie. Sujet précis : Certifier les observations. **Preuve :** Tests OPEN/ADD/REDUCE/CLOSE/UNKNOWN sans faux fill.
- [ ] **[ASF-053] Certifier le lifecycle** (P1, ancien T053). **Action :** Tracer discovery→wallet→fill→position→signal→sortie. Sujet précis : Certifier le lifecycle. **Preuve :** Tests OPEN/ADD/REDUCE/CLOSE/UNKNOWN sans faux fill.
- [ ] **[ASF-054] Corriger les événements ambigus** (P1, ancien T054). **Action :** Tracer discovery→wallet→fill→position→signal→sortie. Sujet précis : Corriger les événements ambigus. **Preuve :** Tests OPEN/ADD/REDUCE/CLOSE/UNKNOWN sans faux fill.
- [ ] **[ASF-055] Renforcer les sorties** (P1, ancien T055). **Action :** Tracer discovery→wallet→fill→position→signal→sortie. Sujet précis : Renforcer les sorties. **Preuve :** Tests OPEN/ADD/REDUCE/CLOSE/UNKNOWN sans faux fill.
- [ ] **[ASF-056] Vérifier toute la chaîne Copy-Vault** (P1, ancien T056). **Action :** Tracer discovery→wallet→fill→position→signal→sortie. Sujet précis : Vérifier toute la chaîne Copy-Vault. **Preuve :** Tests OPEN/ADD/REDUCE/CLOSE/UNKNOWN sans faux fill.

### 08 RiskEngine, ledger et dashboard

- [ ] **[ASF-057] Auditer le RiskEngine canonique** (P1, ancien T057). **Action :** Tester RiskEngine→PAPER→ledger→dashboard et refus. Sujet précis : Auditer le RiskEngine canonique. **Preuve :** PnL réconcilié et aucun ordre réel possible.
- [ ] **[ASF-058] Vérifier les capitaux** (P1, ancien T058). **Action :** Tester RiskEngine→PAPER→ledger→dashboard et refus. Sujet précis : Vérifier les capitaux. **Preuve :** PnL réconcilié et aucun ordre réel possible.
- [ ] **[ASF-059] Vérifier les limites de risque** (P1, ancien T059). **Action :** Tester RiskEngine→PAPER→ledger→dashboard et refus. Sujet précis : Vérifier les limites de risque. **Preuve :** PnL réconcilié et aucun ordre réel possible.
- [ ] **[ASF-060] Vérifier l'exécution PAPER** (P1, ancien T060). **Action :** Tester RiskEngine→PAPER→ledger→dashboard et refus. Sujet précis : Vérifier l'exécution PAPER. **Preuve :** PnL réconcilié et aucun ordre réel possible.
- [ ] **[ASF-061] Vérifier l'exactitude du ledger** (P1, ancien T061). **Action :** Tester RiskEngine→PAPER→ledger→dashboard et refus. Sujet précis : Vérifier l'exactitude du ledger. **Preuve :** PnL réconcilié et aucun ordre réel possible.
- [ ] **[ASF-062] Renforcer NO_TRADE** (P1, ancien T062). **Action :** Tester RiskEngine→PAPER→ledger→dashboard et refus. Sujet précis : Renforcer NO_TRADE. **Preuve :** PnL réconcilié et aucun ordre réel possible.
- [ ] **[ASF-063] Auditer les affichages HyperSmart** (P1, ancien T063). **Action :** Tester RiskEngine→PAPER→ledger→dashboard et refus. Sujet précis : Auditer les affichages HyperSmart. **Preuve :** PnL réconcilié et aucun ordre réel possible.
- [ ] **[ASF-064] Supprimer les fausses façades** (P1, ancien T064). **Action :** Tester RiskEngine→PAPER→ledger→dashboard et refus. Sujet précis : Supprimer les fausses façades. **Preuve :** PnL réconcilié et aucun ordre réel possible.

### 09 amélioration des signaux et des BPS

- [ ] **[ASF-065] Reproduire les baselines historiques pertinentes** (P2, ancien T065). **Action :** Comparer à baseline avec mêmes données, coûts, latence et risque. Sujet précis : Reproduire les baselines historiques pertinentes. **Preuve :** Rapport net, ablation, intervalle, essais conservés.
- [ ] **[ASF-066] Tester de meilleurs sous-ensembles de leaders** (P2, ancien T066). **Action :** Comparer à baseline avec mêmes données, coûts, latence et risque. Sujet précis : Tester de meilleurs sous-ensembles de leaders. **Preuve :** Rapport net, ablation, intervalle, essais conservés.
- [ ] **[ASF-067] Étudier la microstructure** (P2, ancien T067). **Action :** Comparer à baseline avec mêmes données, coûts, latence et risque. Sujet précis : Étudier la microstructure. **Preuve :** Rapport net, ablation, intervalle, essais conservés.
- [ ] **[ASF-068] Étudier les séquences de marché** (P2, ancien T068). **Action :** Comparer à baseline avec mêmes données, coûts, latence et risque. Sujet précis : Étudier les séquences de marché. **Preuve :** Rapport net, ablation, intervalle, essais conservés.
- [ ] **[ASF-069] Étudier les régimes** (P2, ancien T069). **Action :** Comparer à baseline avec mêmes données, coûts, latence et risque. Sujet précis : Étudier les régimes. **Preuve :** Rapport net, ablation, intervalle, essais conservés.
- [ ] **[ASF-070] Renforcer l'estimation du signal** (P2, ancien T070). **Action :** Comparer à baseline avec mêmes données, coûts, latence et risque. Sujet précis : Renforcer l'estimation du signal. **Preuve :** Rapport net, ablation, intervalle, essais conservés.
- [ ] **[ASF-071] Calculer l'edge net honnêtement** (P2, ancien T071). **Action :** Comparer à baseline avec mêmes données, coûts, latence et risque. Sujet précis : Calculer l'edge net honnêtement. **Preuve :** Rapport net, ablation, intervalle, essais conservés.
- [ ] **[ASF-072] Organiser le tournoi scientifique** (P2, ancien T072). **Action :** Comparer à baseline avec mêmes données, coûts, latence et risque. Sujet précis : Organiser le tournoi scientifique. **Preuve :** Rapport net, ablation, intervalle, essais conservés.

### 10 World Monitor et sources financières

- [ ] **[ASF-073] Auditer les six variantes World Monitor** (P3, ancien T073). **Action :** Vérifier source, disponibilité point-in-time et consommateur. Sujet précis : Auditer les six variantes World Monitor. **Preuve :** Aucun lookahead, utilité empirique prouvée ou non-déploiement.
- [ ] **[ASF-074] Auditer les flux et contrats** (P3, ancien T074). **Action :** Vérifier source, disponibilité point-in-time et consommateur. Sujet précis : Auditer les flux et contrats. **Preuve :** Aucun lookahead, utilité empirique prouvée ou non-déploiement.
- [ ] **[ASF-075] Étudier News et Markets** (P3, ancien T075). **Action :** Vérifier source, disponibilité point-in-time et consommateur. Sujet précis : Étudier News et Markets. **Preuve :** Aucun lookahead, utilité empirique prouvée ou non-déploiement.
- [ ] **[ASF-076] Étudier les données boursières** (P3, ancien T076). **Action :** Vérifier source, disponibilité point-in-time et consommateur. Sujet précis : Étudier les données boursières. **Preuve :** Aucun lookahead, utilité empirique prouvée ou non-déploiement.
- [ ] **[ASF-077] Étudier la macroéconomie** (P3, ancien T077). **Action :** Vérifier source, disponibilité point-in-time et consommateur. Sujet précis : Étudier la macroéconomie. **Preuve :** Aucun lookahead, utilité empirique prouvée ou non-déploiement.
- [ ] **[ASF-078] Étudier crypto et dérivés** (P3, ancien T078). **Action :** Vérifier source, disponibilité point-in-time et consommateur. Sujet précis : Étudier crypto et dérivés. **Preuve :** Aucun lookahead, utilité empirique prouvée ou non-déploiement.
- [ ] **[ASF-079] Étudier géopolitique et économie réelle** (P3, ancien T079). **Action :** Vérifier source, disponibilité point-in-time et consommateur. Sujet précis : Étudier géopolitique et économie réelle. **Preuve :** Aucun lookahead, utilité empirique prouvée ou non-déploiement.
- [ ] **[ASF-080] Prioriser les intégrations utiles** (P3, ancien T080). **Action :** Vérifier source, disponibilité point-in-time et consommateur. Sujet précis : Prioriser les intégrations utiles. **Preuve :** Aucun lookahead, utilité empirique prouvée ou non-déploiement.

### 11 Event Intelligence et 120 idées

- [ ] **[ASF-081] Vérifier les 120 identifiants** (P3, ancien T081). **Action :** Tracer chaque idée vers producteur, données et consommateur. Sujet précis : Vérifier les 120 identifiants. **Preuve :** Branchement effectif, distinct de preuve économique.
- [ ] **[ASF-082] Corriger les chaînes non fonctionnelles** (P3, ancien T082). **Action :** Tracer chaque idée vers producteur, données et consommateur. Sujet précis : Corriger les chaînes non fonctionnelles. **Preuve :** Branchement effectif, distinct de preuve économique.
- [ ] **[ASF-083] Normaliser les événements** (P3, ancien T083). **Action :** Tracer chaque idée vers producteur, données et consommateur. Sujet précis : Normaliser les événements. **Preuve :** Branchement effectif, distinct de preuve économique.
- [ ] **[ASF-084] Renforcer la qualité des sources** (P3, ancien T084). **Action :** Tracer chaque idée vers producteur, données et consommateur. Sujet précis : Renforcer la qualité des sources. **Preuve :** Branchement effectif, distinct de preuve économique.
- [ ] **[ASF-085] Garantir les jointures causales** (P3, ancien T085). **Action :** Tracer chaque idée vers producteur, données et consommateur. Sujet précis : Garantir les jointures causales. **Preuve :** Branchement effectif, distinct de preuve économique.
- [ ] **[ASF-086] Relier les événements aux marchés** (P3, ancien T086). **Action :** Tracer chaque idée vers producteur, données et consommateur. Sujet précis : Relier les événements aux marchés. **Preuve :** Branchement effectif, distinct de preuve économique.
- [ ] **[ASF-087] Relier les features à Copy-Vault** (P3, ancien T087). **Action :** Tracer chaque idée vers producteur, données et consommateur. Sujet précis : Relier les features à Copy-Vault. **Preuve :** Branchement effectif, distinct de preuve économique.
- [ ] **[ASF-088] Mesurer leur utilité** (P3, ancien T088). **Action :** Tracer chaque idée vers producteur, données et consommateur. Sujet précis : Mesurer leur utilité. **Preuve :** Branchement effectif, distinct de preuve économique.

### 12 laboratoire quantitatif et mémoire

- [ ] **[ASF-089] Vérifier la console laboratoire** (P2, ancien T089). **Action :** Exécuter campagne déterministe et préserver expérience. Sujet précis : Vérifier la console laboratoire. **Preuve :** Même résultat sur même seed; ledger append-only.
- [ ] **[ASF-090] Vérifier le context pack** (P2, ancien T090). **Action :** Exécuter campagne déterministe et préserver expérience. Sujet précis : Vérifier le context pack. **Preuve :** Même résultat sur même seed; ledger append-only.
- [ ] **[ASF-091] Certifier Discovery V3.2** (P2, ancien T091). **Action :** Exécuter campagne déterministe et préserver expérience. Sujet précis : Certifier Discovery V3.2. **Preuve :** Même résultat sur même seed; ledger append-only.
- [ ] **[ASF-092] Certifier le tournoi** (P2, ancien T092). **Action :** Exécuter campagne déterministe et préserver expérience. Sujet précis : Certifier le tournoi. **Preuve :** Même résultat sur même seed; ledger append-only.
- [ ] **[ASF-093] Vérifier l'historique durable** (P2, ancien T093). **Action :** Exécuter campagne déterministe et préserver expérience. Sujet précis : Vérifier l'historique durable. **Preuve :** Même résultat sur même seed; ledger append-only.
- [ ] **[ASF-094] Renforcer les expérimentations** (P2, ancien T094). **Action :** Exécuter campagne déterministe et préserver expérience. Sujet précis : Renforcer les expérimentations. **Preuve :** Même résultat sur même seed; ledger append-only.
- [ ] **[ASF-095] Vérifier les méthodes statistiques** (P2, ancien T095). **Action :** Exécuter campagne déterministe et préserver expérience. Sujet précis : Vérifier les méthodes statistiques. **Preuve :** Même résultat sur même seed; ledger append-only.
- [ ] **[ASF-096] Éviter l'overfitting** (P2, ancien T096). **Action :** Exécuter campagne déterministe et préserver expérience. Sujet précis : Éviter l'overfitting. **Preuve :** Même résultat sur même seed; ledger append-only.

### 13 replays et backtests déterministes

- [ ] **[ASF-097] Vérifier l'ordonnancement causal** (P1, ancien T097). **Action :** Rejouer book et fills PAPER avec pannes injectées. Sujet précis : Vérifier l'ordonnancement causal. **Preuve :** Golden replay déterministe et failles rejetées.
- [ ] **[ASF-098] Vérifier la reconstruction des carnets** (P1, ancien T098). **Action :** Rejouer book et fills PAPER avec pannes injectées. Sujet précis : Vérifier la reconstruction des carnets. **Preuve :** Golden replay déterministe et failles rejetées.
- [ ] **[ASF-099] Vérifier le moteur d'exécution simulé** (P1, ancien T099). **Action :** Rejouer book et fills PAPER avec pannes injectées. Sujet précis : Vérifier le moteur d'exécution simulé. **Preuve :** Golden replay déterministe et failles rejetées.
- [ ] **[ASF-100] Vérifier les fills PAPER** (P1, ancien T100). **Action :** Rejouer book et fills PAPER avec pannes injectées. Sujet précis : Vérifier les fills PAPER. **Preuve :** Golden replay déterministe et failles rejetées.
- [ ] **[ASF-101] Vérifier les positions et sorties** (P1, ancien T101). **Action :** Rejouer book et fills PAPER avec pannes injectées. Sujet précis : Vérifier les positions et sorties. **Preuve :** Golden replay déterministe et failles rejetées.
- [ ] **[ASF-102] Certifier le déterminisme** (P1, ancien T102). **Action :** Rejouer book et fills PAPER avec pannes injectées. Sujet précis : Certifier le déterminisme. **Preuve :** Golden replay déterministe et failles rejetées.
- [ ] **[ASF-103] Renforcer les tests anti-biais** (P1, ancien T103). **Action :** Rejouer book et fills PAPER avec pannes injectées. Sujet précis : Renforcer les tests anti-biais. **Preuve :** Golden replay déterministe et failles rejetées.
- [ ] **[ASF-104] Créer ou consolider les golden replays** (P1, ancien T104). **Action :** Rejouer book et fills PAPER avec pannes injectées. Sujet précis : Créer ou consolider les golden replays. **Preuve :** Golden replay déterministe et failles rejetées.

### 14 OOS, forward et preuves économiques

- [ ] **[ASF-105] Vérifier les gates actuelles** (P1, ancien T105). **Action :** Séparer TRAIN/OOS/forward, freeze et coûts complets. Sujet précis : Vérifier les gates actuelles. **Preuve :** Verdict honnête, sans profit fixe terminal ni fuite.
- [ ] **[ASF-106] Vérifier le gel des candidats** (P1, ancien T106). **Action :** Séparer TRAIN/OOS/forward, freeze et coûts complets. Sujet précis : Vérifier le gel des candidats. **Preuve :** Verdict honnête, sans profit fixe terminal ni fuite.
- [ ] **[ASF-107] Vérifier OOS** (P1, ancien T107). **Action :** Séparer TRAIN/OOS/forward, freeze et coûts complets. Sujet précis : Vérifier OOS. **Preuve :** Verdict honnête, sans profit fixe terminal ni fuite.
- [ ] **[ASF-108] Vérifier le forward-paper** (P1, ancien T108). **Action :** Séparer TRAIN/OOS/forward, freeze et coûts complets. Sujet précis : Vérifier le forward-paper. **Preuve :** Verdict honnête, sans profit fixe terminal ni fuite.
- [ ] **[ASF-109] Vérifier les coûts all-in** (P1, ancien T109). **Action :** Séparer TRAIN/OOS/forward, freeze et coûts complets. Sujet précis : Vérifier les coûts all-in. **Preuve :** Verdict honnête, sans profit fixe terminal ni fuite.
- [ ] **[ASF-110] Vérifier la capacité économique** (P1, ancien T110). **Action :** Séparer TRAIN/OOS/forward, freeze et coûts complets. Sujet précis : Vérifier la capacité économique. **Preuve :** Verdict honnête, sans profit fixe terminal ni fuite.
- [ ] **[ASF-111] Certifier les verdicts** (P1, ancien T111). **Action :** Séparer TRAIN/OOS/forward, freeze et coûts complets. Sujet précis : Certifier les verdicts. **Preuve :** Verdict honnête, sans profit fixe terminal ni fuite.
- [ ] **[ASF-112] Préserver les refus honnêtes** (P1, ancien T112). **Action :** Séparer TRAIN/OOS/forward, freeze et coûts complets. Sujet précis : Préserver les refus honnêtes. **Preuve :** Verdict honnête, sans profit fixe terminal ni fuite.

### 15 certification des cinq CMD

- [ ] **[ASF-113] Tester LANCER_COLLECTEURS_COPY_VAULT.cmd** (P4, ancien T113). **Action :** Tester chaque lanceur en succès et échec sur OS cible. Sujet précis : Tester LANCER_COLLECTEURS_COPY_VAULT.cmd. **Preuve :** Effets, codes retour, portabilité et absence de PC distant.
- [ ] **[ASF-114] Tester LANCER_LAB_QUANT_COPY_VAULT.cmd** (P4, ancien T114). **Action :** Tester chaque lanceur en succès et échec sur OS cible. Sujet précis : Tester LANCER_LAB_QUANT_COPY_VAULT.cmd. **Preuve :** Effets, codes retour, portabilité et absence de PC distant.
- [ ] **[ASF-115] Tester LANCER_HYPERSMART.cmd** (P4, ancien T115). **Action :** Tester chaque lanceur en succès et échec sur OS cible. Sujet précis : Tester LANCER_HYPERSMART.cmd. **Preuve :** Effets, codes retour, portabilité et absence de PC distant.
- [ ] **[ASF-116] Tester POUSSER-GITHUB-FORCE.cmd** (P4, ancien T116). **Action :** Tester chaque lanceur en succès et échec sur OS cible. Sujet précis : Tester POUSSER-GITHUB-FORCE.cmd. **Preuve :** Effets, codes retour, portabilité et absence de PC distant.
- [ ] **[ASF-117] Tester ALINA_SYNC_COMPLETE.cmd** (P4, ancien T117). **Action :** Tester chaque lanceur en succès et échec sur OS cible. Sujet précis : Tester ALINA_SYNC_COMPLETE.cmd. **Preuve :** Effets, codes retour, portabilité et absence de PC distant.
- [ ] **[ASF-118] Tester les interactions** (P4, ancien T118). **Action :** Tester chaque lanceur en succès et échec sur OS cible. Sujet précis : Tester les interactions. **Preuve :** Effets, codes retour, portabilité et absence de PC distant.
- [ ] **[ASF-119] Tester les échecs** (P4, ancien T119). **Action :** Tester chaque lanceur en succès et échec sur OS cible. Sujet précis : Tester les échecs. **Preuve :** Effets, codes retour, portabilité et absence de PC distant.
- [ ] **[ASF-120] Tester Windows et Linux selon les responsabilités** (P4, ancien T120). **Action :** Tester chaque lanceur en succès et échec sur OS cible. Sujet précis : Tester Windows et Linux selon les responsabilités. **Preuve :** Effets, codes retour, portabilité et absence de PC distant.

### 16 performance, sécurité logicielle et CI

- [ ] **[ASF-121] Vérifier SQLite et stockage** (P4, ancien T121). **Action :** Tester CI, sécurité, quotas, stockage et SHA. Sujet précis : Vérifier SQLite et stockage. **Preuve :** Tests de refus et receipts valides liés à HEAD.
- [ ] **[ASF-122] Vérifier les performances CPU/RAM/I/O** (P4, ancien T122). **Action :** Tester CI, sécurité, quotas, stockage et SHA. Sujet précis : Vérifier les performances CPU/RAM/I/O. **Preuve :** Tests de refus et receipts valides liés à HEAD.
- [ ] **[ASF-123] Vérifier la reprise des processus** (P4, ancien T123). **Action :** Tester CI, sécurité, quotas, stockage et SHA. Sujet précis : Vérifier la reprise des processus. **Preuve :** Tests de refus et receipts valides liés à HEAD.
- [ ] **[ASF-124] Vérifier la sécurité des dépendances** (P4, ancien T124). **Action :** Tester CI, sécurité, quotas, stockage et SHA. Sujet précis : Vérifier la sécurité des dépendances. **Preuve :** Tests de refus et receipts valides liés à HEAD.
- [ ] **[ASF-125] Vérifier Ruff, pytest et coverage** (P4, ancien T125). **Action :** Tester CI, sécurité, quotas, stockage et SHA. Sujet précis : Vérifier Ruff, pytest et coverage. **Preuve :** Tests de refus et receipts valides liés à HEAD.
- [ ] **[ASF-126] Vérifier les gates GitHub** (P4, ancien T126). **Action :** Tester CI, sécurité, quotas, stockage et SHA. Sujet précis : Vérifier les gates GitHub. **Preuve :** Tests de refus et receipts valides liés à HEAD.
- [ ] **[ASF-127] Vérifier les workflows complémentaires** (P4, ancien T127). **Action :** Tester CI, sécurité, quotas, stockage et SHA. Sujet précis : Vérifier les workflows complémentaires. **Preuve :** Tests de refus et receipts valides liés à HEAD.
- [ ] **[ASF-128] Vérifier les preuves sur SHA exact** (P4, ancien T128). **Action :** Tester CI, sécurité, quotas, stockage et SHA. Sujet précis : Vérifier les preuves sur SHA exact. **Preuve :** Tests de refus et receipts valides liés à HEAD.

### 17 tests E2E, clôture et amélioration continue

- [ ] **[ASF-129] Valider collecte vers SAFE vers Release** (P0, ancien T129). **Action :** Exécuter parcours E2E et réconcilier les résultats. Sujet précis : Valider collecte vers SAFE vers Release. **Preuve :** Toutes les gates prouvées et aucun DONE fictif.
- [ ] **[ASF-130] Valider clone vers AlinaSync vers laboratoire** (P0, ancien T130). **Action :** Exécuter parcours E2E et réconcilier les résultats. Sujet précis : Valider clone vers AlinaSync vers laboratoire. **Preuve :** Toutes les gates prouvées et aucun DONE fictif.
- [ ] **[ASF-131] Valider wallet vers signal vers PAPER vers ledger vers dashboard** (P1, ancien T131). **Action :** Exécuter parcours E2E et réconcilier les résultats. Sujet précis : Valider wallet vers signal vers PAPER vers ledger vers dashboard. **Preuve :** Toutes les gates prouvées et aucun DONE fictif.
- [ ] **[ASF-132] Valider événement vers feature vers signal vers ablation vers OOS** (P1, ancien T132). **Action :** Exécuter parcours E2E et réconcilier les résultats. Sujet précis : Valider événement vers feature vers signal vers ablation vers OOS. **Preuve :** Toutes les gates prouvées et aucun DONE fictif.
- [ ] **[ASF-133] Valider les pannes et le déterminisme** (P0, ancien T133). **Action :** Exécuter parcours E2E et réconcilier les résultats. Sujet précis : Valider les pannes et le déterminisme. **Preuve :** Toutes les gates prouvées et aucun DONE fictif.
- [ ] **[ASF-134] Exécuter l'audit anti-oubli** (P0, ancien T134). **Action :** Exécuter parcours E2E et réconcilier les résultats. Sujet précis : Exécuter l'audit anti-oubli. **Preuve :** Toutes les gates prouvées et aucun DONE fictif.
- [ ] **[ASF-135] Certifier la clôture technique** (P0, ancien T135). **Action :** Exécuter parcours E2E et réconcilier les résultats. Sujet précis : Certifier la clôture technique. **Preuve :** Toutes les gates prouvées et aucun DONE fictif.
- [ ] **[ASF-136] Continuer l'amélioration scientifique** (P2, ancien T136). **Action :** Exécuter parcours E2E et réconcilier les résultats. Sujet précis : Continuer l'amélioration scientifique. **Preuve :** Toutes les gates prouvées et aucun DONE fictif.

### 18 — gel et recherche continue

- [ ] **[ASF-137] Geler chaque gain net même minime** (P1). **Action :** Enregistrer snapshot immuable d'expérience positive avec SHA, dataset, fenêtres, seed, configuration et coûts. **Preuve :** Snapshot et résultat rejouables.
- [ ] **[ASF-138] Geler sans promouvoir abusivement** (P1). **Action :** Différencier FREEZE_EXPLORATORY et CHAMPION_VERIFIED. **Preuve :** Impossible de promouvoir TRAIN sans OOS/forward.
- [ ] **[ASF-139] Supprimer les objectifs financiers fixes** (P0). **Action :** Retirer +4 et +5 USD/jour comme conditions de DONE; garder tous les gates. **Preuve :** Tests sur petit gain, perte, résultat inconnu.
- [ ] **[ASF-140] Préserver anciens champions** (P1). **Action :** Conserver configurations, lignée, gagnants et perdants append-only. **Preuve :** Toute expérience peut être restaurée.
- [ ] **[ASF-141] Mesurer stabilité de chaque gain** (P1). **Action :** Contrôler intervalle, risque, drawdown, liquidatabilité et sensibilité. **Preuve :** Pas de promotion d'amélioration fragile.
- [ ] **[ASF-142] Relancer Discovery après gel** (P1). **Action :** Faire repartir recherche de mécanismes après chaque snapshot ou pivot. **Preuve :** Au moins deux cycles rejouables.
- [ ] **[ASF-143] Forcer challengers et pivots** (P1). **Action :** Après stagnation, 4 challengers orthogonaux; jamais retuning en boucle. **Preuve :** Déclencheurs ledger testés.
- [ ] **[ASF-144] Comptabiliser tous les essais** (P1). **Action :** Suivre trial_count, seeds, paramètres, rejets et nuls. **Preuve :** Anti-overfitting utilise tous les essais.
- [ ] **[ASF-145] Refreeze après feedback OOS** (P1). **Action :** Toute OOS réutilisée pour régler perd son indépendance. **Preuve :** Nouvelle période disjointe exigée.
- [ ] **[ASF-146] Batchs scientifiques sans tours IA** (P1). **Action :** Calculer CPU-first et produire résumés compacts. **Preuve :** Même entrée égale même résultat.
- [ ] **[ASF-147] Certifier 5 lanceurs opérateur** (P1). **Action :** Tester collecteur, labo, HyperSmart paper, Git code sync et AlinaSync. **Preuve :** Tests E2E positifs et négatifs.
- [ ] **[ASF-148] Prouver SAFE→AlinaSync→replay** (P1). **Action :** Télécharger un asset SAFE, vérifier, décompresser, indexer et rejouer. **Preuve :** Hash, taille et sortie replay corrects.
- [ ] **[ASF-149] Redéfinir la certification économique** (P1). **Action :** Séparer qualité de preuve, edge net et recherche continue. **Preuve :** PROVEN/PROMISING/MORE_DATA/UNMEASURABLE/REJECTED vérifiés.
- [ ] **[ASF-150] Interdire le saut des tâches** (P1). **Action :** Chaque tâche exige receipt, commande, fichiers, tests et SHA avant VERIFIED_DONE. **Preuve :** Validation échoue sur un tag ignoré.

## 40 tâches supplémentaires, anomalies et vérifications

- [ ] **[AUD-001] Docs Codex multi-familles** (P0, CONFIRME). **Fichier/preuve :** `docs/CODEX_GOAL_OBJECTIVE_V31.txt`. **Action :** Retirer objectif trois familles +4$/j; conserver CopyVault seul. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-002] Runbook cible +5$/jour** (P0, CONFIRME). **Fichier/preuve :** `docs/CODEX_GOAL_RUNBOOK.md`. **Action :** Éliminer cible fixe et imposer gel puis découverte continue. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-003] Spec canonique cible +5$/jour** (P0, CONFIRME). **Fichier/preuve :** `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`. **Action :** Modifier en place objectifs et contrat de gel, sans spec parallèle. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-004] OBJECTIF et CURRENT_STATE obsolètes** (P0, CONFIRME). **Fichier/preuve :** `OBJECTIF.md ; docs/CURRENT_STATE.md`. **Action :** Mettre à jour les objectifs et HEAD de référence. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-005] Certificateur hardcode +5$/jour** (P0, CONFIRME). **Fichier/preuve :** `tools/run_daily_economic_certification.py`. **Action :** Séparer gates de preuve du target fixe et tester les petits gains. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-006] Tasklist ancienne multi-familles ACTIVE** (P1, CONFIRME). **Fichier/preuve :** `docs/TASKLIST_ACTIVE.md`. **Action :** Marquer tableau de juillet historique et non autoritatif. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-007] Ancien scoreboard trois familles** (P0, CONFIRME_HISTORIQUE). **Fichier/preuve :** `catalog/ANALYSIS_SCOREBOARD_RECEIPT.json`. **Action :** Ne pas projeter epoch7 comme scope courant epoch8. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-008] Aucun champion CopyVault validé** (P1, CONFIRME). **Fichier/preuve :** `catalog/ECONOMIC_IMPROVEMENT_LEDGER.json`. **Action :** Expliquer champion=null et NON_MESURABLE; pas de gain inventé. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-009] 45199 PARTIAL en attente** (P0, CONFIRME). **Fichier/preuve :** `catalog/QUARANTINE_AUDIT.json`. **Action :** Réparer si prouvable; sinon exclure et classifier. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-010] 15052 REJECT inventoriés** (P0, CONFIRME). **Fichier/preuve :** `catalog/QUARANTINE_AUDIT.json`. **Action :** Tester leur exclusion de tous les inputs de replay/backtest. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-011] RECORD_COUNT_PATCH >95MB** (P0, CONFIRME_LOG). **Fichier/preuve :** `tools/merge_measured_catalog_patches.py`. **Action :** Partitionner les patches avec écriture atomique; test grand fichier. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-012] Publication taille échoue après mesure** (P0, CONFIRME_LOG). **Fichier/preuve :** `.github/workflows/uncompressed-size-v2.yml`. **Action :** Reprendre données déjà mesurées sans rescanner; test publication. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-013] SHA-256 moteur Windows inattendu** (P1, CONFIRME_LOG_ANCIEN). **Fichier/preuve :** `POUSSER-GITHUB-FORCE.cmd`. **Action :** Tracer contenu attendu vs réel; réparer sans supprimer protection hash. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-014] Delta UNKNOWN vs OPEN** (P1, CONFIRME_LOG_ANCIEN). **Fichier/preuve :** `tests/test_user_fills_live_scan.py`. **Action :** Tracer la causalité, conserver UNKNOWN quand preuve insuffisante. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-015] Tests réclament lanceurs disparus** (P2, CONFIRME_LOG_ANCIEN). **Fichier/preuve :** `tests/test_recherche_continue.py`. **Action :** Aligner tests aux entrypoints officiels sans recréer de doublon. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-016] Coverage shards rouges** (P1, A_REVALIDER). **Fichier/preuve :** `.github/workflows/coverage-parallel-probe.yml`. **Action :** Rejouer tests échoués sur SHA courant; corriger cause. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-017] Reconciliation Release échoue** (P0, CAUSE_A_CONFIRMER). **Fichier/preuve :** `GitHub run 41522080188`. **Action :** Obtenir stack trace du rebuild et réparer recovery atomique. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-018] Copy-Vault V2 n'est plus collecteur** (P0, MIGRATION). **Fichier/preuve :** `.github/workflows/collect-copy-vault-v2.yml`. **Action :** Prouver remplacement réel par campagnes résumables. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-019] Market Data V2 n'est plus collecteur** (P0, MIGRATION). **Fichier/preuve :** `.github/workflows/collect-market-data-v2.yml`. **Action :** Prouver couverture native et publication par nouveaux workers. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-020] Event Intelligence V2 diagnostic seul** (P1, MIGRATION). **Fichier/preuve :** `.github/workflows/collect-event-intelligence-v2.yml`. **Action :** Prouver que sources sont effectivement collectées. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-021] Worker continue-on-error** (P0, RISQUE). **Fichier/preuve :** `.github/workflows/resumable-campaign-worker.yml`. **Action :** Injecter panne unité: aucune erreur ne devient SAFE ou DONE. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-022] Receipt worker if false** (P0, RISQUE). **Fichier/preuve :** `.github/workflows/resumable-campaign-worker.yml`. **Action :** Vérifier voie active de remplacement avec receipt atomique. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-023] Dispatch fallback 403/429** (P0, RISQUE). **Fichier/preuve :** `.github/workflows/analysis-stage-controller.yml`. **Action :** Tester watchdog/schedule sans campagne perdue. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-024] Diagnostics avec permission write** (P2, CONFIRME_CONFIGURATION). **Fichier/preuve :** `.github/workflows/collect-market-data-v2.yml`. **Action :** Réduire permissions au minimum nécessaire. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-025] Vieux self-hosted encore versionnés** (P2, DESACTIVE_HISTORIQUE). **Fichier/preuve :** `.github/workflows/alina-self-hosted.yml`. **Action :** Prouver tous chemins désactivés et pas de PC accessible. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-026] Cadence controller très fréquente** (P2, RISQUE). **Fichier/preuve :** `.github/workflows/resumable-campaign-controller.yml`. **Action :** Mesurer coût runs vides puis optimiser sans couper collecte. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-027] FILE_PRESENT ≠ HEALTHY** (P1, CONFIRME_CONTRAT). **Fichier/preuve :** `docs/source-capability-matrix.json`. **Action :** Prouver véritables flux, santé et compatibilité replay. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-028] Event Intelligence STRUCTURAL_ONLY** (P1, CONFIRME). **Fichier/preuve :** `docs/event-intelligence-120-status.json`. **Action :** Vérifier source, feature, consommateur et ablation utile. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-029] Frais historiques à revalider** (P1, A_REVALIDER). **Fichier/preuve :** `catalog/ANALYSIS_SCOREBOARD_RECEIPT.json`. **Action :** Actualiser coûts ou déclarer inconnu. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-030] Limites API fills Hyperliquid** (P0, RISQUE). **Fichier/preuve :** `docs/HYPERLIQUID_API_CONTRACT_CURRENT.md`. **Action :** Tester pagination 500/2000, même timestamp, plafond et dédup. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-031] Snapshots WebSocket isSnapshot** (P0, RISQUE). **Fichier/preuve :** `src/hl_observer/collection`. **Action :** Tester ack, reconnexion, backfill, dédup causal. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-032] WS 10 utilisateurs uniques** (P1, RISQUE). **Fichier/preuve :** `src/hl_observer/collection`. **Action :** Contrôler globalement connexions et souscriptions. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-033] Receipt santé potentiellement absent** (P0, A_VERIFIER). **Fichier/preuve :** `catalog/DATASET_HEALTH_RECEIPT.json`. **Action :** Contrôler fichier réel, schéma et fail-closed sur absent. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-034] Attribution SHA des campagnes** (P0, RISQUE). **Fichier/preuve :** `.github/workflows/resumable-campaign-worker.yml`. **Action :** Tester code SHA et dataset selection non dérivants. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-035] Quarantaine partitionnée** (P0, RISQUE). **Fichier/preuve :** `catalog/QUARANTINE_AUDIT.json`. **Action :** Vérifier hashes, 8 partitions et compteurs globaux. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-036] AlinaSync→BookLoader→Replay** (P0, RISQUE). **Fichier/preuve :** `tools/sync_complete_clone.py`. **Action :** Prouver un parcours réel du shard SAFE au résultat replay. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-037] Découverte continue après FREEZE** (P0, CHANGEMENT_DEMANDE). **Fichier/preuve :** `tools/codex_hypothesis_ledger.py`. **Action :** Tester deux cycles GEL→DISCOVERY sans stopper recherche. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-038] Release partiellement publiée** (P0, RISQUE). **Fichier/preuve :** `.github/workflows/resumable-campaign-worker.yml`. **Action :** Crash entre asset, manifest, receipt et reprise idempotente. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-039] Rapports auto-publication en boucle** (P1, RISQUE). **Fichier/preuve :** `.github/workflows/alina-canonical-closure-report.yml`. **Action :** Vérifier absence commit vide, trigger loop et SHA trompeur. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.
- [ ] **[AUD-040] Issue ccxt exécuteur** (P0, ISSUE_OUVERTE). **Fichier/preuve :** `GitHub issue #42`. **Action :** Tracer package/transitive imports et empêcher ordre réel. **Validation :** test dédié sur le HEAD courant, preuve SHA-bound et garde-fou fail-closed.

## Sources et incidents observés

GitHub Actions : `41512996633` (ValueError `CATALOG_PATCH_NEEDS_PARTITION: RECORD_COUNT_PATCH.json exceeds 95 MB` après mesure), `41489430128` (SHA Windows inattendu), `41489664831` (deux échecs de tests dans un ancien coverage shard), `41522080188` (échec rebuild de l'index, cause à retrouver). Sur `catalog/QUARANTINE_AUDIT.json`, 45 199 PARTIAL `PENDING` et 15 052 REJECT étaient recensés, sans droit d'utilisation en backtest. Le ledger Copy-Vault inspecté n'a pas de champion certifié. Ces observations doivent être revalidées si HEAD ou données changent.

Docs officielles : https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint ; https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions ; https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits ; https://docs.github.com/en/actions ; https://sqlite.org/backup.html.

**Contrat de fin :** chaque tag vérifié ou explicitement BLOCKED, chaque diff contrôlé, aucun nouveau doublon, aucun profit inventé, aucun REJECT admis, aucune dépendance PC/self-hosted.
