# Alina SmartFlow — Codex Quant Research V2

Date : 2026-09-09
Statut : design approuvé conceptuellement par l'utilisateur ; implémentation bloquée jusqu'à revue de ce spec.

## 1. But

Maximiser le progrès quantitatif utile par unité de quota ChatGPT Plus sans réduire l'ambition scientifique : un seul GPT-5.6 Sol choisit les expériences, tandis que le PC exécute autant que possible les backtests, optimisations, stress tests et validations localement.

La cible économique et les garanties de preuve restent celles de `AGENTS.md`, `docs/CODEX_GOAL_RUNBOOK.md` et de la gate canonique : trois certifications séparées `copy_vault`, `lead_lag`, `cross_venue_dislocation_v2`, chacune >= +4 USD NET PROUVÉS en paper/read-only.

## 2. Principes non négociables

- Un seul agent IA principal pour le Goal ; aucun sous-agent/fan-out/reviewer-agent.
- Le calcul répétitif est local-first : Python, pytest, replays, Optuna, backtests et scripts existants.
- Les outils externes servent à créer une hypothèse falsifiable précise, jamais à remplacer les mesures locales.
- Aucune baisse d'une gate de sécurité ou de preuve pour produire un PnL.
- OOS/forward observé puis utilisé pour retuner => ce segment perd son statut de preuve et un nouveau freeze + nouveau segment disjoint sont requis.
- Tous les essais de recherche sont comptabilisés pour les corrections de multiplicité.
- Aucun run lourd identique si code, données, coûts, paramètres et hypothèse n'ont pas changé.

## 3. Architecture retenue

### 3.1 Single-writer : un SHA expérimental stable

Pendant une campagne Goal active, Codex devient le seul écrivain du code/protocole sur `main`. Les autres automatisations/agents peuvent lire, auditer et rechercher, mais ne doivent pas pousser de commit qui déplace `main` tant que la lease est active.

Créer `coordination/CODEX_WRITER_LEASE.json`, petit registre versionné avec :

- `schema_version` ;
- `status`: `active|released` ;
- `writer`: `codex_goal` ;
- `session_id` non secret ;
- `base_sha` ;
- `started_at_utc` ;
- `expires_at_utc` ;
- `goal`: identifiant court ;
- `note`.

Règles :

1. Codex acquiert/rafraîchit la lease avant une campagne d'écriture.
2. Les automatismes ChatGPT doivent vérifier la lease avant tout push : `active` => recherche/audit seulement, zéro commit ; `released/expired` => écriture permise selon leur propre contrat.
3. Codex travaille contre un `base_sha` figé pendant une expérience. Si `origin/main` avance malgré la lease, il ne boucle pas en fetch/rebase : il termine/abandonne proprement l'expérience, produit un état de reprise puis resynchronise une seule fois.
4. `main-only` signifie : état livré et certifié sur `main`. Un worktree local éphémère de Codex est autorisé s'il évite les collisions ; aucune branche finale parallèle n'est conservée.
5. La lease ne contient ni secret ni lock système. C'est un protocole de coordination auditable ; sa violation doit être visible et fail-closed côté Goal.

La mise à jour des prompts des automatisations ChatGPT existantes fera partie de l'implémentation afin qu'elles respectent cette lease.

### 3.2 Skill repo-local `alina-quant-research`

Créer `.agents/skills/alina-quant-research/SKILL.md`.

Le skill reste court et à divulgation progressive. Sa description doit déclencher uniquement pour : recherche d'edge, conception d'expérience, backtest, optimisation de paramètres, validation quantitative et certification des trois familles Alina.

Le skill n'impose pas une stratégie. Il impose une méthode :

`état -> mécanisme -> hypothèse -> spec machine -> recherche locale -> résumé compact -> décision -> freeze/validation ou rejet`.

Il doit router vers les briques existantes avant toute réinvention :

