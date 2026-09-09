# AGENTS.md — Alina SmartFlow

> **Version compacte active — 2026-09-09.** Ce fichier doit rester court : Codex le charge automatiquement.
> Dernière mise à jour : **2026-09-09**
> L'ancien guide verbeux est archivé dans `docs/archive/AGENTS_LEGACY_20260909.md` et ne doit être lu
> que si une question historique précise l'exige.

## 1. Autorité et vérité courante

Ordre de priorité en cas de contradiction :

1. code, tests, gates et registres machine du **HEAD exact** ;
2. `docs/CURRENT_STATE.md` ;
3. ce fichier, `docs/CODEX_GOAL_RUNBOOK.md` et `SECURITY.md` ;
4. `docs/LOIS_MESUREES.md` pour les hypothèses déjà tranchées ;
5. documents historiques uniquement si nécessaires à une investigation ciblée.

Ne jamais présenter un ancien chiffre de PnL, un ancien verdict, une ancienne tasklist ou un ancien
statut CI comme actuel sans nouvelle preuve liée au HEAD courant.

## 2. Mission économique

Alina SmartFlow cherche un edge **paper** honnête sur Hyperliquid. Les trois familles économiques
canoniques sont uniquement :

- `copy_vault` ;
- `lead_lag` ;
- `cross_venue_dislocation_v2`.

`src/hl_observer/simulation/economic_objective.py` reste la gate de preuve économique de base.
La cible finale réelle est maintenant **au moins +4.00 USD NET PROUVÉS PAR JOUR par famille**, séparément,
sans compensation. La gate finale journalière est
`src/hl_observer/ops/daily_economic_certification.py`, exécutable via
`python tools/run_daily_economic_certification.py .`.

Le rendement journalier ne doit jamais être extrapolé depuis quelques minutes : la certification exige
au minimum 86 400 secondes de forward strictement post-freeze observé par famille et mesure le net sur
ce temps mur réel. Donnée de durée manquante => `NO_GO`.

Ambition maximale pour **chercher** l'edge ; honnêteté maximale pour **le certifier**. `KILL`,
`MORE_DATA` ou `BLOCKED` valent mieux qu'un faux gain et n'arrêtent pas la recherche globale.

## 3. Sécurité absolue

`READ-ONLY-MAINNET · LOCAL-DECISION · PAPER-ONLY · DENY-BY-DEFAULT`.

Interdit sans exception : ordre réel, `/exchange` réel, signature réelle, clé privée, seed/mnemonic,
wallet-connect d'action, dépôt, retrait, argent réel, exécution mainnet ou testnet.
Un signal ou paper-trade n'est jamais un ordre. Donnée incertaine, stale, incomplète ou non
liquidable => refus/fail-closed.

Ne jamais réduire un garde-fou de risque ou de sécurité pour améliorer un PnL.

## 4. Surfaces de travail

- `src/hl_observer/` : runtime actif ; nouvelles implémentations ici.
- `tools/` : collecteurs, feeders et CLI ; modifier seulement si nécessaire.
- `hyper_smart_observer/` : legacy/compat ; ne pas y créer de nouvelle architecture.
- `runtime/data/*.jsonl` et `runtime/replay/` : append-only ; jamais de purge/réécriture destructive.
- Si l'utilisateur indique qu'une session tourne : lecture seule sur son runtime.
- Une modification de `src/` nécessite un redémarrage pour prendre effet ; le signaler si pertinent.

Contrat Git : **`main` uniquement**. Ne pas créer de branche de travail finale. Ne jamais faire de
`reset --hard`, `clean` destructeur ou écrasement de données locales non sauvegardées.

## 5. Workflow obligatoire et économe en quota

1. Inspecter d'abord le SHA/état Git et les preuves les plus récentes utiles au blocage courant.
2. Renforcer l'architecture existante ; ne pas recréer ce qui existe déjà.
3. Travailler sur **une famille + un goulot d'étranglement principal à la fois**.
4. Mesurer avant de proposer : données/preuves -> diagnostic -> hypothèse causale -> test ciblé.
5. Tout calcul faisable localement doit être fait par le PC : Python, numpy/scipy, pytest, replays,
   backtests, bootstrap, permutations, Monte-Carlo, optimisation, profiling et agrégation de logs.
6. Le calcul lourd est **CPU-first**. `tools/codex_quant_experiment.py` masque CUDA/ROCm/HIP/JAX GPU par
   défaut et utilise les CPU locaux. Ne recourir au GPU que hors de ce runner si un besoin réel le rend
   nettement préférable ; ce n'est jamais le choix par défaut.
7. Le parallélisme **local** est autorisé et encouragé : processus, threads, multiprocessing, batchs,
   jobs CPU et essais simultanés peuvent être lancés autant que raisonnablement utile. Ce parallélisme
   local n'est pas du multi-agent IA.
