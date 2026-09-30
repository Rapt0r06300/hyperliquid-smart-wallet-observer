# ARBITRAGE DE DISLOCATION — AUDIT DU COÛT ET DU SEUIL (2026-07-21)

> Statut : **`POSITIVE_BEFORE_COSTS_ONLY`**.
> Données : `data/reports/dislocation_opportunities.csv` (369 écarts ≥ 5 bps),
> `data/reports/dislocation_cost_calibration.json`.

## 1. D'où vient le seuil, et pourquoi il a changé

| date | seuil | coûts supposés | erreur |
|---|---|---|---|
| jusqu'au 20/07 | 35 bps | **22 bps** | supposait **4 jambes** (aller-retour × 2 venues) |
| depuis le 21/07 | **15 bps** | **8 bps** | une dislocation se ferme sur **2 jambes** |

La marge de sécurité implicite est donc **7 bps** (15 − 8), pas 13.

## 2. Ce que les 8 bps contiennent réellement — et ce qu'ils NE contiennent pas

`COUT_AR_BPS = 8.0` est un **forfait**, pas une décomposition. Il modélise un aller-retour
maker deux jambes. **Ne sont PAS modélisés séparément** (la mission les exige tous) :

frais Hyperliquid · frais Binance · franchissement de spread HL · franchissement de spread
Binance · slippage HL · slippage Binance · profondeur disponible · risque de jambe ·
partial fill simulé · âge des quotes · latence entre les deux flux · différence de funding ·
marge d'incertitude.

**Conséquence honnête** : le seuil actuel est défendable comme **ordre de grandeur**, pas
comme calibration. Il ne peut pas encore devenir dynamique
(`seuil = coût_estimé + marge`) puisque `coût_estimé` n'est pas décomposé.

## 3. 🔴 Le défaut structurel : les prix ne sont pas exécutables

```python
ecart = (hl_mid − binance_mid) / binance_mid × 1e4
```

**Deux mids.** Aucun `best_bid`, aucun `best_ask`, aucune taille, aucun horodatage
d'échange, aucun âge de quote, aucune santé de source.

Un écart entre deux mids **n'est pas une opportunité** : il ne dit pas à quel prix on
entrerait, ni pour quelle taille, ni si la quote était encore valide. Les 369 opportunités
du CSV sont marquées `prix_executable_mesure = false` — elles sont **théoriques**.

C'est la tâche **P4-1**, et elle doit précéder tout ajustement de seuil.

## 4. La distribution mesurée (912 écarts réels)

| quantile | |écart| |
|---|---:|
| p50 | 3,26 bps |
| p75 | 5,40 bps |
| p90 | **8,65 bps** |
| p95 | 11,80 bps |
| p99 | 71,44 bps |
| max | 71,44 bps |

- **12,68 %** des observations dépassent les 8 bps de coûts ;
- **2,39 %** dépassent le seuil actuel de 15 bps.

Voilà pourquoi le moteur ouvre rarement : ce n'est pas un réglage trop strict, c'est la
**forme de la distribution**.

## 5. La question qui précède toutes les autres : ça converge ?

Mesuré sans aucun seuil ni coût dans le calcul :

| horizon | paires | variation moyenne de \|écart\| | part réduite |
|---|---:|---:|---:|
| 30 min | 74 | **−2,26 bps** | 64,9 % |
| 1 h | 41 | −2,13 bps | 56,1 % |
| 2 h | 7 | −1,95 bps | 57,1 % |

**Verdict : ça converge — mais moins que les 8 bps de coûts.** L'edge net est donc négatif
**en moyenne**. Seuls les écarts extrêmes paient : à 8 bps d'ouverture, 19 entrées, capture
moyenne **8,53 bps**, PnL +0,05 $.

**Décision : ne PAS descendre le seuil à 8 bps.** 19 entrées, c'est une anecdote, pas un
résultat. Réévaluation à ≥ 5 000 écarts (P4-6).

## 6. Fraîcheur : la cadence ×5 n'est pas encore active

Mesuré : intervalle **p50 = 253,8 s**, p95 = 304,2 s. Le passage 300 s → 60 s a été écrit
dans les launchers **mais ne prendra effet qu'au prochain redémarrage** de Flo. Tant qu'il
n'a pas lieu, une dislocation de 20 bps qui dure 3 minutes reste **invisible** — or c'est
exactement celle qu'un arbitrage capture.

## 7. Ordre de travail

1. **P4-1** prix exécutables (best bid/ask, tailles, âge de quote, santé de source) ;
2. **P4-2** décomposition du coût all-in, les 13 postes ci-dessus ;
3. **P4-3** seuil dynamique `coût_estimé + marge` ;
4. **P4-6** réévaluer le niveau du seuil, une fois (1) à (3) faits **et** ≥ 5 000 écarts.

Refus obligatoires à implémenter avec (1) : quote périmée · quotes désynchronisées · venue
dégradée · tailles insuffisantes · contrats non correspondants · jambe non mesurable ·
edge net non positif.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
