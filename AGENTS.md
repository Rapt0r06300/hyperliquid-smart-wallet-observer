# AGENTS.md — Alina SmartFlow · Discovery V3.2

> Routeur compact chargé automatiquement. Les détails restent lazy-load pour économiser au maximum le quota modèle.

## Autorité

Priorité : `SECURITY.md` > `docs/HYPERSMART_CONSTITUTION.md` > code/tests/gates/manifests du HEAD exact > ce fichier > docs ciblées. Un texte historique ne peut jamais assouplir sécurité, provenance ou gate machine.

## Mission

Familles canoniques : `copy_vault`, `lead_lag`, `cross_venue_dislocation_v2`.
Cible finale : **>= +4.00 USD NET/jour PROUVÉS par famille, séparément**, sur le même SHA certifié, sans compensation. Autorité finale : `python tools/run_daily_economic_certification.py .`.

Sécurité absolue : `READ-ONLY-MAINNET · LOCAL-DECISION · PAPER-ONLY · DENY-BY-DEFAULT`.
Interdits : ordre réel/testnet, `/exchange` réel, signature, clé/seed, dépôt/retrait, argent réel. Donnée stale/incertaine/incomplète => fail-closed.

## Reprise V3.2 — quota maximalement préservé

**Première commande par défaut :**
`python tools/codex_research_context.py --auto`

Le JSON compact produit est la source normale de reprise : HEAD, famille, ledger, `PROCESS_MEMORY`, veto motifs, trial accounting, état semantic discovery, surfaces disponibles et prochaines actions.

Après ce pack :
1. lire uniquement le code/fichier compact nécessaire à la prochaine décision ;
2. charger `docs/CODEX_GOAL_RUNBOOK.md` ou `$alina-quant-research` seulement quand une vraie décision Discovery/TOURNAMENT/EXPLOIT/PIVOT l'exige ;
3. lire `.agents/skills/alina-quant-research/references/discovery-v32.md` uniquement en Discovery/champion-challenger ;
4. ne lire les gros résultats qu'après leurs `RESULT_SUMMARY.json` / `BATCH_SUMMARY.json`.

**Interdit comme reprise normale :** rescanner l'**historique Git complet**, relire les **775** optimisations scellées, charger de gros logs/raw trials, ou parcourir tout le dépôt pour reconstruire l'état. Si HEAD a avancé : seulement le **delta Git** pertinent depuis `base_sha`.

## Modèle décide, PC calcule

Objectif de cadence : **1 décision modèle -> gros batch local -> résumé compact -> 1 décision modèle**.
Tout calcul déterministe faisable localement reste local : Python, numpy/scipy, pytest, replays, backtests, bootstrap, permutations, Monte-Carlo, optimisation et agrégation. CPU-first ; multiprocessing/threads/batchs permis. GPU seulement si un besoin mesuré le justifie.

`python tools/codex_semantic_discovery.py --family <family> --pool-size 2000 --shortlist 12`
peut générer un grand pool local, filtrer invalides/doublons/vetos et n'exposer au modèle qu'une shortlist. `PROCESS_MEMORY.jsonl` et `HYPOTHESIS_LEDGER.jsonl` restent append-only.

**Sous-agents IA : interdits** dans une campagne économique Discovery. Ils restent autorisés pour travaux techniques indépendants hors campagne quant, avec surfaces disjointes et intégration vérifiée.

## Contrôleur scientifique

Discovery V3.2 enveloppe V3.1 sans changer ses preuves économiques :
- DISCOVERY : 12 hypothèses structurelles par défaut, minimum 8, >=5 archétypes ;
- TOURNAMENT : falsifier bon marché, classer causalité/données/headroom/valeur d'information ;
- EXPLOIT : gros calcul local seulement sur survivants ;
- REDISCOVERY : 2 retunings `PARAMETER_ONLY` sans progrès ou 2 évaluations non positives => `PIVOT` ;
- CHALLENGER : après 3 `IMPROVE` consécutifs sans FREEZE, >=4 challengers orthogonaux avant un 4e improve.

Mémoire négative : veto seulement pour mécanisme+contexte suffisamment équivalents et preuve répétée haute confiance. Un retest reste admissible avec nouvelle donnée/surface, mécanisme matériellement différent ou contradiction fraîche. Mémoire positive = boost borné, jamais certification.

Toute variante évaluée compte dans la pression de recherche. Toute OOS/forward observée puis utilisée pour retuner devient feedback : refreeze et nouvelle preuve disjointe. Frais, spread, slippage, latence, capacité, fill/liquidatabilité, closed positions, provenance et no-lookahead restent obligatoires.

## Done / Git

Feature DONE = codée + testée + câblée ; ne jamais supprimer/skip/xfail un test ni baisser une gate pour obtenir du vert. `main` est l'état final ; pas de `reset --hard`/clean destructeur. Runtime de collecte actif annoncé par l'utilisateur => lecture seule.

Mission économique DONE seulement si le même `main` certifie les 3 familles à >= +4.00 USD NET/jour avec le contrat machine courant et gates finales vertes.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
