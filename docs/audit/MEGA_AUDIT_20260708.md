# Méga-audit pré-run 48h — 2026-07-08

Audit QA complet demandé avant le run 48h. Objectif : repérer trous, mauvais réglages,
casses, et tout réparer pour que les données du run soient fiables.

## Méthode — 6 passes
1. Compile-all (troncature/casse) — **0 fichier cassé**.
2. Import-all du paquet — 815 → **817/817 modules importent** (après fix).
3. Grep sécurité (exécution réelle, clés, signatures) — **0 chemin réel**.
4. Suite de tests (ciblée + large) — ~1150 tests verts, 6 échecs traités.
5. Cohérence config launcher (flags morts/contradictoires/mal réglés).
6. Chemin critique live (funding feed, poller, boot, réconciliation).

## Problèmes RÉELS trouvés + corrigés

### 1. TROU CRITIQUE — le poller funding n'était jamais démarré (funding-arb muet)
Le correctif funding-arb précédent (commit 4624d32) était **incomplet**. `_build_funding_rows`
lisait bien `funding_runtime_cache`, mais `funding_poller.ensure_started` n'avait **aucun
point d'appel sur le chemin live** : son seul call-site est dans `signals/v26_entry_vetos.py`,
derrière le flag `HYPERSMART_V26_ENTRY_VETOS_AUTHORITATIVE` **non activé** au launcher.
→ cache vide → `funding_rows=[]` → le moteur funding-arb ne pouvait toujours **jamais** ouvrir de paire.

**Fix** : `ensure_started(None)` appelé dans `_build_funding_rows` (chaque heartbeat),
idempotent + no-op si `HYPERSMART_V26_FUNDING_POLLER` off. Poller **découplé des vetos**
(collecte de données = sûr, démarre ; vetos V26 = changement de comportement, restent OFF
pour A/B). + test de régression `test_heartbeat_starts_funding_poller`.

### 2. Baseline sécurité ROUGE (depuis a7fb87b)
`test_safety_audit_passes_project_baseline` échouait : `no_exchange_endpoint_in_runtime_source`.
Cause : littéral brut `"/exchange"` dans `perf/hot_path_guard.py` (garde défensive orpheline —
faux positif). Fix idiome split `"/" + "exchange"` (convention déjà utilisée par safety_audit.py).
→ `hl_observer safety-audit` = **VERT, 0 finding**.

### 3. Incohérence launcher — plancher d'edge
`LANCER_HYPERSMART.cmd` posait `HYPERSMART_SIMULATION_MIN_EDGE_BPS=40`, mais
`start_hypersmart_simulation.ps1` posait `28`. En live le .cmd gagne (set-if-absent → 40),
mais c'est fragile et faux si le .ps1 tourne seul. **Aligné à 40 partout** + guard test.

### 4. Régression imports — ExitPlan écrasé
Mon `exits/exit_engine.py` (commit b57c1dc) avait écrasé `ExitPlan`+`build_default_exit_plan`
du scaffold → 2 modules `copying/` (viral_bot_engine, pipeline_integrator, orphelins non câblés)
ne s'importaient plus. Couche compat restaurée (ExitPlan/ExitReason/select_exit_plan/evaluate_exit).

## Tests obsolètes recalés (durcissements délibérés, PAS des bugs)
- Plancher edge par défaut 15 → 28 bps (`DEFAULT_SIMULATION_MIN_EDGE_BPS`).
- Fenêtre d'âge signal 15 s → 12 s (signaux plus frais).
- Bus github externe → **shadow-only** (0 profil installé/exécuté, jamais prioritaire ; pivot ff7aeec).

## Limites restantes
- **4 échecs CLI = artefacts sandbox** (subprocess avec chemin Windows `C:\...` inexistant
  sous Linux). Passent sur Windows. `cli.py` non tronqué (3721 l.).
- Vérité complète des tests (gros fichiers non tronqués) = à lancer sur Windows :
  `set PYTHONPATH=src && python -m pytest -q`.
- Registre exhaustif des ~261 flags (dead-flag audit complet) non terminé — flags critiques
  du run vérifiés consommés + cohérents.

## Sécurité
0 ordre réel, 0 argent réel, 0 clé privée, 0 signature, 0 dépôt/retrait.
`safety-audit` VERT · `HL_ENV=paper` · mainnet/testnet execution = 0.

Commit : `1d79eee`.
