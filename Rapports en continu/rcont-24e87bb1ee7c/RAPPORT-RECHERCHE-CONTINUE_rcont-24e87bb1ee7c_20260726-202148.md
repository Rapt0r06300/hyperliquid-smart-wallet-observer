# RAPPORT — RECHERCHE CONTINUE HYPERSMART (FINAL, paper-only)

## 1. Résumé pour Flo
Aucune piste positive au holdout pour l'instant. 0 à confirmer, 0 rejetées. Recherche honnête, rien de maquillé.

## 2-3. Durée & identité
- durée totale : **0j 00h 02m 30s** (150 s) · run_id `rcont-24e87bb1ee7c` · code_sha `477e26e80318f284`
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
- Portefeuille GLOBAL : une seule equity curve chronologique sur un capital unique ; drawdown non additionné ; equity_curve.jsonl.

## 27. Champions & challengers (registre append-only, gel immuable)
- candidats enregistrés : **0** · dont net>0 : **0** (une amélioration = NOUVEAU candidate_id + version + parent_id, jamais une réécriture)

## 37. Lineage
- data_lineage.jsonl (source→événement→…→PnL→rapport ; PnL sans lignée = NON_AUDITABLE)

## 41-43. Limites & prochaines pistes
- Un run de recherche ne PROUVE rien seul : les prometteuses doivent tenir en forward paper OOS. Renforcer les survivants (familles × horizons × régimes), compléter les DATA_MISSING.

## 44. Reproduction
```
LANCER-RECHERCHE-CONTINUE.cmd start   # meme code_sha 477e26e80318f284
```

## 45. Manifeste
- SHA256_MANIFEST_FINAL.json (écrit en DERNIER, contient ce rapport + tous les results)

---
**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