- `tools/outils_recherche.py` pour grid/random/QMC/TPE/CMA-ES/NSGA-II/Successive Halving/Hyperband ;
- validateurs anti-overfit existants (`anti_overfit_gate.py`, `validation_methods.py`, registres d'essais) ;
- scripts/backtests propres à chaque famille ;
- Exa + Parallel Search, Consensus et GitHub uniquement pour un manque externe précis ;
- skills Superpowers compatibles mono-agent pour debugging/TDD/vérification.

Le skill demande des sorties machine-readable et n'encourage jamais la narration de logs volumineux.

### 3.3 Orchestrateur local d'expériences

Créer un protocole Python générique, sans réécrire les moteurs quant existants :

- `src/hl_observer/research/experiment_protocol.py` : schéma, validation, signatures, état et résumé ;
- `tools/codex_quant_experiment.py` : CLI locale ;
- `tests/test_codex_quant_experiment.py` : contrats machine.

L'orchestrateur lit un `EXPERIMENT_SPEC.json` produit par Codex. Le spec contient au minimum :

- `schema_version`, `experiment_id`, `family`, `hypothesis_id`, `phase` ;
- `base_sha` et empreinte des données/cutoff ;
- évaluateur Python versionné (`module:function`) limité au code du projet ;
- espace de paramètres ;
- moteur de recherche (`grid|random|qmc|tpe|cma_es|nsga2|successive_halving|hyperband`) ;
- budget (`max_trials`, éventuellement `max_wall_seconds`) ;
- seed ;
- contrat de coûts et split/validation ;
- critères de promotion/rejet explicitement séparés de la gate finale.

L'orchestrateur réutilise `tools/outils_recherche.py` pour l'optimisation au lieu de dupliquer Optuna/pruning.

### 3.4 Deux niveaux de sortie

Chaque expérience écrit sous `runtime/codex_experiments/<experiment_id>/` :

1. preuves détaillées locales : trials, SQLite/JSONL, logs, artefacts ;
2. `RESULT_SUMMARY.json` compact, destiné à Codex.

Le résumé contient : signature, SHA, data fingerprint, durée, nombre d'essais proposés/terminés/prunés/échoués, meilleur candidat, métriques principales, coûts, statut des contrôles, verdict `REJECT|ITERATE|FREEZE_CANDIDATE|BLOCKED`, raisons et chemins des preuves détaillées.

Codex lit d'abord uniquement `RESULT_SUMMARY.json`. Il n'ouvre les preuves volumineuses qu'en cas d'anomalie précise.

### 3.5 Déduplication et cache expérimental

Calculer une `experiment_signature` déterministe à partir de :

`base_sha + family + hypothesis + evaluator + search_space + data_fingerprint + cost_model + split_config + seed`.

Si une signature complète existe déjà, l'orchestrateur retourne le résultat mis en cache au lieu de relancer le calcul. Un `--force` n'est accepté qu'avec une raison enregistrée et ne permet pas de requalifier une ancienne validation en nouvelle preuve.

C'est un garde-fou quota/CPU central : Codex peut reprendre une campagne sans répéter les mêmes runs.

### 3.6 Échelle de coût locale

Le protocole doit permettre à Codex de choisir dynamiquement les tests, mais recommande une montée en coût :

1. faisabilité/causalité ;
2. mini-échantillon + break-even coûts ;
3. recherche train coarse-to-fine ;
4. plateau/sensibilité/régimes ;
5. walk-forward/purge/embargo selon besoin ;
6. multiplicité/PBO/DSR/bootstrap/placebos ;
7. OOS verrouillé ;
8. forward strictement post-freeze ;
9. certification canonique.

Une hypothèse faible doit mourir tôt. Successive Halving/Hyperband/TPE sont privilégiés quand leur structure correspond au problème ; jamais comme checklist obligatoire.

## 4. État de reprise compact

Créer `runtime/codex_goal_state.json` (runtime local, non utilisé comme preuve à lui seul) contenant uniquement l'état nécessaire à la prochaine décision : SHA, famille, hypothèse, phase, data cutoff, freeze, compteur d'essais, dernier résultat, blocage et prochaine expérience.

À la reprise, Codex lit ce fichier + les autorités minimales du repo, pas l'ensemble de l'historique Git/775 tâches/anciens rapports.

## 5. Routage modèle et outils

- Défaut Goal : GPT-5.6 Sol, High/Élevé, Standard.
- XHigh/Très élevé : uniquement phase de Plan exceptionnelle (nouveau mécanisme, contradiction scientifique difficile, audit final complexe), puis retour High.
- Agent unique ; `multi_agent=false`, `agents.enabled=false` restent actifs.
- Shell/Python/fichiers locaux en premier.
- MCP/plugins : chargés/utilisés à la demande. Exa + Parallel Search = web/praticiens ; Consensus = littérature ; GitHub = repo/CI/code externe précis ; Superpowers = workflows mono-agent pertinents.
- Les outputs outils sont agrégés/tronqués avant retour au modèle quand ils sont volumineux.

## 6. Changements de documentation/config prévus

Après validation de ce spec :

- ajuster `AGENTS.md` pour le sens exact de `main-only`, la lease single-writer et l'orchestrateur ;
- ajuster `docs/CODEX_GOAL_RUNBOOK.md` pour faire du skill + `EXPERIMENT_SPEC.json` la boucle normale ;
- conserver `.codex/config.toml` High/Plan-XHigh/low-verbosity/sans sous-agents ;
- créer le skill et le protocole Python ;
- mettre à jour les automatisations ChatGPT existantes afin qu'elles ne poussent pas pendant une lease active.

## 7. Erreurs et fail-closed

L'orchestrateur refuse une expérience si :

- `base_sha` ne correspond pas à l'état attendu ;
- famille/phase/moteur/évaluateur sont invalides ;
- data fingerprint ou contrat de coûts exigé manque ;
- output dir tente de sortir du répertoire runtime autorisé ;
- un evaluateur hors namespace projet est demandé ;
- une signature identique a déjà été exécutée sans `--force` justifié.

Une erreur de trial n'efface pas les autres trials ; elle est comptée et exposée. Aucun champ manquant n'est converti silencieusement en zéro.

## 8. Tests et critères d'acceptation

Implémentation en TDD.

Tests ciblés obligatoires :

- validation/rejet du schéma ;
- signature déterministe et changement de signature quand une entrée scientifique change ;
- cache/déduplication ;
- refus `base_sha` incohérent ;
- refus d'évaluateur hors projet ;
- intégration avec un faux évaluateur déterministe et `tools/outils_recherche.py` ;
- propagation seed/budget ;
- `RESULT_SUMMARY.json` compact et stable ;
- état de reprise atomique ;
- aucune capacité d'ordre réel/clé/signature ajoutée.

Critère V2 terminé : Codex peut, à partir d'un spec minuscule, lancer une campagne locale bornée comportant plusieurs trials, obtenir un seul résumé JSON utile, reprendre sans répéter une signature déjà terminée, et travailler sur un SHA stable sans être perturbé par les automatisations concurrentes.

## 9. Hors périmètre V2

- Aucune exécution réelle/testnet.
- Aucun nouveau moteur de trading autonome.
- Aucun cluster distribué/GPU obligatoire.
- Aucun sous-agent.
- Aucune garantie qu'un edge de +4 USD existe ; la V2 optimise la qualité et le débit de recherche, pas le marché.
- Pas de réécriture des optimiseurs/validateurs déjà présents si une adaptation suffit.
