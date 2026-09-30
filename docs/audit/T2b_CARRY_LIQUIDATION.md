# T2b / #588 — La jambe perp du carry HYPE peut être **liquidée**

*Mesuré le 2026-07-13, sur 200 jours de bougies horaires HYPE réelles (4 801 relevés) et la doc
officielle Hyperliquid. Simulation paper uniquement — aucun ordre réel.*

## Ce que T2 affirmait, et qui était incomplet

> « LONG spot + SHORT perp, même taille → le prix s'annule. Il ne reste que le funding. »

C'est vrai au niveau du **portefeuille**. C'est **faux au niveau du compte perp**.

Le gain de la jambe spot est en **HYPE**, pas en USDC. Il ne recharge pas la marge du short. Si le
prix monte assez, le compte perp passe sous sa marge de maintenance et **il est liquidé** — pendant
que la jambe spot, elle, est parfaitement en profit.

> *Une couverture qui ne peut pas payer sa propre marge n'est pas une couverture : c'est un pari
> sur le fait que le prix ne bougera pas trop avant la fin.*

## La doc officielle (source d'autorité, lue le 13/07)

`hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations` :

- « The maintenance margin is **half of the initial margin at max leverage** » → `mm = 1/(2·L)`.
  **HYPE : levier max 10x → maintenance 5 %.**
- Liquidation par le carnet : le trader garde le collatéral restant, **pas de frais de clearance**.
- Mais sous **2/3 de la marge de maintenance** → **backstop** par le vault liquidateur, et
  « the maintenance margin **is not returned to the user** ». **Perte sèche.**
- Formule : `liq_price = price − side·margin_available / position_size / (1 − l·side)`.
  Pour un short isolé, cela donne : **`r_liq = (m − mm) / (1 + mm)`** avec `m = marge / notionnel`.

## La mesure

Pire hausse **réellement subie** par un short, toutes les entrées possibles (causal, aucun
lookahead), sur 200 jours de HYPE (prix de 20,60 $ à 76,99 $) :

| durée de détention | pire hausse subie |
|---|---|
| 24 h | **+28,8 %** |
| 7 jours | **+68,1 %** |
| 30 jours | **+95,6 %** |

Le choix qu'on ne peut pas esquiver (détention 30 j) :

| marge `m` | liquidé à | survit ? | rendement brut (sur N) | rendement **réel** (sur N+M) |
|---|---|---|---|---|
| 0,15 | +9,5 % | **NON** | 33,6 bps | 29,2 bps — *jamais encaissé* |
| 0,25 | +19,0 % | **NON** | 33,6 bps | 26,9 bps — *jamais encaissé* |
| 0,35 | +28,6 % | **NON** | 33,6 bps | 24,9 bps — *jamais encaissé* |
| 0,50 | +42,9 % | **NON** | 33,6 bps | 22,4 bps — *jamais encaissé* |
| 0,75 | +66,7 % | **NON** | 33,6 bps | 19,2 bps — *jamais encaissé* |
| 1,00 | +90,5 % | **NON** | 33,6 bps | 16,8 bps — *jamais encaissé* |
| **1,50** | **+138,1 %** | **OUI** | 33,6 bps | **13,4 bps** |

**Le tampon et le rendement tirent en sens inverse. On ne peut pas avoir les deux.**

## 🔴 Le coût que personne n'avait compté : le capital immobilisé

Un carry delta-neutre immobilise **deux** poches :

```
capital total = N (le spot, payé CASH — il n'y a pas de levier sur le spot)
              + M (la marge du perp)
```

T2 calculait son rendement sur **N seul**. Le vrai dénominateur est **N + M**.

Pour survivre à la pire hausse réellement observée (+95,6 %), il faut **m = 1,0538** (soit
**105,38 %** du notionnel — *pas* 105 % : à 105,00 % la jambe est liquidée à +95,24 %, juste en
dessous des +95,6 % subis. Mon premier rapport affichait « 105 % » arrondi à l'entier, et j'ai
recopié cet arrondi dans un test, qui a rougi. **L'arrondi d'un rapport n'est pas une entrée de
calcul.**) :

| | |
|---|---|
| spot (payé cash) | 500,00 $ |
| marge du perp | 527,06 $ |
| **capital total** | **1 027,06 $** |

| | |
|---|---|
| rendement annoncé par T2 (sur le notionnel seul) | 33,6 bps / 30 j → **~4,0 % APR** |
| rendement **réel** (sur le capital total) | **16,4 bps / 30 j → ~2,0 % APR** |

## Verdict honnête

**Le carry HYPE n'est pas mort — il est deux fois plus petit qu'annoncé, et il n'est pas sans
risque.**

- Le carry survit **seulement** si on immobilise à peu près autant de marge que de notionnel.
- Ce qui **divise le rendement par deux** : ~2 % APR, pas ~4 %.
- En **backstop**, la marge de maintenance est confisquée : **−25 $ sur 500 $** de notionnel.
- Et surtout : **une jambe perp liquidée = plus de couverture = LONG SPOT SEC**, c'est-à-dire la
  zone morte `FUNDING_JAMBE_NUE`, déjà mesurée (281 bps de bruit de prix subi pour 1 bps encaissé)
  et déjà enterrée.

**Ce qu'il faut ne PAS exagérer :** à la liquidation, le short réalise une perte de `N·r`… mais le
spot a gagné `N·r`. **Le choc en dollars est largement absorbé.** Le carry ne « perd pas tout ».
Les vrais coûts sont : le carry s'arrête, on devient nu, le backstop confisque, et re-couvrir coûte
un aller-retour de plus.

## Ce qui est livré

- `src/hl_observer/funding/carry_liquidation_risk.py` — le chiffrage (pur, deny-by-default).
- `src/hl_observer/funding/delta_neutral_carry.py` — **le verrou est CÂBLÉ** : `evaluer_carry_neutre`
  refuse (`RISQUE_LIQUIDATION_NON_MESURE_NO_TRADE`) tant que le levier max, la marge et la pire
  hausse observée ne sont pas fournis ; et publie désormais le rendement **sur le capital total**.
- `tests/test_carry_liquidation_risk.py` (17 tests) + 2 tests de verrou dans
  `tests/test_delta_neutral_carry.py`.
- `tools/mesurer_risque_liquidation_carry.py` + `MESURER-588.cmd` → `data/reports/carry_liquidation_588.json`.

## Limite restante, nommée

La pire hausse est mesurée sur **200 jours**. Rien ne garantit que le pire est derrière nous — HYPE
a fait ×3,7 sur la période. Un tampon calibré sur le pire passé n'est pas un tampon calibré sur le
pire possible. Le chiffre à retenir n'est pas « m = 1,05 suffit » mais **« il faut ~1× le notionnel
en marge, et le rendement est alors ~2 % APR »**.

*0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.*
