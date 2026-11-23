# Audit Copy-Vault — checkpoint local

Date de départ : 2026-11-23  
HEAD observé : `3654f606038e79061930e5bb7b04f9960c9a10a8` (`main`)  
Contrat applicable : PAPER/read-only/fail-closed, Copy-Vault seul, `PAPER_EQUITY_USD` = 100 USD.

## État vérifié

- Aucun changement suivi dans l’index ou le worktree au démarrage ; la découverte des non-suivis est lente à cause du volume `runtime/data`.
- Tests ciblés initiaux : 64 passés.
- Tests capital/runtime flags/objectif/snapshot : 60 passés.
- `compileall src` : OK.
- `ruff check src tests tools` n’est pas une gate exploitable : 7 952 diagnostics hérités ; `E9,F` en relève 456, principalement dette legacy.
- Suite complète de référence arrêtée au premier échec : 1 688 passés, échec de `tests/test_asf_rig_001_020_copy_vault.py::test_rig_020_all_current_receipts_are_exactly_revalidated`.

## Anomalie traitée

P1 — le registre ignoré `runtime/roadmap/ALINA_ROADMAP_3120.receipts.jsonl` contenait 12 reçus `VERIFIED_DONE` périmés (empreintes antérieures à l’état courant), alors que les tests de preuve étaient verts. Cause : preuves append-only non rejouées après évolution des fichiers épinglés ; pas un défaut du code métier.

Action : `python tools/revalider_receipts.py --timeout-s 600`.

Preuve : 12/12 reçus rafraîchis, 3 groupes rejoués, 0 échec, 0 preuve absente, 0 reste périmé, dont 1 rafraîchissement au second passage pour le groupe circulaire.

## Correctifs de robustesse appliqués

- P1 — `src/hl_observer/config/runtime_flags.py` importait deux fois `PAPER_EQUITY_USD`, dont une fois depuis le module de backtest. Cela contredisait le contrat de module feuille et exposait un risque de dépendance circulaire/contrat capital divergent. Régression AST ajoutée, rouge avant patch puis verte après suppression de l’import backtest ; 10 tests capital/runtime flags passent.
- P1 — `.github/workflows/alina-operator-intent.yml` déclarait deux blocs YAML top-level `env:`. Selon l’interpréteur, le second pouvait remplacer le premier et perdre `PYTHONPATH`. Régression ajoutée, rouge avec 2 blocs puis verte après fusion de `GH_TOKEN` dans le bloc unique ; 18 tests workflow passent. Le workflow reste `ubuntu-latest`, sans runner self-hosted.
- P1 — `tools/alina_quant_lab_console.py` initialisait son fallback global à 1 000 USD avant le chargement du labo optionnel, en contradiction avec le contrat paper 100 USD. Régression comportementale rouge puis verte après dérivation directe depuis `hl_observer.contrat_paper`; le fallback ne peut plus fabriquer un rapport à une autre échelle. Le groupe console + capital compte 37 tests verts.
- P2 — `economic_objective.py` publiait encore `alina.economic_objective.350usd-reference-only.v2` dans les preuves courantes. Test de version rouge puis vert après passage à `100usd-reference-only.v3`; 66 tests économiques passent. Les références historiques documentaires restent archivées et ne sont pas exécutées.
- P1 — le certificateur hachait les octets gzip compressés pour une archive, mais les octets JSONL décompressés pour le ruban clair. Après compression, la source semblait donc nouvelle et 1 000 lignes étaient redéposées. Le test d’idempotence existant a reproduit le défaut (`2 001` au lieu de `2 000`) ; l’identité source utilise maintenant le contenu logique décompressé. Archive/couverture/symlink : 23 tests verts.
- Après les correctifs, le registre append-only comptait 11 reçus périmés ; revalidation réelle : 11/11 rafraîchis, 3 groupes rejoués, 0 échec, 0 preuve absente, 0 reste périmé. Le rafraîchissement est une conséquence attendue des hashes de code, pas une régénération aveugle.
- P1 — `ETA_COLLECTE.cmd` affichait une sonde datée chargée une seule fois : le compteur de journées restait figé pendant que les collecteurs continuaient. `tools/eta_donnees_labo.py` choisit désormais le dernier rapport `sonde_horloges_*.json` par défaut et le recharge à chaque tour ; `--sonde` explicite reste disponible. La mesure d'intervalle utilise aussi `time.monotonic()` pour éviter les lectures Windows indistinguables. TDD : 18 tests ETA + 63 tests ETA/lanceurs/runtime verts, ruff ciblé et compileall verts.

## Preuves bout en bout

- `tools/valider_chaine_bout_en_bout.py --racine . --json` : 11 maillons en état `OK`, sécurité `OK`, aucune violation, témoins de reprise présents et artefacts lisibles. Le rapport précise les étapes sans artefact unique à vérifier ; cette validation structurelle ne remplace donc pas les tests économiques/replay.
- Tests de fermeture et receipts après revalidation : 24 passés.
- Entrypoints/runtime : 19 passés ; groupe économique/entrypoint/dashboard/santé : 45 passés.
- Collecte → SAFE → replay/backtest → simulation/PnL : 155 passés.
- PAPER/SAFE/phases/reprise/CI : 294 passés.
- Suite complète : première passe arrêtée après 1 089 tests sur le défaut gzip ; seconde passe arrêtée après ~8 % sur les 11 reçus périmés engendrés par les nouveaux hashes. Revalidation faite ; une nouvelle passe complète reste requise.

## Suite de travail

1. Rejouer les groupes Copy-Vault collecte/SAFE/replay/backtest/simulation/PnL directement impactés.
2. Inspecter les invariants temporels, doublons/trous, reprise, déterminisme et les workflows GitHub-hosted.
3. Corriger uniquement les anomalies reproduites ; ajouter une régression avant chaque correctif de code.
4. Relancer les tests impactés, puis la suite complète locale ; vérifier le diff réel et les HEAD avant toute conclusion.

## Règles de preuve

Ne pas promouvoir un résultat économique à partir d’un backtest positif seul. Une donnée manquante/stale/incohérente reste inconnue ; aucune exécution réelle/testnet, clé, secret, `/exchange`, self-hosted ou dépendance au PC ne doit devenir atteignable.
