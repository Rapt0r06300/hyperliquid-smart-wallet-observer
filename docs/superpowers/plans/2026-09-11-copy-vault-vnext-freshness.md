# Copy-Vault vNext Freshness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Faire échouer fermée la sélection Copy-Vault vNext lorsque les preuves de fraîcheur dépassent les plafonds causaux immuables du protocole.

**Architecture:** Conserver la validation family-local dans `copy_vault_vnext_train.py` et réutiliser `MAX_REFERENCE_LAG_MS` / `MAX_TARGET_LAG_MS` depuis `copy_vault_protocol.py`, sans dupliquer ni modifier les seuils. Le filtre intervient avant tout scoring TRAIN afin qu'une observation stale ne contribue ni au consensus ni au PnL sélectionné.

**Tech Stack:** Python, pytest, GitHub Actions.

**Spec:** AgiFlow H—T-40 / roadmap V5 §10 + Copy-Vault 776+.

## Global Constraints

- Branche persistante `main` uniquement.
- PAPER/READ-ONLY, 0 €, aucune exécution réelle.
- Aucun affaiblissement de test/gate et aucun changement des plafonds économiques existants.
- TRAIN/OOS/forward restent séparés; aucune preuve économique partagée entre familles.

---

### Task 1: Enforcer les plafonds de fraîcheur Copy-Vault vNext

**Files:**
- Create: `tests/test_copy_vault_vnext_freshness_limits.py`
- Modify: `src/hl_observer/backtesting/copy_vault_vnext_train.py`

**Interfaces:**
- Consumes: `MAX_REFERENCE_LAG_MS`, `MAX_TARGET_LAG_MS` de `copy_vault_protocol.py`.
- Produces: `_execution_evidence_complete(row)` refuse toute ligne dont `reference_lag_ms`, `entry_target_lag_ms` ou `exit_target_lag_ms` dépasse le plafond canonique correspondant.

- [ ] **Step 1: Write the failing test**

Créer trois variantes d'une ligne TRAIN économiquement réconciliée et liquidatable, avec respectivement `reference_lag_ms = MAX_REFERENCE_LAG_MS + 1`, `entry_target_lag_ms = MAX_TARGET_LAG_MS + 1` et `exit_target_lag_ms = MAX_TARGET_LAG_MS + 1`; vérifier que `explore_copy_vault_vnext_train(...)["train_rows_seen"] == 0` pour chaque variante.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_copy_vault_vnext_freshness_limits.py`
Expected: FAIL avant implémentation, car la ligne stale est actuellement admise dans le TRAIN row set.

- [ ] **Step 3: Write minimal implementation**

Importer les deux constantes canoniques et ajouter à `_execution_evidence_complete` une condition `reference_lag_ms <= MAX_REFERENCE_LAG_MS` et deux conditions target `<= MAX_TARGET_LAG_MS`. Ne modifier aucun seuil.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_copy_vault_vnext_freshness_limits.py tests/test_copy_vault_vnext_train.py`
Expected: PASS.

- [ ] **Step 5: Regression and commit**

Run la régression Copy-Vault ciblée et vérifier les workflows exact-SHA. Commit production minimal séparé après le commit RED du test.

## Self-Review

Le plan couvre uniquement le gap freshness prouvé. Concentration, capacité/liquidatabilité/coûts, multiple testing et consensus prior-only sont déjà présents et ne sont pas réimplémentés. Aucun placeholder, aucune nouvelle surface partagée.