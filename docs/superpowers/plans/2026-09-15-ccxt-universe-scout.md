# CCXT Universe Scout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter une découverte CCXT multi-venues sûre, persistante et strictement séparée des flux natifs.

**Architecture:** Un module focalisé normalise, agrège et compare les snapshots CCXT. La CLI et les paramètres existants l’exposent sans modifier le hot path natif.

**Tech Stack:** Python 3.11, Pydantic, Typer, CCXT, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-ccxt-universe-scout-design.md`

## Global Constraints

- Discovery publique uniquement; aucun trading, endpoint privé, clé ou signature.
- CCXT ne fournit jamais de données au hot path Cross-Venue/Lead-Lag.
- Une panne de venue est isolée et tout état ambigu est fail-closed.
- Exécuter uniquement `tests/test_ccxt_universe_scout.py`.

---

### Task 1: Contrat canonique et agrégation

**Files:**
- Create: `tests/test_ccxt_universe_scout.py`
- Create: `src/hl_observer/markets/ccxt_universe.py`

**Interfaces:**
- Consumes: dictionnaires de marché retournés par `exchange.load_markets()`.
- Produces: `CanonicalCCXTMarket`, `CCXTUniverseResult`, `CCXTUniverseScout.scan()` et sérialisation JSON.

- [ ] Écrire les tests de normalisation, agrégation, diff, panne isolée et frontière native.
- [ ] Exécuter le fichier de test et confirmer l’échec attendu car le module manque.
- [ ] Implémenter modèles, normalisation, déduplication, agrégation, timeout/retry, statuts et snapshot atomique.
- [ ] Exécuter le fichier de test jusqu’à réussite.

### Task 2: Configuration, CLI et dépendance

**Files:**
- Modify: `src/hl_observer/config/settings.py`
- Modify: `src/hl_observer/config/loader.py`
- Modify: `config/settings.example.yaml`
- Modify: `src/hl_observer/cli.py`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Modify: `README.md`

**Interfaces:**
- Consumes: `Settings.ccxt_universe`.
- Produces: `hl-observer discover-ccxt-universe` et une courte documentation d’usage.

- [ ] Ajouter un test CLI/config ciblé au même fichier et confirmer son échec.
- [ ] Ajouter les paramètres bornés, la commande asynchrone et `ccxt` aux dépendances.
- [ ] Documenter brièvement l’usage et la séparation `DISCOVERY_ONLY`/native.
- [ ] Exécuter uniquement `tests/test_ccxt_universe_scout.py`.

### Task 3: Vérification et livraison

**Files:**
- Verify: tous les fichiers ci-dessus.

**Interfaces:**
- Consumes: diff Git et sortie pytest fraîche.
- Produces: commit poussé sur `main`.

- [ ] Relire le diff ciblé et vérifier l’absence d’accès privé/trading.
- [ ] Réexécuter `pytest -q tests/test_ccxt_universe_scout.py`.
- [ ] Committer avec `feat: add CCXT universe scout` puis pousser `main`.
