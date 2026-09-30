# GRINDER / SNIPER — statut RÉEL, mesuré (2026-07-21)

> Recherche exhaustive de `GRINDER`, `SNIPER`, `SCALP`, `MOMENTUM`, `MEAN_REVERSION`,
> `MICROSTRUCTURE`, `WALLET_CLUSTER`, `FAST_SIGNAL`, `COPY_SIGNAL` dans `src/`, `tools/`,
> `tests/`, `docs/`, les `.cmd` et le dashboard. **Aucune affirmation sans occurrence.**

## Verdict

| Terme | Statut | Ce que c'est RÉELLEMENT |
|---|---|---|
| **SNIPER** | `EXPERIMENTAL` | `src/hl_observer/backtesting/sniper_horizon_curve.py` — un **instrument de mesure**, pas un moteur. Il calcule la courbe edge/horizon (100 ms → 5 min) après le fill d'un leader. CLI : `tools/mesurer_courbe_sniper.py`. Tests : `tests/test_sniper_horizon_curve.py`. **Il ne prend aucune décision et n'ouvre aucune position.** |
| **GRINDER** | `LEGACY` | N'existe comme **aucun module**. Apparaît uniquement comme mot-clé dans `agent/dead_zones_hypersmart.py` (registre des zones mortes) et se rattache à `backtesting/grid_market_maker.py`, lié au market-making **réfuté 0 gagnant sur 29 coins**. Le concept est mort avec T1b. |
| SCALP | `NOT_FOUND` | 0 occurrence |
| MOMENTUM | `NOT_FOUND` | 0 occurrence |
| MEAN_REVERSION | `NOT_FOUND` | 0 occurrence |
| MICROSTRUCTURE | `NOT_FOUND` | 0 occurrence |
| WALLET_CLUSTER | `NOT_FOUND` | 0 occurrence |
| FAST_SIGNAL | `NOT_FOUND` | 0 occurrence |
| COPY_SIGNAL | `NOT_FOUND` | 0 occurrence |

## Preuve par le PnL : aucun ne trade

Le ledger paper (`runtime/data/carry_paper_ledger.jsonl`) contient exactement deux stratégies :

```
('arbitrage', 'OPEN')   1
('carry',    'CLOSE')  42
('carry',    'OPEN')   54
```

**Aucune ligne `grinder`, `sniper`, `scalp` ou assimilée.** Ni PnL séparé, ni position, ni
décision. Toute doc qui les présenterait comme moteurs actifs serait fausse.

## Ce que le Sniper a réellement produit

Sa mesure est à l'origine d'une des **lois** du projet (`docs/LOIS_MESUREES.md`, clé
`latence`) : sur 24 133 signaux, **la courbe edge/horizon est PLATE** — raccourcir l'horizon
ne fait pas remonter l'edge au-dessus de zéro. Edge médian mesuré **à 500 ms : −3,74 bps**
(15 571 observations, hors échantillon).

C'est un résultat de recherche de valeur : il a **fermé** une piste (la course à la latence)
au lieu d'en ouvrir une. L'outil garde sa raison d'être — mesurer à nouveau si les données
changent — mais il ne doit jamais être décrit comme un moteur.

## Décision

1. **Ne pas développer** un moteur « Grinder » : son hypothèse économique (capter le spread)
   est réfutée — le spread médian BTC vaut **0,16 bps** contre **3,0 bps** de coût maker
   aller-retour, soit des frais **10 à 20×** le revenu visé.
2. **Conserver le Sniper comme instrument**, dans `backtesting/`, jamais dans un chemin de
   décision. Le relancer uniquement si la collecte sub-seconde change d'ordre de grandeur.
3. **Aucune spécification de moteur** ne sera écrite pour l'un ou l'autre tant qu'une
   hypothèse économique mesurable et un baseline n'existent pas.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
