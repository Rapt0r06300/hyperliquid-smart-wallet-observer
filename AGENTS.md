# AGENTS.md — Alina SmartFlow

> **Version compacte active — 2026-09-10.** Ce fichier doit rester court : Codex le charge automatiquement.
> Dernière mise à jour : **2026-09-10**
> L'ancien guide verbeux est archivé dans `docs/archive/AGENTS_LEGACY_20260909.md` et ne doit être lu
> que si une question historique précise l'exige.

## 1. Autorité et vérité courante

Ordre de priorité en cas de contradiction :

1. code, tests, gates et registres machine du **HEAD exact** ;
2. `docs/CURRENT_STATE.md` ;
3. ce fichier, `docs/CODEX_GOAL_RUNBOOK.md` et `SECURITY.md` ;
4. `docs/LOIS_MESUREES.md` pour les hypothèses déjà tranchées ;
5. documents historiques uniquement si nécessaires à une investigation ciblée.

Ne jamais présenter un ancien chiffre de PnL, verdict, tasklist ou statut CI comme actuel sans preuve liée au HEAD courant.

## 2. Mission économique

Alina SmartFlow cherche un edge **paper** honnête sur Hyperliquid. Familles canoniques :

- `copy_vault` ;
- `lead_lag` ;
- `cross_venue_dislocation_v2`.

`src/hl_observer/simulation/economic_objective.py` est la gate économique de base.
La cible finale est **au moins +4.00 USD NET PROUVÉS PAR JOUR par famille**, séparément, sans compensation.
Toujours suivre les constantes/gates du HEAD exact : le contrat courant exige aussi la preuve quotidienne
canonique sur plusieurs jours (`MIN_PROOF_DAYS`) et la certification finale via
`python tools/run_daily_economic_certification.py .`.

Ambition maximale pour **chercher** l'edge ; honnêteté maximale pour **le certifier**. `KILL`,
`MORE_DATA` ou `BLOCKED` valent mieux qu'un faux gain et n'arrêtent pas la recherche globale.

## 3. Sécurité absolue

`READ-ONLY-MAINNET · LOCAL-DECISION · PAPER-ONLY · DENY-BY-DEFAULT`.

Interdit : ordre réel, `/exchange` réel, signature réelle, clé privée, seed/mnemonic, wallet-connect
d'action, dépôt, retrait, argent réel, exécution mainnet ou testnet.
Un signal ou paper-trade n'est jamais un ordre. Donnée incertaine, stale, incomplète ou non liquidable
=> refus/fail-closed. Ne jamais réduire un garde-fou de risque/sécurité pour améliorer le PnL.

## 4. Surfaces de travail

- `src/hl_observer/` : runtime actif ; nouvelles implémentations ici.
- `tools/` : collecteurs, feeders, CLI et orchestration locale.
- `hyper_smart_observer/` : legacy/compat ; pas de nouvelle architecture.
- `runtime/data/*.jsonl`, `runtime/replay/` et ledgers runtime : append-only ; pas de purge destructive.
- Si l'utilisateur indique qu'une session tourne : lecture seule sur son runtime.
- Une modification de `src/` nécessite un redémarrage pour prendre effet ; le signaler si pertinent.

Contrat Git : **`main` uniquement** à la clôture. Ne jamais faire de `reset --hard`, `clean` destructeur
ou écrasement de données locales non sauvegardées.

## 5. Workflow obligatoire, Discovery V3 et quota

Le moteur de recherche Codex est **Discovery V3**. Utiliser `$alina-quant-research` et
`docs/CODEX_GOAL_RUNBOOK.md`. Le ledger local est piloté par
`python tools/codex_hypothesis_ledger.py ...`.

Principes :

1. Inspecter le SHA/état Git et les preuves récentes utiles ; ne pas relire tout l'historique.
2. Avant un gros run, distinguer une vraie nouvelle hypothèse d'un simple retuning.
3. Au début d'un cycle Discovery ou après stagnation, générer plusieurs mécanismes structurellement
   distincts, les enregistrer/scorer, puis faire un tournament local avant d'exploiter les survivants.
4. Deux retunings `PARAMETER_ONLY` sans progrès économique, ou une lignée à headroom non positif,
   doivent provoquer un `PIVOT`/Rediscovery plutôt qu'une boucle cosmétique.
