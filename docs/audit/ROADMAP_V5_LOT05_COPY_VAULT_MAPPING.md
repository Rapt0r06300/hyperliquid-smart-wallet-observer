# ROADMAP V5 LOT 05 — Copy-Vault H—T-40 mapping

Checkpoint de mapping technique pour AgiFlow `H—T-40` sur `main`.

Ce document **ne remplace pas** les contrats machine. Il relie les exigences V5 §10 / 776+ aux surfaces réellement actives du dépôt afin d'éviter de réimplémenter des contrôles déjà présents ou de ressusciter des hypothèses tuées.

## Invariants du lot

- PAPER / READ-ONLY uniquement ; aucune exécution réelle.
- +4 USD / 3×4 / PnL positif n'est pas une condition de Done de H—T-40.
- Les coûts complets, la liquidatabilité, la capacité entrée/sortie et les timestamps causaux restent des préconditions d'admission.
- TRAIN est séparé de OOS/forward ; le sélecteur vNext ne lit pas le held-out avant freeze.
- Les preuves sont familiales Copy-Vault ; aucune preuve d'une autre famille n'est réutilisée pour valider Copy-Vault.

## Mapping §10 / 776+

| Contrôle | Statut | Surface canonique | Preuve / test |
|---|---|---|---|
| Hypothèse simple whitelist détruite conservée | **KILLED / HISTORICAL** | `src/hl_observer/backtesting/copy_vault_hypothesis_registry.py` (`copy_vault_simple_whitelist`) | registre retourne `KILLED`, `HISTORICAL_NEGATIVE_EVIDENCE`; `require_runnable_copy_vault_hypothesis()` refuse tout statut non `ACTIVE` |
| Hypothèse courante | **ACTIVE** | même registre + `copy_vault_vnext_train.py` | mécanisme exact `copy_vault_vnext_causal_multiwallet_consensus`; `economic_vnext_pack.py` appelle `require_runnable_copy_vault_hypothesis()` avant le sélecteur |
| Hypothèse inconnue | **CORRIGÉ / FAIL-CLOSED** | `copy_vault_hypothesis_registry.py` | disposition `UNREGISTERED`, non runnable |
| Lifecycle leader / sortie causale | **DÉJÀ IMPLÉMENTÉ** | `copy_vault_v5_lifecycle_train.py` | variante V5 TRAIN-only ; sortie liée aux réductions/fermetures du leader, non au futur PnL |
| Consensus strictement causal | **DÉJÀ IMPLÉMENTÉ** | `copy_vault_vnext_train.py::admit_consensus_train_rows` | uniquement lignes antérieures (`age > 0`) dans fenêtre déclarée ; test `test_copy_vault_vnext_selection_ignore_totalement_oos_et_exige_consensus_prior_only` |
| Freshness / timestamps causaux | **CORRIGÉ** | `copy_vault_vnext_train.py::_execution_evidence_complete` + `copy_vault_protocol.py` | `MAX_REFERENCE_LAG_MS` et `MAX_TARGET_LAG_MS` appliqués aux références, entrée et sortie ; `tests/test_copy_vault_vnext_freshness_limits.py` |
| Entités publiques liées | **DÉJÀ IMPLÉMENTÉ** | `following/entity_consensus.py` via `_identity_vote` / `_causal_entity_keys` | `test_copy_vnext_does_not_count_same_public_entity_as_independent_wallets` |
| Behavioral fingerprint / faux leaders | **CORRIGÉ / FAIL-CLOSED** | `copy_vault_vnext_integrity.py::_behavioral_fingerprint_evidence` + `research/wallet_fingerprint.py` | preuve behavioral obligatoire et complète ; wallets comportementalement liés doivent partager la même entité ; `test_missing_behavioral_fingerprint_evidence_fails_closed`, `test_behaviorally_related_wallets_require_same_declared_entity` |
| Sybils / wallets miroirs | **CORRIGÉ / FAIL-CLOSED** | `copy_vault_universe_integrity.py` + `research/wallet_integrity.py::detecter_sybils` | paires corrélées non normalisées => `SYBIL_ENTITY_NORMALIZATION_MISSING`; corrélations malformées/non finies refusées |
| Universe coverage | **CORRIGÉ / FAIL-CLOSED** | `copy_vault_vnext_integrity.py` + `copy_vault_universe_integrity.py` | `universe_complete=True` exigé, survivants hors univers et cohortes incomplètes refusés ; tests d'intégrité vNext |
| Survivorship bias | **CORRIGÉ / FAIL-CLOSED** | `copy_vault_universe_integrity.py` + `correction_survivorship()` | survivants comparés à l'univers complet ; absence d'univers => refus |
| Wallets liquidés dans cohorte historique | **CORRIGÉ / FAIL-CLOSED** | `copy_vault_universe_integrity.py` + `inclure_wallets_liquides()` | `cohorte_suspecte=True` => `LIQUIDATED_WALLET_COVERAGE_UNPROVEN`; test ajouté par commits `84aff543` / `8ea5e34b` |
| Copyability d'entrée/sortie | **DÉJÀ IMPLÉMENTÉ / MESURABLE** | `copy_vault_vnext_train.py::_train_rows` + `_execution_evidence_complete` | exige `liquidatable_net=True`, prix d'entrée/sortie, notionnel, capacité entrée/sortie >= notionnel, latence observable ; tests `test_copy_vnext_fail_closed_when_execution_capacity_is_missing`, `test_copy_vnext_refuses_capacity_below_notional`, `test_copy_vnext_fail_closed_when_execution_evidence_is_incomplete` |
| Coûts complets / PnL net | **DÉJÀ IMPLÉMENTÉ / FAIL-CLOSED** | `copy_vault_vnext_train.py::_reconciled` | `gross - fees - spread - slippage - latency == net`; coûts absents, négatifs ou non finis refusés avant scoring |
| Déduplication économique | **DÉJÀ IMPLÉMENTÉ** | `copy_vault_vnext_train.py::_train_rows` | `trade_id` unique + `metaorder_id` compté une seule fois ; `test_copy_vnext_counts_each_metaorder_only_once_for_train_statistics` |
| Concentration coin | **DÉJÀ IMPLÉMENTÉ** | `copy_vault_vnext_train.py` | `MAX_COIN_TRADE_SHARE=0.65`, gate dans `train_statistics_eligible`; résultat expose `largest_coin_trade_share` |
| Concentration wallet/entité | **DÉJÀ IMPLÉMENTÉ / ENTITY-NORMALIZED** | `_causal_entity_keys`, `_concentration`, `MAX_VAULT_TRADE_SHARE=0.50` | la concentration utilise `entity_concentration_key_at_signal`; `test_copy_vnext_persists_causal_economic_entity_key_for_concentration` |
| Concentration gagnants / anti-one-hit | **DÉJÀ IMPLÉMENTÉ** | `train_statistics.summarize_train_rows` + `MAX_TOP_POSITIVE_SHARE=0.60` | `top_positive_trade_share` doit respecter le plafond avant éligibilité |
| Multiple testing | **DÉJÀ IMPLÉMENTÉ** | `copy_vault_vnext_train.py` + `train_statistics.summarize_train_rows` | grille fixe `CONSENSUS_WINDOWS_MS × MIN_DISTINCT_WALLETS`, `trial_count=len(grid)` transmis aux statistiques avec `FAMILY_ALPHA=0.05` |
| Robustesse temporelle minimale | **DÉJÀ IMPLÉMENTÉ** | `copy_vault_vnext_train.py` | `MIN_TRAIN_TRADES`, `MIN_DISTINCT_DAYS`, `MIN_DISTINCT_REGIMES`, LCB > 0 et PF > 1 pour l'éligibilité TRAIN |
| Séparation TRAIN / OOS / forward | **DÉJÀ IMPLÉMENTÉ** | `_train_rows` + sortie du sélecteur | seules lignes `segment=train`; `selection_scope=TRAIN_ONLY_PRE_FREEZE`, `heldout_evaluated=False`; test injectant un énorme gagnant OOS sans effet sur la sélection |
| Freeze physique | **DÉJÀ IMPLÉMENTÉ / FAIL-CLOSED** | `copy_vault_vnext_train.py` + `gate_copy_vault_candidate()` | pas de candidat si base non physiquement gelée ; intégrité invalide efface `freeze_candidate_sha256` et force `physical_freeze_allowed=False` |
| Wiring avant persistance | **CORRIGÉ** | `economic_vnext_pack.py` | `evaluate_copy_vault_vnext_integrity(copy_raw)` puis gate vNext + V5 avant `paths = { ... }`; test `test_economic_pack_wires_integrity_before_copy_reports` |
| PAPER/read-only | **DÉJÀ IMPLÉMENTÉ** | sorties des gates/sélecteurs | `paper_read_only=True`, `real_execution=False`; aucune primitive d'ordre dans ces surfaces |

