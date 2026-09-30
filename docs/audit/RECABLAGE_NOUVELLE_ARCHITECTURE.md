# Ré-câblage vers la nouvelle architecture (2 lanceurs officiels)

Base : HEAD `872dd91`. Paper-only, read-only, 0 réseau dans les tests.

## 1. La nouvelle architecture, telle qu'elle est réellement dans le code

| Lanceur officiel | Point d'entrée réel | Périmètre |
|---|---|---|
| `LANCER_HYPERSMART.cmd` | `tools/start_hypersmart_simulation.ps1` → `python -m hl_observer ui` (port 8794) + `hl_observer.ops.superviseur_collecteurs demarrer-tous core` | Runtime / live : moteur, dashboard, collecteurs `allMids` + `BBO` |
| `ANALYSER_BACKTESTS_REPLAYS.cmd` | `tools/run_backtest_replay_suite.py` (shim 8 lignes) → `hl_observer.ops.historical_analysis_suite` | Backtests, replays, validation temporelle, walk-forward, recherche hors runtime |

**Legacy confirmé, à ne plus étendre** : `LANCER-RECHERCHE-14H.cmd`, `LANCER-RECHERCHE-18H.cmd`,
`LANCER-RECHERCHE-CONTINUE*.cmd` et leur moteur `tools/recherche_continue.py`. Rien n'a été supprimé :
les données, rapports et runs existants restent en place.

## 2. Ce que l'audit a trouvé — et qui change le plan

Codex a **déjà implémenté dans `src/hl_observer/`** une partie des idées de la tasklist. Les
ré-implémenter dans `tools/` aurait créé une 3ᵉ architecture, ce que les règles du projet interdisent.
Vérification faite fichier par fichier :

| Module nouvelle archi | Idées couvertes | Câblé ? (mesuré, pas supposé) |
|---|---|---|
| `collection/tick_dataset.py` | 1 (dataset tick durable, sha256, shards) | ✅ `tools/collecter_bbo.py` |
| `normalization/market_events.py` | 2, 4 (RAW→CANONICAL, horloges, provenance) | ✅ `collecter_bbo.py` + `market_truth/pipeline` |
| `realtime/feed_quality.py` | 3, 5, 6 (gate, stale/gap/outlier, score) | ✅ `collecter_bbo.py`, `decision_engine/local_engine.py`, `noyau_unique.py` |
| `ops/pnl_improvement_lab.py` | 37-40, 49-51 (vérité PnL, train/val/holdout) | ✅ étape `pnl_improvement_lab` de la suite d'analyse |
| `ops/historical_analysis_suite.py` | 43, 46-48, 77 (walk-forward, anti-overfit, rapport) | ✅ appelé par `ANALYSER_BACKTESTS_REPLAYS.cmd` |
| **`market_truth/`** (1 145 l.) | **11, 12-21** (chaîne de vérité, replay exécutable, coûts) | ❌ **zéro appelant de production** |

**Le seul vrai trou : `market_truth/`.** Écrit, testé (`tests/test_market_truth_pipeline.py`), mais
importé par personne en dehors de lui-même. C'est exactement la maladie documentée du projet —
« testé-seulement », 28,6 % des modules (fiche S7). Un module qui n'a pas d'appelant ne protège rien.

Correction d'un diagnostic intermédiaire, pour mémoire : j'avais d'abord classé `pnl_improvement_lab`
comme orphelin car aucun `import` ne le référence. Faux — la suite le lance **en sous-processus**
(`python -m hl_observer.ops.pnl_improvement_lab`). Chercher les imports ne suffit pas quand les
étapes sont des chaînes de commande.

## 3. Ce qui a été fait

### Nouvelle étape `market_truth_replay` (recherche offline → `ANALYSER_BACKTESTS_REPLAYS.cmd`)

`src/hl_observer/ops/market_truth_replay.py` fait tourner la chaîne complète sur les ticks durables
réellement collectés : `canonicalize_tick_record` → `MarketTruthPipeline` → `TruthChain` →
`replay_executable_fill`, puis agrège.

Enregistrée dans `build_stage_plan` (position 4, entre `replay_data_quality` et `ab_exact`), avec
`required_paths=(runtime/data/market_ticks,)` : **sans données, l'étape est `SKIPPED`, jamais en échec**.

**Ce que la sonde mesure** : taux d'exécution, spread réel, slippage de profondeur, coût de latence,
markout, fill ratio — par instrument.

