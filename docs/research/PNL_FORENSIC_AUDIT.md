# Audit forensique du PnL — reconstruit depuis le ledger

Outil : `python tools/analyze_trading_pnl.py` (lecture seule, n'ecrit que dans `data/reports/`).
Sortie : `data/reports/trades_enriched.csv|json`, `pnl_forensics.json`, `grinder_vs_sniper.csv`.

## Session analysee (en cours au moment de l'audit)

| | |
|---|---|
| evenements lus | 704 |
| aller-retours reconstruits | 10 |
| PnL net | **-7.81 $** |
| PnL **brut** (le trading seul) | **-1.81 $** |
| frais | **6.50 $** |
| winrate | 20 % |
| profit factor | 0.423 |

## LE RESULTAT CENTRAL

> **Le trading brut ne perd que 1.81 $. Les frais coutent 6.50 $.**
> **Les frais representent 83 % de la perte nette.**

Rapporte au notionnel de 500 $ par trade :

| | par trade |
|---|---|
| mouvement brut moyen | **-3.6 bps** — quasi nul : aucun edge directionnel |
| frais | **+13.0 bps** — le tueur |

C'est exactement le diagnostic pose pour le **Grinder** : *le signal ne perd pas, ce sont les
frais, le spread et le slippage qui mangent chaque petit gain.* Sauf que — voir ci-dessous — le
Grinder ne trade pas.

## Reconciliation (PnL recalcule vs PnL stocke)

Le PnL **brut** se reconcilie a **0,0001 $ pres** : la formule de PnL est **juste**.
L'ecart residuel de **0.0501 $** est **entierement** explique par :

> **BUG COMPTABLE : les frais d'ENTREE (0,05 $/trade) ne sont deduits NULLE PART.**
> `net_stocke = brut - frais de SORTIE` uniquement.
> Ils devraient etre *inclus dans le prix d'entree* (`simulate_execution` renvoie un fill
> "tout compris") — mais le prix d'entree etait celui du **leader**, donc ils n'etaient ni dans le
> prix, ni deduits. Ils disparaissaient. *(Corrige : la latence et les couts sont desormais
> transmis au prix de fill.)*
> ⚠️ **Ne PAS "corriger" en soustrayant `fee_cost_usdc` de l'entree** : une fois le prix de fill
> degrade, ce serait un DOUBLE COMPTAGE.

## Anomalies comptables

{"POSITION_JAMAIS_FERMEE": 7}

## Repartition par moteur

| moteur | trades | PnL net | PnL brut | frais | winrate | PF | duree mediane |
|---|---|---|---|---|---|---|---|
| **SNIPER** | 10 | -7.81 $ | -1.81 $ | 6.50 $ | 20 % | 0.423 | 0.51 h |

---
*Simulation paper uniquement. Aucun ordre reel. Aucune promesse de PnL.*
