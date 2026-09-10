# Codex Discovery V3 — Design

Date: 2026-09-10
Status: design approuve en conversation, a relire avant implementation

## 1. Probleme

Le Goal quant actuel est tres robuste pour l'execution locale et la certification, mais il favorise trop facilement l'exploitation repetee d'une hypothese deja ouverte. Les derniers travaux ont surtout durci la preuve economique, alors que l'objectif utilisateur exige aussi une recherche active de nouveaux mecanismes pouvant atteindre, en PAPER, au moins +4.00 USD NET/jour pour chacune des familles `copy_vault`, `lead_lag` et `cross_venue_dislocation_v2`.

Les dix mecanismes historiques de `tools/recherche_14h_mecanismes.py` restent des baselines utiles, mais ne doivent pas etre presentes comme des hypotheses nouvelles.

## 2. Objectifs

V3 doit rendre le comportement de recherche explicitement `DISCOVERY -> TOURNAMENT -> EXPLOIT -> FREEZE` avec retour obligatoire vers `DISCOVERY` en cas de stagnation. Le systeme doit :

- conserver un ledger append-only de toutes les hypotheses et essais ;
- distinguer une nouvelle hypothese d'un simple retuning de seuils ;
- mesurer la nouveaute structurelle d'une hypothese avant de depenser un gros budget CPU ;
- forcer une nouvelle exploration apres stagnation ;
- reutiliser les runners locaux existants, notamment `tools/codex_quant_experiment.py` et `tools/codex_quant_batch.py` ;
- conserver la separation train / validation / OOS / forward et le comptage des essais ;
- rester agent LLM principal unique : aucun sous-agent n'est necessaire au moteur V3.

## 3. Non-objectifs

V3 ne remplace pas les gates economiques, ne change pas la cible de +4 USD NET/jour, n'autorise aucune execution reelle et ne promet pas qu'un edge existe. Elle ne reconstruit pas les 775 optimisations scellees. Elle n'introduit pas un second framework de backtest.

## 4. Architecture

### 4.1 Etat de recherche

Ajouter `src/hl_observer/research/hypothesis_ledger.py`, module local pur et sans reseau. Le ledger runtime canonique sera `runtime/codex_research/HYPOTHESIS_LEDGER.jsonl` et restera append-only.

Chaque ligne est un enregistrement versionne avec au minimum :

- `schema_version`, `record_id`, `created_at_utc` ;
- `hypothesis_id`, `family`, `parent_hypothesis_id` ;
- `stage` dans `DISCOVERY`, `TOURNAMENT`, `EXPLOIT`, `FREEZE`, `REJECTED`, `BLOCKED` ;
- `mechanism`, `data_surfaces`, `temporal_operator`, `conditioning`, `prediction_target`, `execution_translation` ;
- `change_class` dans `NEW_MECHANISM`, `REPRESENTATION`, `MODEL`, `EXECUTION`, `PARAMETER_ONLY` ;
- `rationale`, `falsification_test`, `source_refs` ;
- `experiment_ids`, `scientific_signatures`, `trial_count` ;
- `verdict`, `economic_progress`, `notes`.

Les champs semantiques sont des descriptions de recherche ; aucune valeur du ledger ne peut certifier un PnL.

### 4.2 Score de nouveaute

La nouveaute est deterministic et calculable localement, sans embeddings distants. Une hypothese est decrite par six axes :

1. mecanisme economique ;
2. surfaces de donnees ;
3. operateur temporel ;
4. conditionnement/regime ;
5. cible predite ;
6. traduction d'execution.

`novelty_score(candidate, history)` retourne un score dans `[0, 1]` egal a la distance minimale du candidat aux hypotheses deja evaluees. Les champs ensemblistes utilisent une distance de Jaccard ; les champs categoriels utilisent 0 si identiques, 1 sinon. La moyenne ponderee donne la distance finale. Le mecanisme et les surfaces de donnees recoivent le poids le plus eleve afin qu'un simple changement de seuil ne paraisse jamais nouveau.

Le module expose aussi `semantic_fingerprint(record)` pour dedupliquer les hypotheses structurellement identiques.

Le score n'est pas une gate economique. Il sert a allouer le budget d'exploration et a rendre la redondance visible.

### 4.3 Regle anti-boucle

`rediscovery_required(history, hypothesis_id)` retourne vrai lorsque les deux dernieres iterations comparables d'une meme lignee sont `PARAMETER_ONLY` et n'apportent pas de progression economique, ou lorsque deux evaluations consecutives concluent que le headroom net reste non positif / que le mecanisme est rejete.

Quand la comparaison economique n'est pas fiable ou que les donnees/splits ne sont pas comparables, l'absence de preuve de progression ne doit pas etre transformee en faux progres. Le verdict peut rester `BLOCKED`/`MORE_DATA`, mais Codex ne doit pas continuer a retuner par defaut.

### 4.4 Cycle Discovery

Au debut d'un cycle ou apres `rediscovery_required=true`, Codex doit proposer au moins huit hypotheses structurellement distinctes avant un gros run. Elles peuvent provenir du repo, de nouvelles combinaisons de donnees ou d'une recherche externe ciblee.

