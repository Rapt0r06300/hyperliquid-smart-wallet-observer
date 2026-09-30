# IDEA-11 → IDEA-35 — Exécution, microstructure, forward causal, ledger/PnL (P0)

Base : HEAD `81446fe`. Paper-only, read-only. Chaque idée est **auditée**, **complétée** si nécessaire, et
**prouvée** par un test nommé. Suite : `tests/test_idees_p0_execution_ledger.py` (52 tests).

## Ce qui existait déjà (audité, non réécrit)

| # | Idée | Existant vérifié par test |
|---|------|---------------------------|
| 12 | Prix réellement exécutable | `moteur_execution_prod.prix_exit_executable` : long → **BID futur**, short → **ASK futur**, `UNMEASURABLE` si pas de futur, approximation `FWD_MID_MOINS_DEMISPREAD` explicitement nommée |
| 13 | VWAP et profondeur L2 | `moteur_execution_prod.vwap_profondeur` : marche le carnet, `rempli_frac < 1` quand la profondeur manque |

## Ce qui manquait (livré)

| # | Idée | Livré | Test principal |
|---|------|-------|----------------|
| 11 | TruthReconciler | `ledger_verite.TruthReconciler` : recoupe les 10 maillons `CHAINE` par candidat ; divergence PnL ou comptage impossible → **PNL_UNTRUSTED + quarantaine + promotion interdite** ; un seul candidat en quarantaine bloque le global | `test_idea11_divergence_pnl_donne_pnl_untrusted_et_quarantaine` |
| 14 | Fills partiels | `execution_realiste.propager_fill_partiel` : 20 % remplis ⇒ position, marge, coûts, PnL, turnover **tous à 20 %** | `test_idea14_fill_20pct_propage_partout` |
| 15 | Probabilité de fill maker | `probabilite_fill_maker` : le volume sert **d'abord la file devant nous** ; sans reliquat → `NO_FILL` | `test_idea15_no_fill_si_le_volume_ne_depasse_pas_la_file` |
| 16 | Queue position | `position_file` : ajouts/annulations/volume ⇒ `queue_depletion_rate` (None si file vide) | `test_idea16_queue_depletion_rate_mesure` |
| 17 | Adverse selection | `markouts_apres_fill` : 100/250/500 ms, 1 s, 5 s ; horizon sans donnée = **None**, jamais 0 | `test_idea17_markouts_causaux_et_adverse_selection` |
| 18 | Fill rate ≠ qualité | `qualite_fill` : verdicts `FILL_TOXIQUE` / `MAUVAIS_NET` / `OK` | `test_idea18_fill_rate_eleve_mais_toxique_est_refuse` |
| 19 | Coûts complets | `couts_verite.composante` + `additionner_couts` : statuts **KNOWN / NOT_APPLICABLE / UNMEASURABLE**, composante absente = inconnue (**pas gratuite**) ⇒ promotion bloquée | `test_idea19_composante_inconnue_bloque_la_promotion` |
| 20 | Anti-double-comptage | `included_in_price=True` (spread déjà dans le VWAP) ⇒ compté pour info, **jamais re-soustrait** ; chaque composante porte `source` + `methode` | `test_idea20_cout_deja_dans_le_prix_nest_pas_soustrait_deux_fois` |
| 21 | Capacité | `capacite_round_trip` (**jambe la plus restrictive**, inconnue si une jambe manque) + `courbe_capacite_nette` | `test_idea21_capacite_limitee_par_la_jambe_la_plus_restrictive` |
| 22 | Budget de latence | `budget_latence` sur les **7 horodatages** + `percentiles_latence` (p50/p95/p99) + détection de **violation de causalité** | `test_idea22_violation_de_causalite_detectee` |
| 23 | Edge decay | `edge_decay` : courbe + **demi-vie observée** (mesure, pas modèle) | `test_idea23_edge_decay_demi_vie` |
| 24 | Timings d'entrée | `comparer_timings` : un timing sous `min_n` est **NON_CONCLUANT** (50 bps sur 3 essais ne gagne pas) | `test_idea24_timing_avec_trop_peu_d_observations_non_concluant` |
| 25 | Entry quality | `qualite_entree` : spread, distance au mid, **part du spread payée**, coût break-even | `test_idea25_qualite_entree_mesure_spread_et_distance_mid` |
| 26 | Break-even réel | `seuil_break_even` : edge minimal + **win-rate minimal** ; sans gain/perte moyens → `None` (non calculable) | `test_idea26_break_even_win_rate_minimal` |
| 27 | SIGNAL_READY vs EPISODE_MATURED | `forward_causal.ouvrir_signal` **n'accepte aucun paramètre de sortie** (vérifié par introspection) ; `maturer` refuse de fermer avant l'échéance | `test_idea27_open_ne_connait_jamais_la_sortie` |
| 28 | Stateful forward paper | `mode = STATEFUL_FORWARD_PAPER` distinct de `PROSPECTIVE_MATURED_REPLAY` ; OPEN refusé sans prix exécutable | `test_idea28_maturation_a_l_echeance_produit_le_net` |
| 29 | File chronologique globale | `file_chronologique` : clé (ts marché, candidate_id) — **indépendante de l'ordre Python** | `test_idea29_ordre_chronologique_independant_de_l_ordre_python` |
| 30 | Concurrence du capital | `allouer_capital` : le **premier chronologique** sert ; résultat identique après permutation | `test_idea30_resultat_identique_quelle_que_soit_la_permutation` |
| 31 | Pending exits reconstructibles | `SortiesReconstructibles.reconstruire` : fichier corrompu ⇒ **aucune sortie perdue**, reconstruction depuis les positions | `test_idea31_fichier_corrompu_ne_fait_pas_disparaitre_une_sortie` |
| 32 | Sortie non mesurable | `EXIT_UNMEASURABLE` + `DATA_GAP` + politique **pré-enregistrée** (`CONSERVATEUR_PERTE_MAX` par défaut) ; position **jamais supprimée**, politique inconnue refusée | `test_idea32_sortie_non_mesurable_conserve_la_position` |
| 33 | Ledger reproductible | `evenement_ledger` : `event_seq`, `event_id`, `candidate_id`, requested/filled, `fill_fraction` **dérivée** (None sans requested), `price_source`, coûts, `state_version` | `test_idea33_evenement_ledger_complet_et_fill_fraction_derivee` |
| 34 | Crash recovery exact | `rejouer` **idempotent** (`event_seq > depuis_seq`) : rejouer 2× ne double jamais le PnL ; `reprise_apres_crash` n'applique que la queue | `test_idea34_rejeu_idempotent_ne_double_jamais_le_pnl` |
| 35 | Snapshot corrompu | `RECOVERY_REQUIRED` + reconstruction depuis le ledger — le **cash n'est jamais remis à neuf** ; ledger illisible ⇒ `LEDGER_CORRUPTED` avec **ligne + offset**, reconstruction refusée | `test_idea35_snapshot_corrompu_declenche_recovery_et_ne_remet_pas_le_cash_a_neuf` |

