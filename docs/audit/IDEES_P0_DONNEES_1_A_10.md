# IDEA-1 → IDEA-10 — Vérité des données et du PnL (P0)

Base : HEAD `fb5a52e`. Paper-only, read-only. Chaque idée est **auditée** (ce qui existait déjà),
**complétée** (ce qui manquait), et **prouvée** par un test nommé.

Suite de tests : `tests/test_idees_p0_donnees.py` (31 tests).

| # | Idée | Existait déjà | Ce qui manquait → livré | Test |
|---|------|---------------|--------------------------|------|
| 1 | Dataset tick-by-tick | `canonical_store` (coin/ts/bid/ask/L2) | **`tools/evenement_canonique.py`** : `SCHEMA_TICK` 26 champs — 3 horloges (exchange/recv/write), source, channel, reconnect_id, tid/oid/hash, latence, gap, duplicate, `data_quality_flags` | `test_idea1_schema_tick_complet_et_trois_horloges`, `test_idea1_champ_absent_reste_none_jamais_zero` |
| 2 | RAW / CANONICAL / DERIVED | — (aucune séparation explicite) | `COUCHES`, `normaliser_tick` travaille sur une **copie** (RAW jamais muté), `marquer_derive` produit une couche à part | `test_idea2_raw_jamais_mute_et_couches_separees`, `test_idea2_derive_refuse_un_evenement_non_canonique` |
| 3 | Data Quality Gate | `realtime/feed_quality.FeedQualityGate` (ready/synchronized) | **`tools/etat_flux.py`** : statuts **nommés** `FEED_WARMING/READY/STALE/GAP/RECOVERY/CORRUPTED` + `peut_consommer` (deny-by-default), y compris après reconnexion | `test_idea3_warming_puis_ready_puis_consommation_autorisee`, `test_idea3_reconnexion_repasse_en_recovery_ou_gap`, `test_idea3_carnet_croise_est_corrompu` |
| 4 | Snapshot vs incremental | `FeedMode`, `is_snapshot`, `INCREMENTAL_BEFORE_SNAPSHOT` ✔ | Préservation du flag dans l'événement canonique ; **le premier tick n'est jamais jeté** | `test_idea4_snapshot_flag_preserve_et_premier_tick_non_jete`, `test_idea4_incremental_avant_snapshot_est_refuse` |
| 5 | Stale/Jitter/Gap/Outlier | `FeedQualityGate` (complet) + `tick_quality_guard` + `data_quality/guards` ✔ | Drapeaux qualité **au niveau de l'événement** (carnet croisé, ts futur, gap seuillé sans faux positif) | `test_idea5_stale_gap_outlier_detectes`, `test_idea5_flags_qualite_sur_evenement_canonique`, `test_idea5_gap_seuil_respecte` |
| 6 | Feed Quality Score | `feed_quality_score` + compteurs bruts | **Taux explicites** : stale/gap/duplicate/reconnect/out_of_order/**snapshot_conflict**_rate ; `None` si 0 événement (jamais un 0 flatteur) ; `quarantaine()` décidée sur les taux | `test_idea6_taux_explicites_et_score`, `test_idea6_taux_inconnu_si_aucun_evenement`, `test_idea6_quarantaine_sur_taux` |
| 7 | Staggered startup | **rien** (`demarrer_tous` lançait tout dans la même ms) | **`tools/demarrage_etale.py`** `plan_demarrage` (décalage + jitter **déterministe** par nom) **CÂBLÉ** dans `superviseur_continue.demarrer_tous` | `test_idea7_demarrages_etales_et_deterministes`, `test_idea7_jitter_desynchronise_les_collecteurs`, `test_idea7_superviseur_etale_reellement_les_demarrages` |
| 8 | Reconnexion intelligente | backoff+jitter (`ws_resilience`, `collection/backoff`) | **`BudgetReconnexions`** : budget par fenêtre glissante (refus explicite `BUDGET_EPUISE`) + **grace period** (connexion stable → backoff remis à zéro) | `test_idea8_backoff_exponentiel_puis_budget_epuise`, `test_idea8_grace_period_remet_le_backoff_a_zero`, `test_idea8_budget_se_libere_apres_la_fenetre` |
| 9 | Dédup forte et **durable** | `stable_event_id` + fenêtre **en mémoire** (perdue au redémarrage) | **`tools/dedup_durable.py`** : journal append-only + snapshot + **archive** (rien n'est supprimé), borné 24/7, **survit au crash** ; `identite_evenement` priorise tid/oid/hash | `test_idea9_identite_stable_et_reproductible`, `test_idea9_dedup_survit_au_crash_et_a_la_reprise`, `test_idea9_dedup_survit_a_la_compaction`, `test_idea9_filtrer_marque_les_doublons_sans_les_perdre`, `test_idea9_dedup_borne_la_memoire` |
| 10 | Operational Reality Journal | **rien** d'unifié | **`tools/journal_operationnel.py`** : les **15 types** exigés, incidents **bloquants** (LEDGER_MISMATCH / PNL_UNTRUSTED / DATA_MISSING → `promotion_interdite`), et **`scenarios_pour_replay()`** qui réinjecte les incidents réels comme stress | `test_idea10_journal_enregistre_les_15_types`, `test_idea10_type_inconnu_refuse`, `test_idea10_incident_bloquant_interdit_la_promotion`, `test_idea10_incidents_reinjectes_en_scenarios_de_replay` |

## Décisions d'ingénierie

- **Aucun doublon** : `FeedQualityGate` (déjà excellent) n'est **pas** réécrit — `etat_flux` le **lit** et en dérive
  les statuts nommés et les taux. Idem `ws_resilience`/`backoff` : `demarrage_etale` ajoute seulement le budget
  et la grace period qui manquaient.
- **Additif** : 5 nouveaux modules + 1 suite de tests. Un seul fichier existant modifié
  (`superviseur_continue.demarrer_tous`), avec `etaler=False` pour retrouver le comportement historique.
- **Deny-by-default** : un champ inconnu vaut `None`, un taux sans échantillon vaut `None` — jamais `0`.
- **Rien n'est supprimé** : dédup et journal **archivent** au lieu d'effacer.

## Limites connues (honnêtes)

- `evenement_canonique` / `dedup_durable` / `journal_operationnel` sont **écrits et testés mais pas encore
  branchés** dans `recherche_continue._maturer_live` (ce fichier porte des modifications locales en cours) :
  statut `PARTIAL_NOT_WIRED` pour le câblage, à faire dans un lot suivant.
- Le câblage IDEA-7 est prouvé par test unitaire avec `dormir` injecté ; **non exécuté sous Windows** par moi.
- IDEA-6 : `snapshot_conflict_rate` s'appuie sur les raisons du gate ; il vaut `None` tant qu'aucun événement
  n'a été observé.

## Sécurité

0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait. Un test transversal
(`test_aucun_module_ne_touche_au_reseau_ni_a_l_exchange`) interdit `/exchange`, `requests`, `websocket`,
`private_key`, `sign(`, `mnemonic` dans les 5 nouveaux modules.