## Acceptance criteria H—T-40

### AC1 — §10 + 776+ mappés au code courant

**PASS technique par mapping** : le présent document couvre les axes explicitement portés par H—T-40 et les relie aux modules/tests actifs. Les anciens modules spécialisés (par ex. `copyability_kill_switch.py`, `copyability_erosion_monitor.py`, `coin_concentration_ceiling.py`, `vault_concentration_ceiling.py`) restent du patrimoine utile mais ne sont pas utilisés comme preuve unique lorsqu'un gate vNext canonique couvre déjà le même risque.

### AC2 — faux leaders, entités liées, concentration, survivorship, copyability, causalité

**PASS technique par code/tests existants + corrections E2** :

- faux leaders / behavioral : fail-closed ;
- entités liées / sybils : normalisation obligatoire ;
- concentration : coin + entité causale + top-positive ;
- survivorship : univers complet + wallets liquidés ;
- copyability : liquidatable net + profondeur/capacité entrée/sortie + coûts complets ;
- causalité : strictement prior-only + plafonds de lag.

### AC3 — hypothèses tuées traçables

**PASS technique** : registre familial machine-enforced. La simple whitelist est `KILLED/HISTORICAL`; une hypothèse inconnue est `UNREGISTERED` et non runnable. Aucune hypothèse tuée ne peut redevenir exécutable par simple renommage/référence.

### AC4 — Done exact-SHA indépendant du PnL

**PARTIAL au moment de ce checkpoint** : le contrat technique est respecté, mais le passage AgiFlow à Done doit attendre la vérification exact-SHA post-commit et une revue indépendante des preuves. Un workflow coverage global rouge pour une cause CI externe doit être enregistré honnêtement ; il ne doit ni être masqué, ni être confondu avec un échec fonctionnel Copy-Vault.

## Classification finale du lot au checkpoint

- `copy_vault_simple_whitelist`: **KILLED / HISTORICAL**.
- behavioral/entity/universe/liquidated-wallet/freshness hardening: **CORRIGÉ**.
- lifecycle, copyability executable, coûts, concentration, multiple-testing, TRAIN/held-out separation: **DÉJÀ IMPLÉMENTÉ** et réutilisé.
- anciens modules spécialisés non nécessaires au chemin vNext : **HISTORICAL / CONTEXT**, pas une seconde voie canonique.
- aucun contrôle économique n'a été relâché pour obtenir une fermeture de roadmap.
