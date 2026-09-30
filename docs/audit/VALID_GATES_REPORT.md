# VALID-GATES — Rapport unifié de validation (2026-07-10)

> ⚠️ **Aucune promesse de PnL.** Métriques descriptives sur données passées. 0 ordre réel, 0 argent,
> 0 clé, 0 signature. Ce rapport consolide la discipline de validation appliquée au replay/segments.

## 1. Méthodologie appliquée (ce qui EST validé)

- **Hors-échantillon (walk-forward simple).** `scenario_search.temporal_split` coupe les candidats
  par `recorded_at` en train 70 % / test 30 %. Tout classement final est ré-évalué sur le **TEST**
  jamais vu. Un réglage n'est retenu que s'il est net>0 sur train **ET** test.
- **No-lookahead.** `simulate_exit_on_path` n'utilise QUE les marks **postérieurs** à `entry_ts` ;
  `prefilter_candidates` exige au moins un mark postérieur. Aucun accès au futur.
- **Gate de déploiement.** `run_validation_gates` → `DEPLOY_CANDIDATE` seulement si le drawdown
  hors-échantillon reste raisonnable vs le gain. (#1 a été **rejeté** : DD $85 > gain $54.)
- **Plateau (robustesse locale).** `_plateau_flag` vérifie le voisinage : un optimum isolé (pic
  entouré de creux) = sur-apprentissage, rejeté.
- **Coûts réels.** Frais+spread (`cost_bps`) **+ dégradation de copie réelle par candidat** ;
  PnL sur notre notional $500 (marge $50 × levier 10).

## 2. Résultats sur les ~6h de données disponibles

| Analyse | Verdict OOS |
|---|---|
| Replay 1 425 000 scénarios | **robust_count = 0** (aucun ne passe OOS+gate+plateau) |
| Segments (18 tranches × 4 sorties) | **0 tranche positive** en test ; meilleure = edge≥40+frais≤10s → −$8.7 |
| Sensibilité dégradation/fraîcheur | net OOS piloté par la **fraîcheur**, pas le calibrage |

**Conclusion validée :** pas d'edge net robuste dans les signaux **tels qu'observés** (trop tard).
Le « +$328 » était un mirage train-only (écarté par l'OOS). Levier réel = fraîcheur du signal.

## 3. Couvert / Non couvert (honnête)

**Couvert :** OOS temporel · no-lookahead · gate net>0 train&test + drawdown · plateau · coûts réels.

**Partiel :** *régime* — le test est une fenêtre temporelle postérieure (donc un régime marché
différent du train), mais il n'y a **pas** de split multi-régimes explicite (vol haute vs basse).

**Non couvert (gaps assumés) :**
- **Monte-Carlo** : pas de rééchantillonnage bootstrap des séquences de trades → pas d'intervalle
  de confiance sur PnL/profit-factor.
- **Walk-forward multi-fenêtres** : une seule coupe 70/30, pas de fenêtres glissantes successives.

## 4. Prochaines étapes

1. Après un run **propre de 48h** (fixes du 2026-07-10 actifs : fermeture tree-kill, mid-coverage,
   fraîcheur 10 s, WS-first), re-jouer avec **la même discipline OOS**.
2. Si un candidat passe enfin le gate : ajouter **MC bootstrap (≥1000×)** + **split régime**
   (vol haute/basse) **avant** toute promotion.
3. **Ne jamais** promouvoir un réglage sur le seul train. La donnée fraîche est le facteur limitant.
