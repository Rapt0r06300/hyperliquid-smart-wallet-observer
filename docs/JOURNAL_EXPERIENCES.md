# Journal des expériences — cahier de labo (2026-07-10)

> Index unique de tout ce qui a été testé et construit. Discipline constante : hors-échantillon,
> coûts réels, contrôle aléatoire, critère d'arrêt fixé à l'avance. **Aucune promesse de PnL, aucun
> chiffre maquillé. Read-only, paper-only : 0 ordre réel.**

## A. Études de recherche (verdicts mesurés)

| Étude | Rapport | Verdict |
|---|---|---|
| Copy-trading (smart-money) | ÉTAT_RECHERCHE_HONNETE.md | Pas d'edge net (dégradation ~13 bps) |
| Calibrage 1,4 M scénarios | MEILLEUR_CANDIDAT_REPLAY.md | `robust=0` en OOS |
| Levier fraîcheur / coûts | ANALYSE_REPLAY_LEVIER_REEL.md | Levier = fraîcheur, pas calibrage |
| Entrée maker | MAKER_MODE_RESULT.md | 16 % fill, sélection adverse → négatif |
| Grid / market-making | GRID_MM_RESULT.md | Breakeven calme, catastrophe en tendance |
| Réversion à la moyenne | EXPLORE_MEAN_REVERSION.md | Edge ~0,6 bps, 20× < coûts |
| Scan mécanismes + hasard | EXPLORE_MECHANISM_SCAN.md | Tous perdent ; 0/50 aléatoires positifs |
| Oracle-exit (SL/TP) | (analyse) | Plafond parfait irréalisable ; problème de prédiction |
| Modèle prédictif (ML) | EXPLORE_PREDICTIVE_MODEL.md | Souffle de signal, 15× trop faible + régime shift |
| Validation unifiée | VALID_GATES_REPORT.md | OOS/no-lookahead/gate/plateau/MC |

**Fil rouge, méta-prouvé** : sur ce marché, en retail, la friction dépasse les petits edges.

## B. Toolkit quantitatif construit (pur, testé, réutilisable)

| Module | Contenu | Backlog |
|---|---|---|
| `robustness.py` | bootstrap PnL, maker-adjust, profit factor | (session) |
| `quant_methods.py` | bootstrap blocs, diff fractionnaire, **Sharpe déflaté**, Hurst, entropie | 49,22,26,88,87 |
| `validation_methods.py` | **bootstrap stationnaire**, **PBO/CSCV**, longueur backtest min | 29,23,28 |
| `risk_sizing.py` | Kelly fractionné, vol targeting, VaR/CVaR | 61,62,64 |
| `portfolio_risk.py` | corrélation, drawdown-stop, **risk parity**, plafond expo | 63,65,66,67 |
| `regime_detection.py` | **Kalman**, GARCH, **CUSUM** change-point | 83,84,82 |
| `execution_models.py` | **micro-prix**, spread effectif, **Almgren-Chriss**, TWAP | 18,20,51,53 |
| `features.py` | vol réalisée, ATR, saisonnalité | 31,32 |
| `cost_model.py` | coûts variables par coin, latence simulée | 47,48 |
| `labeling.py` | triple-barrière, meta-labeling | 24,25 |
| `lookahead_guard.py` | **détecteur anti-triche** (méta-test) | 46 |
| `experiment_harness.py` | **harnais OOS + contrôle aléatoire + gate edge-réel** | 11,12,13 |
| `mechanism_zoo.py`, `mean_reversion.py`, `grid_market_maker.py`, `maker_fill.py`, `edge_predictor.py` | stratégies + prédicteur | (session) |
| `research_recorder.py` | stockage par-process capé (future collecte) | — |

**~32 tâches du backlog exécutées, ~90 tests verts au total.**

## C. Méthodologie (invariante)
Split temporel train/test · no-lookahead (vérifié par `lookahead_guard`) · coûts réels · **contrôle
aléatoire** (le meilleur doit battre le hasard) · Monte-Carlo (bootstrap blocs/stationnaire) · gate
« edge réel » décidé à l'avance · détection de sur-apprentissage (PBO) et de changement de régime.

## D. Ce qui reste
- **Encore constructible (pur)** : corrélation inter-coins, anomalies, spectral, stress-test portefeuille,
  purged-CV, White's Reality Check, stratégies pairs/liquidations/vol-harvesting…
- **Différé — ressource externe requise** : librairies lourdes (transformers, XGBoost, SHAP), infra
  (Kafka, Redis, Prometheus), données externes (on-chain, L2, sentiment), outils (ruff/mypy), et le
  **câblage runtime** (watchdog dans le poller, auto-restart) qui touche le serveur vivant. Ces items
  seront marqués « différé : ressource externe » plutôt que bâclés.

## Sécurité
✅ 0 ordre réel · 0 argent · 0 clé · 0 signature. Tout le toolkit est du calcul pur, hors-ligne.
