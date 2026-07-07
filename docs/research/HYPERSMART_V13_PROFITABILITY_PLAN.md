# HyperSmart V13 — Plan Rentabilité (extraction TOTALE des 14 GitHub → PnL/ROI)

> Décision après ré-analyse des 14 repos. Contraintes : **GRATUIT uniquement** (aucune API
> payante, aucune donnée payante, aucun secret type TAAPI/OpenAI dans le hot-path),
> **paper-only / read-only / 0 ordre réel**, additif (ne casse rien), Hyperliquid runtime.

## Constat n°1 — le trésor est déjà codé, mais DORMANT
Audit câblage hot-path (`routes.py` + `copying/` + `following/`) : la boucle de décision
live n'utilise que le score de base (`realtime_magic_score`). Les modules quant suivants
**existent et sont testés mais ne sont PAS branchés** (0 import hot-path) :

| Module dormant | Repo source | Levier PnL |
| --- | --- | --- |
| `signals/whale_fill_signal.py` | Harrier A1 | entrée FRAÎCHE primaire via fills WS bruts (3–30 s d'avance) → bat le gate de fraîcheur |
| `risk/regime_guard.py` | CloddsBot A2 | resserre/halt en régime volatil (HIGH/EXTREME) → coupe les pertes en chop |
| `edge/bias_model.py` | mlmodelpoly A3 | biais directionnel multi-TF → ne pas copier à contre-tendance |
| `signals/opportunity_ranker.py` | mlmodelpoly/Harrier | classe les candidats, prend les MEILLEURS, pas le bruit |
| `risk/adaptive_sizing.py` | MrFadiAi A3 | sizing selon séries (−20%/perte, +10%/gain) → limite les dégâts |
| `calibration/confidence_buckets.py` + `shadow_promote.py` | CloddsBot A1 / backtesting A4 | promotion calibrée (accuracy par bucket + Brier) |
| `edge/fair_value.py` | mlmodelpoly A2 | valeur de référence + edge buffer |

**→ Câbler ces pépites (shadow d'abord, puis autoritatif) = gros gain PnL, ZÉRO nouveau code, GRATUIT.**

## Constat n°2 — la seule vraie brique manquante : l'IA (modèle appris)
Tout est **déterministe/hand-tuné**. `scikit-learn` n'est pas installé ; il n'existe **aucun
modèle entraîné** sur nos résultats réels. C'est l'« IA » repérée dans les repos
(mlmodelpoly = ML, Polymarket/agents = agents) qu'on n'a pas encore.
`numpy 2.2.6` + `pandas 2.3.3` sont dispo → on fait une **régression logistique pure-numpy
+ calibration (Platt/isotonic)**, entraînée sur NOTRE ledger réel : **0 dépendance nouvelle,
0 coût, 100 % local**. Le modèle prédit `P(trade rentable | features)` et **sélectionne**
les meilleurs trades (moins de trades, plus propres). sklearn = upgrade optionnel plus tard.

## Ce qu'on GARDE (gratuit, paper-only) — par repo
- **01 CloddsBot** : calibration de confiance (buckets), VaR/CVaR + régime vol + stress (paper), lazy-load robuste. *(déjà codé → câbler)*
- **02 Harrier** : whale-fill signal PRIMAIRE, OBI autonome, depth guard, trade floor, circuit breaker. *(câbler whale-fill + depth guard)*
- **03 MrFadiAi** : seuils smart-money exacts (WR≥60 / PnL≥500 / PF≥1.5 / consistency≥70 / one-big-win≤30), sizing par série, loss halts. *(vérifier seuils + câbler sizing/halts)*
- **04 LP tool / 05 PolyWeather** : stabilité signal + snapshot autoritatif + stale-blocked. *(déjà fait)*
- **09 mlmodelpoly** : fair-value prob, bias multi-TF, min-depth veto, max-slices/USD par fenêtre, quality-mode 3 niveaux. *(câbler fair_value+bias ; ajouter min-depth + cap par fenêtre)*
- **11 backtesting** : Brier score, exec modeling profond (queue/maker-rebate/L2), optimisation TPE anti-overfit. *(Brier existe ; approfondir exec modeling ; lancer optimize sur ledger réel)*
- **12 polybot** : replication/similarity scoring + execution-quality (copy_fidelity). *(déjà codé → exposer)*
- **13 Polymarket/agents** : modèles Pydantic stricts (frontière anti-corruption), RAG d'evidence OFFLINE. *(garder offline ; pas d'LLM payant dans le hot-path)*
- **07 Awesome** : labels evidence-based + watchlists. **14 lightweight-charts** : déjà fait.

## Ce qu'on BANNIT / DEFER (inchangé)
BAN : tout ordre réel, clé privée, signature, dépôt/retrait, market-making réel, LLM payant
dans le hot-path, données payantes (TAAPI), arbitrage latence Binance. DEFER : microservices
Java/Kafka/ClickHouse (polybot), orchestration LLM agentique complète, sklearn (optionnel).

## Plan d'exécution (étapes #141→#153)
**Axe A — câbler les pépites dormantes (gratuit, shadow→autoritatif).**
**Axe B — modèle IA local pur-numpy entraîné sur nos données réelles.**
**Axe C — exec modeling + optimisation data-driven + vérif 100 % simulation.**

Règle constante : chaque câblage passe d'abord en **SHADOW** (observé, ne change pas la
décision) puis devient autoritatif via un flag, comme le gate V12. Aucune promesse de PnL ;
on maximise honnêtement la probabilité d'un PnL paper positif réaliste.