8. Tests ciblés pendant l'itération ; suites globales lourdes aux jalons, régressions transversales et
   certifications. Les gros calculs locaux peuvent être longs si leur gain d'information est élevé.
9. Ne jamais relancer exactement le même gros run si ni code, ni données, ni hypothèse n'ont changé.
10. Ne pas relire toute l'histoire Git, les 775 optimisations ou tous les audits à chaque reprise.
11. Recherche web, MCP et plugins seulement pour combler un manque **précis** que le repo et les données
    locales ne peuvent pas résoudre. Revenir ensuite immédiatement au test falsifiable local.
12. **Sous-agents IA interdits pour ce Goal** : agent principal unique ; aucun spawn/fan-out/reviewer-agent.
    Cette interdiction ne limite jamais les calculs/processus locaux non-LLM.
13. Si la prochaine preuve dépend uniquement de nouvelles données, d'un délai réel, d'un runner ou
    d'une intervention utilisateur : arrêter le travail modèle inutile et signaler clairement le blocage.

Pour une recherche multi-trials, préférer le skill `$alina-quant-research` et
`python tools/codex_quant_experiment.py <spec>` : le PC exécute les essais, Codex lit d'abord
`RESULT_SUMMARY.json` et n'ouvre les artefacts détaillés que pour une anomalie précise.

Pour la boucle de recherche quantitative, les tests possibles et le routage des outils, suivre
`docs/CODEX_GOAL_RUNBOOK.md`. Les **775 optimisations pré-run déjà scellées** ne sont pas une backlog à
recommencer. Les réauditer seulement lorsqu'une modification actuelle menace explicitement leur contrat.

## 6. Discipline scientifique de la preuve

Une amélioration économique n'est admissible que si elle survit aux coûts réels applicables : frais,
spread, slippage, latence, capacité et coûts de copie/exécution pertinents.

Obligatoire pour une certification :

- données réelles avec provenance ;
- positions entièrement fermées et PnL réconcilié ;
- `LIQUIDATABLE_NET` ;
- identités de trades/événements uniques ;
- séparation temporelle et absence de lookahead ;
- paramètres figés avant validation ;
- OOS ;
- forward strictement post-freeze ;
- durée forward mesurée sur le temps mur réel ;
- placebos/contrôles requis ;
- aucune compensation entre familles.

Ne jamais retuner validation/OOS/forward après observation pour embellir le résultat. Une nouvelle
hypothèse se choisit sur train, puis se freeze. Ne pas rouvrir une loi mesurée sans donnée ou mécanisme
réellement nouveau : consulter `docs/LOIS_MESUREES.md` seulement lorsque la piste correspondante est
concernée.

Jamais de donnée fabriquée présentée comme réelle. Un champ manquant reste manquant (`None`), pas `0`.
`LIVE`, `BACKTEST`, `REPLAY` et `TEST_FIXTURE` ne se mélangent pas. Le latent/non réalisé reste séparé
du net. Enregistrer les refus autant que les acceptations.

## 7. Qualité du code

- Petits modules cohérents et importables plutôt qu'une architecture parallèle.
- Nouveau comportement => test de régression dans le même mouvement.
- Une feature n'est DONE que si elle est codée, testée et réellement câblée, ou explicitement marquée
  non câblée/partielle.
- Ne pas supprimer/xfail/skip des tests ni baisser une gate pour fabriquer du vert.
- Respecter les lanceurs existants ; `LANCER_HYPERSMART.cmd` reste le runtime CORE et
  `ANALYSER_BACKTESTS_REPLAYS.cmd` reste l'entrée dédiée aux analyses/replays.
- Éviter les collecteurs lourds dupliqués : réutiliser les processus/données déjà disponibles.

## 8. Définition de fin

La mission économique n'est terminée que lorsque le **même état certifié de `main`** prouve séparément :

- `copy_vault >= +4.00 USD NET/jour PROUVÉS` ;
- `lead_lag >= +4.00 USD NET/jour PROUVÉS` ;
- `cross_venue_dislocation_v2 >= +4.00 USD NET/jour PROUVÉS` ;

sur au moins une journée complète de forward post-freeze mesuré par famille, avec toutes les exigences
scientifiques ci-dessus, puis les gates techniques finales requises vertes sur le SHA certifié.
`python tools/run_daily_economic_certification.py .` doit finir avec les trois familles certifiées.
Aucun document narratif ne peut surclasser les gates machine.

## 9. Rapport final

Répondre de façon concise en français : fichiers modifiés, preuve/diagnostic obtenu, tests lancés,
statut économique honnête, blocages et prochaine action utile. Éviter les longs historiques si non
nécessaires.

Terminer les livraisons touchant au runtime ou à la stratégie par :

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**