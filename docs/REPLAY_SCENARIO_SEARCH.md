# Recherche massive de scénarios sur les données replay (après les 48h)

Objectif : après le run de 48h, essayer des **dizaines de milliers de réglages** sur les
données réellement enregistrées, et trouver le scénario le plus **robuste** — sans se faire
piéger par un gagnant chanceux (overfit).

## Données d'entrée (enregistrées pendant le run)

- `runtime/replay/candidates.jsonl` — chaque candidat évalué (coin, direction, edge, mid,
  timestamp, dégradation de copie, notional leader). **Le coin doit être renseigné** (fix
  2026-07-08 : sans coin, un candidat est inutilisable car on ne peut pas le relier à sa
  courbe de prix).
- `runtime/replay/marks.jsonl` — le chemin des prix réels, coin par coin.

Vérifier vite que le coin est présent (sinon relancer le serveur — le recording n'écrit le
coin qu'après le fix) :
```
python -c "import json;rows=[json.loads(l) for l in open('runtime/replay/candidates.jsonl') if l.strip()];print('avec coin:',sum(1 for r in rows if str(r.get('coin') or '').strip()),'/',len(rows))"
```

## Lancer la recherche

```
python -m hl_observer.backtesting.scenario_search \
    --candidates runtime/replay/candidates.jsonl \
    --marks runtime/replay/marks.jsonl \
    --max-scenarios 30000 --jobs 0 \
    --out runtime/replay/scenario_report.json
```

- `--max-scenarios` : nombre de réglages testés (30000 par défaut ; monte à 100000+ si tu veux).
- `--jobs 0` : utilise tous les cœurs (parallèle).
- `--notional-usd 500` : notre taille réelle (marge $50 × levier 10). Le PnL du rapport est
  sur NOTRE taille, pas celle du leader.

## Espace de scénarios (8 dimensions)

`sl_bps`, `tp_bps`, `trailing_stop_bps`, `trailing_activation_bps`, `breakeven_bps`,
`horizon_min`, `cost_bps`, `min_edge_bps` (filtre d'entrée). Sources : grid structuré +
archétypes de style (trend-follow, triple-barrière, scalp, mean-revert, runner…) + sampler
aléatoire pour la couverture large. Les flags de vetos V26 ne sont **pas** cross-multipliés
ici (explosion combinatoire = overfit) : leur effet se teste séparément via
`python -m hl_observer.backtesting.ab_flag_replay`.

## Fidélité (ce qui rend le replay honnête)

- **Pas de lookahead** : la sortie ne lit que les marks postérieurs à l'entrée.
- **Coûts réels** : fees + spread + **dégradation de copie enregistrée** par candidat.
- **Non-mesurables exclus** : un candidat sans mark après l'entrée est écarté (pas de triche).
- **Anti-overfit** : split temporel train (70 %) / test (30 %), classement sur le
  **hors-échantillon**, et « plateau » (un bon réglage doit avoir de bons voisins).

## Lire le rapport

Champs clés de `scenario_report.json` :
- `robust_count` / `best_robust` : les scénarios fiables (net>0 sur train **et** test, gate OK,
  plateau OK). **Ne considérer que ceux-là.**
- `finalists` : classés par net **out-of-sample** (test), avec PF, winrate, drawdown des deux côtés.

⚠️ Métriques **descriptives** sur le passé enregistré. Un bon score au replay **n'est pas une
promesse** de PnL futur — c'est le meilleur pari possible sur données réelles, pas une garantie.
