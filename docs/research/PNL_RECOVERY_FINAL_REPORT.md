# Rapport final — récupération du PnL

**2026-07-11.** Ce rapport ne promet aucun PnL positif. Il dit ce qui a été mesuré, ce qui a été
corrigé, ce que je me suis trompé à affirmer, et ce qui reste hors de portée.

---

## 1. Les deux moteurs n'existaient pas

Ton brief part du principe que le bot a deux moteurs. **Vérification faite : c'était faux.**

Le mot « sniper » n'apparaissait **nulle part** dans le moteur — seulement dans une ligne de
JavaScript du dashboard qui devinait le mode d'après le nom de la stratégie, **côté navigateur** :

```js
return (m.indexOf('FUNDING')>=0 || m.indexOf('ARBITRAGE')>=0 || ...)?'GRINDER':'SNIPER';
```

Aucun champ `strategy_mode`. Aucun moteur séparé. **Tous les trades passaient par le même chemin.**
C'est pour cela que tous les audits précédents mélangeaient les deux : *il n'y avait rien à séparer.*

Ta piste n° 11 n'était donc pas une amélioration parmi cent — **c'était le prérequis de tout le
reste.** Elle est faite : le moteur est posé **à la source**, sur chaque entrée et chaque sortie.

---

## 2. Le Grinder ne trade pas — deux causes

**A. Il était éteint.** Les flags `HYPERSMART_FUNDING_ARB_PAPER` et le poller n'existaient que dans
`LANCER_HYPERSMART.cmd`. Or **le `.ps1` est l'autorité**. Lancé directement, le Grinder était
purement et simplement éteint — et personne ne le voyait. → **corrigé.**

**B. Un seuil peut-être mort.** Le funding-arb exige **2,5 bps de funding par heure**. Le
commentaire du code le trahit : *« ~20 bps/8h (repo 32) »*. Le repo d'origine visait une place où
le funding tombe **toutes les 8 heures**. Hyperliquid paie **toutes les heures**.

Si le funding horaire réel reste loin sous 2,5 bps, c'est un **verrou mort** — zéro trade garanti,
la signature exacte du plafond de dégradation à 12 bps posé sous un coût plancher de 14,2.

> **Je n'ai pas pu le mesurer** (pas de réseau depuis mon environnement). **Donc je n'ai rien
> changé.** Baisser un seuil sans la donnée serait exactement la faute que je reproche au code.
> → outil livré : `python tools/measure_funding_gate.py`

---

## 3. Ce que j'avais annoncé, et qui était FAUX

Je t'avais dit : *« les frais d'entrée ne sont déduits nulle part — bug comptable »*.

**C'était faux.** Le prix d'entrée stocké **est** le prix de fill (`paper_engine.py` le déclare :
`fill_price_includes_spread_slippage_fee_latency`). Le coût d'entrée est **déjà dans le prix**.
Le code le savait : la réconciliation passait déjà `fees_paid_usdc=0.0`, *« pour ne pas les
soustraire deux fois »*.

**C'est mon outil qui les comptait deux fois**, et qui **noircissait** ton PnL de 0,50 $ sur 10
trades. *Noircir un PnL est aussi malhonnête que le flatter.*

Idem pour les « 7 positions jamais fermées » : le serveur **tourne**, ce sont des positions
**ouvertes**, pas des orphelines.

> **Après correction : écart de réconciliation 0,0013 $, zéro anomalie comptable.**
> **Ton ledger était juste.** C'est l'audit qui inventait des bugs.

