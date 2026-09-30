# RAPPORT — RECHERCHE CONTINUE HYPERSMART (FINAL, paper-only)

## 1. Résumé pour Flo
Aucune piste positive au holdout pour l'instant. 0 à confirmer, 0 rejetées. Recherche honnête, rien de maquillé.

## 2-3. Durée & identité
- durée totale : **0j 00h 03m 39s** (220 s) · run_id `rcont-920207626a10` · code_sha `5ab242d19ca89a30`
- cycles terminés : **1** · campagnes : **1**
## 4. Sécurité
- read_only=True · real_execution=False · **0 ordre réel · 0 clé · 0 signature · 0 dépôt/retrait**

## 5-6. Sources & couverture
- sources détectées **0** · parsées **0** · exclues **0** · events utilisés **0**

## 8-16. Totaux recherche
| métrique | valeur |
|---|---:|
| FAST_SCREEN | 0 |
| EXACT_REPLAY | 0 |
| survivants | 0 |
| forward paper events | 0 |
| PASS forward | 0 |

## 17. Pistes les plus intéressantes (exploratoire ≠ validé)
| candidate_id | coin | horizon | holdout net bps | PnL$/trade | ROI immob % | statut | campagne |
|---|---|---:|---:|---:|---:|---|---|
| — | — | — | — | — | — | aucune | — |

## 18-19. KILL & DATA_MISSING
- rejetées : **0** · à confirmer/DATA_MISSING : **0** (raisons dans rejected_candidates.csv)

## 20-21. Signaux refusés & effet des gates

## 22-25. Matrices (voir CSV)
- horizon_matrix.csv · regime_matrix.csv · pnl_by_coin.csv

## 26. Réconciliation PnL / ROI / equity / drawdown (reconstruite depuis les ledgers d'événements)
- capital initial **1000.0 $** · PnL réalisé **0.0 $** · equity **1000.0 $** · drawdown **0.0 $** · ROI total **0.0%** · ROI déployé **0.0%**
- campagnes **1** · verdicts **0** · PASS forward **0** · equity curve : results/equity_curve.jsonl
- exclusions réelles agrégées : **0** (voir reconciliation.json)
- Portefeuille GLOBAL : une seule equity curve chronologique sur un capital unique ; drawdown non additionné ; equity_curve.jsonl. `coherent` = ledger reconstruit vs snapshot persistant (None si aucun portefeuille global).

## 27. Champions & challengers (registre append-only, gel immuable)
- candidats enregistrés : **0** · dont net>0 : **0** (une amélioration = NOUVEAU candidate_id + version + parent_id, jamais une réécriture)

## 28. Architecture (chaîne PROD-TRUTH)
- ingestion incrémentale (curseurs) → CanonicalStore (maturation PENDING→READY PAR HORIZON) → discovery → validation → holdout historique → **gel (freeze_exchange_ts)** → PRÉ-FORWARD (archive, post-gel) → FORWARD LIVE (registre_candidats_live : épisodes du CanonicalStore APRÈS le gel) → portefeuille GLOBAL persistant → réconciliation ledger↔snapshot. Prix exécutables ask→bid, coûts complets.

## 29. Outils d'optimisation réellement utilisés
- disponibles : **3** · lancés : **3** · avec vrais trials : **3**
  - grid : dispo=True lancé=True trials_terminés=6 prunés=0 échoués=0 cpu=0.2602s
  - random : dispo=True lancé=True trials_terminés=8 prunés=0 échoués=0 cpu=0.3749s
  - qmc : dispo=True lancé=True trials_terminés=8 prunés=0 échoués=0 cpu=0.3633s
  - tpe : dispo=False lancé=False trials_terminés=0 prunés=0 échoués=0 cpu=0.0s [optuna non installe]
  - cma_es : dispo=False lancé=False trials_terminés=0 prunés=0 échoués=0 cpu=0.0s [optuna non installe]
  - nsga2 : dispo=False lancé=False trials_terminés=0 prunés=0 échoués=0 cpu=0.0s [optuna non installe]
  - successive_halving : dispo=False lancé=False trials_terminés=0 prunés=0 échoués=0 cpu=0.0s [optuna non installe]
  - hyperband : dispo=False lancé=False trials_terminés=0 prunés=0 échoués=0 cpu=0.0s [optuna non installe]

## 30. Robustesse des pistes (plateau de PARAMÈTRES, concentration, capacité)
- aucune piste prometteuse (honnête).

## 31. Travail de fond (aucun idle)
- jobs exécutés : **9** · DONE : **8** · bloqués faute de données : **1** (stress/placebos/WF/LOCO/LORO/voisins/revalidation)

## 37. Lineage
- data_lineage.jsonl (source→événement→…→PnL→rapport ; PnL sans lignée = NON_AUDITABLE)

## 41-43. Limites & prochaines pistes
- Un run de recherche ne PROUVE rien seul : les prometteuses doivent tenir en forward paper OOS. Renforcer les survivants (familles × horizons × régimes), compléter les DATA_MISSING.

## 44. Reproduction
```
LANCER-RECHERCHE-CONTINUE.cmd start   # meme code_sha 5ab242d19ca89a30
```

## 45. Manifeste
- SHA256_MANIFEST_FINAL.json (écrit en DERNIER, contient ce rapport + tous les results)

---
**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
