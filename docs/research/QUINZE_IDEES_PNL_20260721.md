# 15 IDÉES POUR LE PnL — recherche + mesure + ce qui a été fait (2026-07-21)

> Recherche : doc officielle Hyperliquid, papier académique MDPI 2026, bots open source
> (HL-Delta, delta_neutral_strategies), DefiLlama. **Puis mesure sur nos propres données.**
> La recherche a fait remonter un défaut qu'on n'avait pas vu.

## Le chiffre qui commande tout

L'aller-retour complet vaut **278 heures de portage** au funding plancher. Décomposition
mesurée sur nos 12 positions :

| coin | coût A/R | dont frais | dont **spread** | break-even corrigé |
|---|---:|---:|---:|---:|
| XPL | 15,9 b | 5,5 | 10,4 | 208 h |
| ETH | 18,6 b | 5,5 | 13,1 | 174 h |
| SOL | 21,8 b | 5,5 | 16,3 | 171 h |
| AVAX | **72,4 b** | 5,5 | **66,9** | 583 h |

**Le spread pèse 3,3× les frais** — corrélation log(liquidité) ↔ coût d'entrée = **−0,590**
sur 215 observations. Optimiser les frais était le mauvais combat.

---

## État des 15 idées

| # | idée | statut | effet mesuré |
|---|---|---|---|
| 1 | **Break-even ignorait la SORTIE** | ✅ **CORRIGÉ** | +88 h sur chaque coin ; 5 coins passent de « viables » à refusés |
| 2 | Plancher de liquidité spot | ✅ **couvert par #1** | le break-even corrigé élimine déjà AZTEC/MON/STABLE/AVAX. Un 2ᵉ garde serait redondant. Motif de refus qui mentait (« < 5k$ » vs seuil réel 2 500 $) corrigé |
| 3 | Trier par break-even à net voisin | ✅ **FAIT** | net arrondi au centième puis départage par break-even |
| 4 | VWAP mesuré à la taille réelle | ⚠️ **à faire** | le VWAP est mesuré sur 500 $ ; l'allocation ouvre jusqu'à ~240 $ de marge × levier |
| 5 | Aligned quote assets (−20 % taker, +50 % rebate) | 📄 **documenté** | doc officielle ; identifier nos paires concernées reste à faire |
| 6 | **Timing du sommet d'heure** | ✅ **CODÉ + BRANCHÉ** | module `carry_timing_reglement` : ouvrir avant / fermer après le règlement. **Un DANGER n'est jamais retardé.** ~1,05 $/an à notre taille |
| 7 | **Qui sort du plancher** | ✅ **CODÉ + BRANCHÉ** | module `funding_hors_plancher` + section 11 du rapport. Journal encore trop jeune (< 24 obs/coin) |
| 8 | Élargir l'univers (20 → ~200 perps) | ⚠️ **à faire** | chaque coin de plus est un billet sur un spike |
| 9 | Funding négatif = revenu inversé | 📄 **impossible sur HL** | HL ne permet pas de shorter le spot → signal cross-venue, déjà noté dans le code |
| 10 | Ratio spot/perp 70/30 (HL-Delta) | ⚠️ **à mesurer** | le backtest carry peut le balayer ; ne pas copier sans mesure |
| 11 | Dérive du hedge non mesurée | ⚠️ **P1-2** | nécessite d'enrichir le schéma de position |
| 12 | Spot compte double pour le palier | 📄 **inatteignable** | Tier 1 = 5 M$ sur 14 j. À 1 000 $ de capital : jamais. Documenté pour ne pas y revenir |
| 13 | **Benchmark HLP** | 🔴 **LOI CORRIGÉE** | notre mesure interne (−0,01 % APR) portait sur une fenêtre trop courte. Donnée publique : **15-30 % APR**. **Notre carry (~12,9 %/an) est DOMINÉ par un dépôt passif** |
| 14 | Papier MDPI : 40 % des meilleures opportunités positives après coûts | ✅ **cohérent** | notre arbitrage mesure la même chose → le seuil doit rester haut |
| 15 | Staking HYPE (5-40 % de rabais) | 🚫 **interdit** | action en argent réel. Modélisé : Bronze = −1,1 bps sur l'A/R = 9 h gagnées, contre 88 h pour #1 |

---

## Ce que #1 a réellement changé

Le break-even testait `funding_cumulé ≥ coût_ENTRÉE`. La fermeture (11 bps, 2 jambes) n'y
entrait pas — **88 heures** au plancher. La porte à 235 h laissait donc passer des positions
dont le vrai break-even atteignait 323 h, pour une vie de 336 h.

**Une position ne rembourse pas quand elle a payé son entrée. Elle rembourse quand elle peut
SORTIR sans perte.**

Le plafond n'est plus une constante choisie : il est **dérivé**. Le funding encaissé sur la
vie entière doit couvrir **k = 1,5 fois** l'aller-retour — parce que le coût est **certain et
payé d'avance** tandis que le revenu est **incertain**. Au plancher, cela donne **248 h**.

| k | plafond dérivé | coins viables |
|---|---:|---:|
| 1,00 | > 336 h | tous (aucune marge) |
| 1,25 | 292 h | 7 |
| **1,50** | **248 h** | **5** (SOL, ETH, BTC, PURR, XPL) |
| 2,00 | 160 h | 0 |

k est un **jugement**, écrit pour être discuté, et balayable par le backtest.

**Régression que j'ai introduite et corrigée** : la porte R3 (base-convergence — le seul PnL
réalisé positif du ledger) comparait la base aux frais d'**entrée**. Avec l'aller-retour, une
base de 20 bps ne couvre plus les 22 bps des deux passages. Le seuil R3 a été porté à
l'aller-retour : on n'entre plus pour une convergence qui, même parfaite, laisserait 2 bps de
perte.

---

## La vérité désagréable (#13)

**Un dépôt passif dans HLP (15-30 % APR public) bat notre carry (~12,9 %/an).**

Nuance qui compte : HLP n'est **pas** delta-neutre — il porte du risque directionnel et de
liquidation, avec des drawdowns de 5-12 %. La comparaison est brutale mais pas parfaitement
égale à risque. Elle reste le test le plus dur, et la loi a été mise à jour de `LIMITE` vers
`REFUTE` : notre stratégie est **dominée** tant qu'elle ne dépasse pas durablement 30 % APR net.

Ce n'est pas une raison d'arrêter — c'est la barre à battre, écrite noir sur blanc.

---

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**

Sources : [HL Fees](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees) ·
[HL Funding](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding) ·
[HL-Delta](https://github.com/cgaspart/HL-Delta) ·
[MDPI 2026](https://www.mdpi.com/2227-7390/14/2/346) ·
[DefiLlama HLP](https://defillama.com/protocol/hyperliquid-hlp)
