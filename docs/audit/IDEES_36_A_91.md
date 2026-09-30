# IDEA-36 → IDEA-91 — PnL, rigueur, régimes, flux, leaders, exits, provenance, garde-fous

Base : HEAD `b9c2698`. Paper-only, read-only. Suite : `tests/test_idees_36_a_91.py` (**68 tests**).

## Modules livrés

| Module | Idées | Cœur |
|---|---|---|
| `tools/pnl_verite.py` | 36-40 | `scanner_ledger` (toutes les lignes invalides, ligne+offset), `valider_operation` + `appliquer_si_valide` (state intact si refus), `roi_explicite` (3 ROI nommés), `mark_causal`/`valoriser` (latent `None`, jamais 0), `SuiviDrawdown` (intraposition) |
| `tools/rigueur_recherche.py` | 41,42,44,49,50,51,45* | `ETAGES` + `transition_valide` (aucun saut), `promouvable` (FAST_SCREEN jamais), `essais_effectifs` (produit des dimensions), `comparer_benchmarks`, `ablation` (gain **marginal**), `preferer_la_plus_simple`, `sharpe_deflate_simple` (*approximation nommée comme telle) |
| `tools/regimes_marche.py` | 52-55 | Catégories **pré-enregistrées** (sessions, bords, seuils vol/spread/profondeur), `regime_temporel`, `regime_microstructure` (`INCONNU` ≠ « calme »), `specialisations_comme_essais`, `verdict_par_regime` (min_n) |
| `tools/flux_microstructure.py` | 56-60 | `ladder_passive` (paper-only, skew d'inventaire), `risque_inventaire`, `ofi_multi_niveaux` (+ alerte « concentré sur le top »), `confirmation_depletion` (jamais un signal seul), `mid_causal`/`toxicite_flux` (**pas de nearest symétrique**) |
| `tools/leaders_entites.py` | 61-66 | `classer_entite` (MM/infra = non copiables), `copyabilite` point-in-time (critère inconnu = bloquant), `detecter_metaorder` (stade + « trop tard »), `lead_lag_conditionne`, `comparer_cohortes`, `resoudre_conflit` (**aucun signal par défaut**) |
| `tools/exits_risque.py` | 67-70 | `plan_experiences_stops` (chaque famille = un essai), `time_stop`, `reduire_position` (sortie partielle si profondeur), `mae_mfe`, `stop_atteint` (`UNMEASURABLE` sans donnée) |
| `tools/garde_fous_recherche.py` | 71, 78-91 | `sanity_cross_source` (`signal_autorise=False` **toujours**), `manifeste_campagne`, `etat_ingestion` (panne ≠ marché calme), `verrou_synthetique`, explorations P2 (81-85), et les 6 garde-fous Punisher (86-91) |

## Idées déjà couvertes — auditées, non réécrites

| # | Existant | Test d'audit |
|---|---|---|
| 43 | `validation_18h.walk_forward` (purge/embargo) | `test_idea43_walk_forward_existant_applique_un_embargo` (l'embargo retire réellement des points) |
| 46 | `validation_18h.pbo_cscv` | `test_idea46_pbo_existant_sur_variantes_reelles` |
| 47 | `validation_18h.bootstrap_bloc` | `test_idea47_bootstrap_bloc_existant_rend_un_ic` |
| 48 | `validation_18h.placebos` | `test_idea48_placebos_existants` |
| 72-73 | `jobs_continue` (6 états + reprise crash + travail de fond) | `test_idea72_73_scheduler_persistant_et_travail_de_fond` |
| 74 | `progres_live` | `test_idea74_progression_reelle_disponible` |
| 75 | `recherche_continue._sante_et_stall` | `test_idea75_watchdog_de_stall_present` |
| 76 | `dashboard_flow` vue compacte | `test_idea76_dashboard_compact_une_seule_ligne_d_attente` |
| 77 | `finaliser` + `_verifier_manifeste_sha` | `test_idea77_rapport_final_et_manifeste_existent` |

## Garanties notables prouvées par test

- **36** : 2 lignes corrompues ⇒ 2 erreurs localisées (ligne 2 et 4) + promotion interdite.
- **37** : NaN, inf, notional ≤ 0, side ∉ {−1,+1}, fraction > 1 refusés ; **state inchangé** après refus.
- **39** : un mark à t=500 ne valorise **jamais** l'instant t=200.
- **40** : creux **entre deux trades** capté (drawdown 150 alors que les trades ne le montrent pas).
- **42** : `EXACT_REPLAY` exigé — `LARGE_SCREENING` ne promeut pas même avec un bon moteur.
- **50** : `A+B+C` à +0,2 bps marginal ⇒ **A_SUPPRIMER**.
- **60** : un mid à t+5 « plus proche » n'est **jamais** choisi comme état initial à t.
- **66** : deux leaders opposés ⇒ `signal=None`.
- **79** : `n_evenements=0` + erreur scanner ⇒ **ROUGE**, pas « marché calme ».
- **80** : `SYNTHETIC` + `PASS_FORWARD_PAPER` ⇒ violation, verdict corrigé en `SHADOW_SYNTHETIQUE`.
- **86** : 100 WebSockets refusé (limite HL = 10/IP).
- **91** : comparaison **métrique par métrique** ; une métrique absente est signalée, jamais ignorée.

## Limites connues (honnêtes)

- **Statut `PARTIAL_NOT_WIRED`** : ces 7 modules sont écrits et testés mais **pas branchés** dans le pipeline
  du labo continu (fichiers en cours de modification locale). Ce sont des **outils de décision**, pas encore
  des étapes automatiques du run.
- **IDEA-45** : `sharpe_deflate_simple` est une pénalisation grossière `√(2·ln n)`, **explicitement nommée
  approximation** — ce n'est pas le DSR complet (skew/kurtosis) de Bailey & López de Prado. Le DSR réel du
  projet reste dans `validation_18h`/`backtesting`.
- **IDEA-56/57** : la ladder et le risque d'inventaire sont des **modèles simples et lisibles**, pas une
  simulation fidèle de la microstructure Hyperliquid ; la liquidation est explicitement **théorique**.
- **IDEA-61/63** : la classification et la détection de metaorder reposent sur des heuristiques déclarées
  (cadence, ratio maker, durée) — à calibrer sur données réelles avant toute conclusion.
- **IDEA-49/82** : les benchmarks et la comparaison de styles fournissent le **cadre** ; les chiffres
  devront venir de vraies campagnes. Aucun résultat n'est produit ici.
- Rien exécuté sous Windows (sandbox Linux).

## Sécurité

0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait. Le test transversal cible
désormais de **vrais appels** (`requests.get`, `import websocket`, `eth_account`, `/exchange`…) et non des
mots : `verifier_plan_websockets` parle des WebSockets sans jamais en ouvrir un.