La recherche externe devient proactive mais bornee : une passe Exa/Parallel Search/GitHub/Consensus peut etre faite au debut d'un cycle Discovery, puis les idees doivent etre converties en hypotheses locales falsifiables. Les outils ne restent pas dans la boucle de calcul.

Le tournament classe les hypotheses sur :

- nouveaute ;
- plausibilite causale ;
- disponibilite des donnees ;
- horizon exploitable ;
- headroom apres couts ;
- gain d'information attendu ;
- cout de falsification.

Le tournament ne selectionne pas uniquement le meilleur backtest brut.

### 4.5 Cycle Exploit

Les survivants utilisent les runners existants. Un `BATCH_SPEC.json` peut contenir de nombreux essais sans round-trip LLM. Les resultats restent lies a `hypothesis_id` et a leurs signatures scientifiques.

`tools/codex_quant_batch.py` doit inclure `family`, `hypothesis_id`, `phase` et `trials` dans son resume compact lorsque ces informations sont disponibles afin de permettre une mise a jour fiable du ledger sans rouvrir tous les artefacts.

### 4.6 CLI locale

Ajouter `tools/codex_hypothesis_ledger.py` avec commandes :

- `register <json>` : valider et ajouter une hypothese ;
- `score <json>` : calculer nouveaute et doublons sans ecrire ;
- `status [--family ...]` : produire un resume compact JSON ;
- `needs-rediscovery <hypothesis_id>` : verdict machine de stagnation.

Toutes les commandes sont locales, read/write uniquement sous `runtime/codex_research/` par defaut, sans reseau et sans ordre.

## 5. Modifications des instructions Codex

Mettre a jour `.agents/skills/alina-quant-research/SKILL.md` et `docs/CODEX_GOAL_RUNBOOK.md` pour rendre obligatoire :

- la distinction DISCOVERY/EXPLOIT ;
- >=8 hypotheses orthogonales lors d'un cycle Discovery ;
- le ledger et le score de nouveaute ;
- le tournament avant gros budget ;
- l'anti-boucle apres deux retunings cosmetiques sans progres ;
- la recherche externe proactive mais ciblee au debut d'un cycle ;
- le retour immediat au calcul local ;
- l'interdiction de confondre accuracy/R2/IC avec profit executable.

`AGENTS.md` doit rester compact. N'y ajouter qu'une courte reference au moteur V3, sans dupliquer le runbook.

## 6. Pistes de recherche autorisees, non obligatoires

Le systeme doit rester libre de trouver d'autres idees. Les familles suivantes sont des exemples d'espaces encore riches :

- wallet informativeness / toxicite / anticipation cross-venue ;
- interaction wallet x etat L2 x order flow ;
- lead-lag asynchrone et price discovery ;
- OFI/microprice multi-horizon et representations stationnaires ;
- spillovers cross-asset et reseaux de causalite ;
- Hawkes/VAR/VECM/transfer-entropy si les donnees et l'horizon les rendent pertinents ;
- regimes de liquidite, volatilite, OI, liquidations et micro-saisonnalite ;
- combinaisons simples/non-lineaires uniquement si elles ajoutent une valeur OOS apres couts.

Ces pistes ne sont jamais des preuves en elles-memes.

## 7. Discipline scientifique

Tous les essais distincts restent comptabilises. Un search ledger plus riche augmente la necessite de corrections multiple-testing, pas l'inverse. Le systeme conserve DSR/PSR/PBO, CPCV/CSCV, bootstrap/permutations/placebos lorsque pertinents, et surtout la separation temporelle/no-lookahead.

Une validation/OOS/forward observee puis utilisee pour retuner cesse d'etre une preuve fraiche. Refreeze puis nouvelle preuve disjointe obligatoire.

## 8. Securite

Inchange : `READ-ONLY-MAINNET · LOCAL-DECISION · PAPER-ONLY · DENY-BY-DEFAULT`.

Aucun ordre reel, argent reel, cle/seed/signature, depot/retrait, mainnet/testnet execution. La logique de discovery ne peut jamais baisser une gate de securite ou de preuve pour creer un PASS.

## 9. Tests attendus

Tests unitaires pour validation du schema, append-only, fingerprint, doublons, bornes du score, invariance a l'ordre des ensembles, distinction parameter-only vs nouveau mecanisme, anti-boucle et filtrage par famille.

Tests d'integration pour le CLI et pour l'enrichissement du `BATCH_SUMMARY.json`.

Tests de contrat docs pour verifier que le runbook/skill mentionnent explicitement Discovery, ledger, >=8 hypotheses, anti-boucle, agent unique et +4 USD NET/jour.

## 10. Definition de Done V3

V3 est implementation-done lorsque les tests cibles sont verts, que le ledger/CLI fonctionne localement, que le batch summary expose les liaisons d'hypothese necessaires, que skill/runbook/AGENTS guident Codex vers Discovery -> Tournament -> Exploit -> Rediscovery, et que les gates de securite existantes ne sont pas affaiblies.

Cela ne signifie pas que l'objectif economique est atteint. La mission economique reste terminee uniquement lorsque `python tools/run_daily_economic_certification.py .` certifie les trois familles a >= +4.00 USD NET/jour chacune sur le meme SHA avec la preuve requise.