5. Tout calcul faisable localement doit être fait par le PC : Python, numpy/scipy, pytest, replays,
   backtests, bootstrap, permutations, Monte-Carlo, optimisation, profiling et agrégation.
6. Le calcul lourd est **CPU-first**. `tools/codex_quant_experiment.py` masque CUDA/ROCm/HIP/JAX GPU
   par défaut. GPU seulement si un besoin mesuré le justifie.
7. Parallélisme **local** autorisé : processus, threads, multiprocessing, batchs et workers CPU.
8. Pour plusieurs expériences pré-définies, préférer `python tools/codex_quant_batch.py <batch>` :
   pas de round-trip modèle à l'intérieur du batch.
9. Lire d'abord `RESULT_SUMMARY.json` / `BATCH_SUMMARY.json`; garder gros logs/trials sur disque.
10. Tests ciblés pendant l'itération ; suites globales lourdes aux jalons et certifications.
11. Cache/déduplication : ne pas relancer un gros run identique sans changement scientifique.
12. Recherche externe proactive mais bornée au début d'un cycle Discovery si elle élargit réellement
    l'espace : Exa/Parallel/Consensus/GitHub selon besoin, puis retour immédiat au calcul local.
13. **Sous-agents IA interdits pour ce Goal** : agent principal unique ; aucun spawn/fan-out/reviewer-agent.
14. Si seule l'accumulation de nouvelles données/temps peut débloquer la preuve, arrêter les tours modèle
    inutiles et laisser les collecteurs locaux nécessaires travailler.

Les **775 optimisations pré-run déjà scellées** ne sont pas une backlog à recommencer.

## 6. Discipline scientifique

Une amélioration économique n'est admissible que si elle survit aux coûts applicables : frais, spread,
slippage, latence, capacité et coûts de copie/exécution pertinents.

Obligatoire pour une certification :

- données réelles avec provenance ;
- positions entièrement fermées et PnL réconcilié ;
- `LIQUIDATABLE_NET` ;
- identités de trades/événements uniques ;
- séparation temporelle et absence de lookahead ;
- paramètres figés avant preuve finale ;
- OOS ;
- forward strictement post-freeze ;
- durée/couverture forward mesurées ;
- placebos/contrôles requis ;
- aucune compensation entre familles.

Tous les essais distincts doivent être comptés. Validation/OOS/forward observé puis utilisé pour retuner
devient exploratoire : refreeze puis nouvelle preuve disjointe. Ne pas rouvrir une loi mesurée sans
nouvelle donnée ou nouveau mécanisme réel.

Jamais de donnée fabriquée présentée comme réelle. `None` n'est pas `0`. `LIVE`, `BACKTEST`, `REPLAY`
et `TEST_FIXTURE` ne se mélangent pas. Le latent/non réalisé reste séparé du net.

## 7. Qualité du code

- Petits modules cohérents et importables ; réutiliser l'architecture existante.
- Nouveau comportement => test de régression dans le même mouvement.
- Feature DONE seulement si codée, testée et câblée, ou explicitement partielle.
- Ne pas supprimer/xfail/skip des tests ni baisser une gate pour fabriquer du vert.
- Respecter les lanceurs existants.
- Éviter les collecteurs lourds dupliqués.

## 8. Définition de fin

La mission économique n'est terminée que lorsque le **même état certifié de `main`** prouve séparément :

- `copy_vault >= +4.00 USD NET/jour PROUVÉS` ;
- `lead_lag >= +4.00 USD NET/jour PROUVÉS` ;
- `cross_venue_dislocation_v2 >= +4.00 USD NET/jour PROUVÉS` ;

avec les exigences exactes du HEAD courant, puis les gates techniques finales requises vertes.
`python tools/run_daily_economic_certification.py .` doit certifier les trois familles.
Aucun document narratif ne peut surclasser les gates machine.

## 9. Rapport final

Répondre de façon concise en français : fichiers modifiés, preuve/diagnostic, tests, statut économique,
blocages et prochaine action. Éviter les longs historiques non nécessaires.

Terminer les livraisons touchant runtime/stratégie par :

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