*(Et ce n'est pas ma première : j'ai aussi cru mesurer « +35 bps d'edge » en soustrayant une moyenne
calculée **sur la période testée** — du lookahead. Rétracté à l'époque, mentionné ici parce qu'une
erreur qu'on cache recommence.)*

---

## 4. La perte de 64 $ était ARITHMÉTIQUE

Le facteur de volatilité rabotait le take-profit à **28 bps**, pour un stop à **126 bps** et un coût
aller-retour de **13 bps** :

| | |
|---|---|
| ce qu'on garde en gagnant | 28 − 13 = **15 bps** |
| ce qu'on paie en perdant | 126 + 13 = **139 bps** |
| **winrate d'équilibre** | 139 / (139 + 15) = **90 %** |

**Aucune stratégie ne fait 90 %. La perte était garantie avant le premier trade.**

Et le **stop catastrophique ne fermait rien** : deux trades (ARB, ZEC) valent **46 % de toute la
perte**.

**Config actuelle : breakeven 43 %** (54 % au pire cas de volatilité) → **VIABLE**. Un test lit
désormais le **vrai launcher** : si un futur réglage recrée un mur, **les tests tombent avant que le
bot ne le découvre en perdant de l'argent.**

---

## 5. Ce qui reste vrai, et qu'aucun réglage ne changera

**Le copy-trading n'a pas d'edge.** Mesuré sur 24 133 signaux réels, hors échantillon : après
l'ordre d'une whale, le prix bouge de **~0 bps** (bruit : 50-100). **Même à coût ZÉRO : −7,97 bps.**

Ni TP/SL, ni horizon, ni filtre, ni hedge, ni l'inversion du signal n'y changent quoi que ce soit.
Les ~30 % de la perte dus aux bugs sont corrigés. **Les 70 % restants sont l'absence d'edge, et elle
est incompressible.**

C'est pourquoi la §7 (mieux choisir les wallets) est probablement une impasse : **si le signal n'a
pas d'edge, mieux choisir la source du signal n'en crée pas.** Je préfère te le dire maintenant que
te livrer dix modules qui n'y changeront rien.

---

## 6. Ce qui a été livré

| fichier | rôle |
|---|---|
| `strategies/strategy_mode.py` | attribution GRINDER/SNIPER, posée **à la source** |
| `strategies/engine_pnl.py` | **deux PnL séparés** — un moteur inactif est *nommé*, pas absent en silence |
| `strategies/engine_economics.py` | **une config peut-elle gagner ?** — l'arithmétique avant le signal |
| `risk/engine_risk_budget.py` | **un moteur qui saigne ne tue pas l'autre** |
| `risk/directional_exposure.py` | le bot empilait **9 shorts = 250 % du capital dans un seul sens** |
| `collection/microstructure_recorder.py` | carnet L2 + funding — **débloque 40 pistes** |
| `tools/analyze_trading_pnl.py` | audit forensique, lecture seule |
| `tools/measure_funding_gate.py` | le seuil du Grinder est-il mort ? — **à lancer sur ta machine** |

**~70 tests neufs.** Sécurité : **VERT 7/7**.

---

## 7. Ce que tu dois faire, dans cet ordre

1. **Relancer** (`LANCER_HYPERSMART.cmd`). Rien de neuf n'est actif avant. Au démarrage :
   `strategy_mode` posé, PnL séparé par moteur, budgets par moteur, Grinder allumé, **carnet L2 et
   funding enregistrés**.
2. **`python tools/measure_funding_gate.py`** → verdict sur le seuil du Grinder.
3. Laisser **collecter**. C'est le vrai goulot : **40 des 100 pistes attendent uniquement de la
   donnée**, pas du code.

---

## 8. La phrase que je ne dirai pas

Je ne te dirai pas que le PnL va devenir positif.

Ce qui a été fait : le PnL **dit la vérité**, les deux moteurs sont **séparables**, une config
perdante par construction est **détectée avant de perdre**, et un moteur ne peut plus **saigner à
l'abri d'un autre**. C'est un système sur lequel on peut enfin mesurer quelque chose.

Le copy-trading, lui, n'a pas d'edge — et je ne vais pas te vendre l'inverse.

---

*Simulation paper uniquement. **0 ordre réel, 0 argent réel, 0 clé privée, 0 signature,
0 dépôt/retrait.***