## Décisions d'ingénierie

- **Zéro doublon** : `prix_exit_executable` et `vwap_profondeur` ne sont pas réécrits — ils sont **audités par
  test**. Deux de mes tests supposaient une signature (`(px, src, approx)`, `capacity_usd`) : c'est **le test**
  qui a été corrigé, pas le code de production.
- **Deny-by-default partout** : composante de coût absente = `UNMEASURABLE` (bloquante) ; horizon de markout
  sans donnée = `None` ; capacité d'une jambe inconnue = capacité round-trip inconnue.
- **Aucune suppression silencieuse** : sortie non mesurable ⇒ position conservée ; fichier pending corrompu ⇒
  reconstruction ; ligne de ledger invalide ⇒ erreur localisée, pas un `continue`.

## Limites connues (honnêtes)

- Les 4 modules sont **écrits et testés mais pas encore branchés** dans le pipeline du labo continu
  (`recherche_continue` / `pipeline_18h` portent des modifications locales en cours) : statut
  **`PARTIAL_NOT_WIRED`**. Le câblage est le prochain lot naturel.
- `probabilite_fill_maker` est un modèle **simple et explicite** (file FIFO + volume traversant) : il ne
  prétend pas reproduire la microstructure exacte d'Hyperliquid, il rend un `NO_FILL` honnête plutôt qu'un
  fill offert. Calibration empirique = IDEA-16 à approfondir avec des données réelles.
- Rien n'a été exécuté sous Windows (sandbox Linux).

## Sécurité

0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait. Test transversal interdisant
`/exchange`, `requests`, `websocket`, `private_key`, `mnemonic`, `eth_account` dans les 4 modules.
