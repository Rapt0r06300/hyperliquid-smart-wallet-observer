# Non-Viable Trades Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent stale or non-viable evidence from entering Alina replays while recovering every release asset that can be proven SAFE and replay-compatible.

**Architecture:** Keep the existing single-repository catalog, collectors, replay adapters, and Release restore path. Add source-binding gates around generated metrics, make restore inventory classification fail-closed and physically separate usable evidence from quarantine/diagnostics, and lock the existing native multi-trade splitter into four-venue integration tests.

**Tech Stack:** Python 3.12 standard library, pytest, GitHub Actions, GitHub Releases.

**Spec:** `docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md`

## Global Constraints

- PAPER / READ-ONLY / FAIL-CLOSED; no real or testnet execution.
- GitHub-hosted runners only; no self-hosted runner or user-PC dependency.
- Keep collection running; do not change phase from COLLECT.
- Reuse the canonical runtime and catalog; do not create a parallel data system.
- Never promote missing, corrupt, unverified, or non-replayable evidence to SAFE.
- Do not import the retired Dataset V2 repository.

## Review Focus

- A metrics file generated from an older index must be rejected before publication.
- Missing or contradictory manifest evidence must route assets to quarantine, never usable restore.
- ZIP and shard-member bytes must be verified independently before usable materialization.
- Interrupted downloads must resume without turning partial bytes into verified assets.
- Multi-trade source frames must produce every native trade exactly once on all four venues.

---

### Task 1: Bind metrics publication to the current catalog

**Files:**
- Modify: `tools/build_catalog_metrics.py`
- Modify: `tests/test_dataset_metrics.py`
- Modify: `.github/workflows/dataset-metrics-v2.yml`

**Interfaces:**
- Produces: `verify_metrics_source(index_path, metrics_path) -> dict[str, Any]`
- Consumes: existing `source_index_sha256` and `TOTAL_SHARDS` metrics fields.

- [x] Add a failing test for stale index SHA and shard-count mismatch.
- [x] Implement the fail-closed verifier.
- [x] Rebuild metrics after every fetch/reset immediately before commit and push.
- [x] Run dataset metrics tests.

### Task 2: Restore only proven usable evidence

**Files:**
- Modify: `tools/restore_alina.py`
- Modify: `tests/test_restore_alina.py`
- Modify: `RESTORE_ALINA.cmd`
- Modify: `RESTORE_ALINA.sh`

**Interfaces:**
- Produces: classified inventory with `usable`, `quarantine`, `diagnostic`, and `excluded` outcomes.
- Produces: resumable verified downloads and a non-success exit when usable restoration is incomplete.

- [x] Add failing tests for SAFE/replay filtering, unknown evidence, ZIP corruption, and interrupted resume.
- [x] Classify from SHA-bound RUN_MANIFEST rows without inventing evidence.
- [x] Download into separate roots and materialize only verified usable assets.
- [x] Report present, downloaded, verified, missing, quarantined, and excluded assets.
- [x] Run restore tests.

### Task 3: Prove four-venue multi-trade wiring

**Files:**
- Add: `tests/test_native_trade_batch_split.py`
- Modify only if a test fails: `src/hl_observer/collection/native_market_tape.py` or `native_venue_coordinator.py`

**Interfaces:**
- Consumes: `native_tick_envelopes(venue, payload) -> list[TickEnvelope]`.
- Proves: per-row native identity, shared batch digest, stable batch index, no truncation.

- [x] Add deterministic cases for Bybit, OKX, Gate, and Bitget.
- [x] Verify every source row becomes one replay event.
- [x] Run collector/replay tests.

### Task 4: Final gates and publication

**Files:**
- Modify: canonical spec acceptance notes only if behavior changes require it.

**Interfaces:**
- Consumes: Tasks 1–3 verification evidence.

- [x] Run targeted tests, compilation, workflow policy scans, and the available project suite.
- [x] Inspect the real diff and confirm no execution/self-hosted path was enabled.
- [ ] Create one non-empty commit against the latest real `main`.
- [ ] Update `main`, verify the remote HEAD/tree, and inspect triggered workflow results.
- [ ] Re-read catalog metrics/quarantine counters and report only measured gains.

## Checkpoint vérifié — reprise du 9 octobre 2026

État de la mission : **PARTIELLEMENT IMPLÉMENTÉE — pas de clôture économique ni de réparation historique prouvée**.

- Phase distante observée : `COLLECT`, epoch `8` (le contrôleur de collecte n'a pas été modifié ni volontairement arrêté).
- Catalogue lu sur `main` : 63 186 shards ; 36 666 SAFE ; 14 078 PARTIAL ; 12 442 REJECT.
- Métriques `DATA_METRICS.json` : 12 036 965 trades comptabilisés, dont 6 536 457 classés SAFE ; `DATA_METRICS` et `QUARANTINE_CAUSES` annoncent le même SHA de source.
- Réparations historiques **prouvées pendant cette reprise** : 0 ; le nombre de shards encore non SAFE reste 26 520 dans le catalogue contrôlé.
- Les 25 tests de restauration ont réussi dans [GitHub Actions run 37980510897](https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer/actions/runs/37980510897), puis **29 tests** de restauration et de découpage des trades multi-venues ont réussi dans [GitHub Actions run 37980749315](https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer/actions/runs/37980749315).
- Nouveaux contrôles : manifeste obligatoire pour Release `data-v2`, IDs dupliqués refusés, membres ZIP ambigus refusés, anciennes matérialisations SAFE révoquées mises en quarantaine, cross-check systématique de la qualification de chaque shard contre le **catalogue actuel lié au SHA-256 des métriques** lors de `RESTORE_ALINA.cmd`.
- Vérifications restantes **non réalisées** : restauration exhaustive des Release assets sur une nouvelle machine, vérification du catalogue actuel contre tous les blobs binaires, réparation/backfill réel des trous L2 et trades historiques, gains SAFE avant/après, tests de replay/OOS/forward et rentabilité nette.
- Limitation de cette intervention : accès GitHub fichiers/commits/CI possible, mais pas de checkout exécutable complet avec toutes les archives lourdes ni de capacité d'exécution directe des traitements historiques sur celles-ci. Ne pas présenter le succès CI ciblé comme une qualification de 26 520 shards.
- La phase `COLLECT` doit rester active ; ne lancer aucune phase `ANALYZE` et ne pas supprimer les preuves d'origine.

Suite prioritaire : exécuter une réconciliation historique GitHub-hosted bornée sur les originaux vérifiables, mesurer par `venue × family × cause` les promotions prouvées, puis refaire l'inventaire et les validations de replays économiques. Toute promotion nécessite identité, hashes, intégrité chronologique et compatibilité replay vérifiés.