**Ce qu'elle ne mesure pas** : aucun edge, aucun PnL de stratégie. Les intentions sont ancrées sur de
vrais ticks et posées **dans les deux sens (LONG et SHORT)** précisément pour qu'aucun résultat
directionnel ne puisse en sortir. Le rapport JSON porte le champ
`ne_mesure_pas: "aucun edge, aucun PnL de stratégie, aucune performance"`. Un chiffre issu de ce
module ne doit jamais être présenté comme une performance.

### Deny-by-default respecté

| Situation | Sortie |
|---|---|
| Aucun tick durable | `NO_DATA` + raison ; **aucun bloc de coûts, aucun taux à 0 %** |
| Schéma de tick inconnu | compté dans `inventaire.rejets_schema`, jamais ignoré en silence |
| Gate qualité non prêt | `AUCUNE_INTENTION_EXECUTABLE` + médianes à `null` (jamais `0.0`) |

## 4. Preuves — `tests/test_market_truth_replay_stage.py` (12 tests, verts)

| Test | Ce qu'il prouve |
|---|---|
| `test_l_etape_est_enregistree_dans_le_lanceur_analyse` | `market_truth_replay` est dans le plan réel + commande pointant le module |
| `test_l_etape_reste_dans_les_modes_full_et_deep` | présente en standard, `--full` et `--deep` |
| `test_ticks_reels_produisent_des_fills_executables_et_des_couts` | ticks écrits par le **vrai** `TickDatasetWriter` ⇒ fills exécutables + spread mesuré > 0 |
| `test_les_deux_sens_sont_testes_donc_aucun_biais_directionnel` | `{LONG, SHORT}` exactement, nombre pair |
| `test_la_fenetre_de_replay_ne_regarde_jamais_le_passe` | aucun événement antérieur au signal dans la fenêtre |
| `test_l_horizon_borne_reellement_la_fenetre` | horizon court ⇒ strictement moins d'événements |
| `test_sans_donnee_le_statut_est_no_data_et_rien_n_est_fabrique` | pas de métrique inventée |
| `test_qualite_insuffisante_ne_produit_aucun_prix_invente` | médianes `None`, raison `DATA_QUALITY_GATE_NOT_READY` |
| `test_les_shards_gzip_sont_relus` | 10 courants + 10 archivés = 20 |
| `test_securite_aucun_appel_reel` | aucun `/exchange`, `requests`, `websocket`, `eth_account`, `private_key` |

Canaris de Codex mis à jour (ils figent l'inventaire d'étapes) :
`test_historical_analysis_launcher.py` — liste des clés, `len(results)`, `summary.PASSED` : 11 → 12.

Non-régression : `market_truth_pipeline`, `pnl_improvement_lab`, `canonical_market_events`,
`tick_dataset`, `feed_quality_gate`, `feed_quality_reader`, `historical_analysis_launcher` — **50/50** ;
lanceurs + sécurité (`hypersmart_single_launcher`, `launcher_unifie`, `safety_audit`,
`collecteurs_registre`, `superviseur_collecteurs`, `no_real_trade_foundations`,
`launcher_no_background_popups`) — **61/61**.

## 5. Statut honnête du câblage précédent

Le lot WIRING (commit `872dd91`, `tools/cablage_idees.py`) branche 5 hooks dans
`tools/recherche_continue.py` — c'est-à-dire **dans le moteur désormais legacy**. Décision appliquée :

- il n'est **pas supprimé** (il fonctionne, ses tests passent, rien n'est cassé) ;
- il ne recevra **aucune nouvelle fonctionnalité** ;
- les idées qui doivent vivre en production passent désormais par `src/hl_observer/`.

Les 16 modules `tools/` (IDEA-1..91) restent des **outils de recherche appelables**. Ceux dont
l'équivalent existe déjà dans `src/hl_observer/` ne seront pas re-câblés : ce serait une 3ᵉ
implémentation du même concept.

## 6. Limites connues

- **Aucun run Windows.** Je travaille depuis un sandbox Linux : la recette Windows et le double-clic
  sur `ANALYSER_BACKTESTS_REPLAYS.cmd` n'ont **pas** été exécutés par moi. La vérité du projet reste
  Windows.
- **Aucune donnée réelle mesurée.** `runtime/data/market_ticks/` est vide à ce jour : l'étape sera
  `SKIPPED` tant que le collecteur BBO n'aura pas tourné avec la nouvelle archi. Aucun chiffre
  d'exécutabilité réel n'est donc produit ici — seulement la porte pour l'obtenir.
- **La sonde ne cherche pas d'edge.** Elle rend le laboratoire plus dur à tromper ; elle n'augmente
  pas la probabilité d'observer un PnL positif, seulement celle qu'un PnL observé soit vrai.

## 7. Sécurité

0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait · 0 réseau.
`paper_only=True` / `real_execution=False` dans tout le rapport produit.
