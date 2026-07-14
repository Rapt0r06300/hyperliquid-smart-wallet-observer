# Grid / Market-making "grinder" — résultat MESURÉ + ÉPREUVE DE VÉRITÉ (2026-07-10)

> ⚠️ **Aucune promesse de PnL.** Simulation paper sur vrais prix Hyperliquid enregistrés
> (`grid_market_maker.py`, testé, 5 tests verts). $50/palier. 0 ordre réel.

## Étape 1 — premier regard (fills optimistes, 6h de calme)
Le grid constant grinçait un petit positif (~+$14 sur 15 coins) et la martingale ~+$121. **Mais** ces
chiffres supposaient des **fills parfaits** (remplissage dès que le mid touche) et une fenêtre **sans
tendance**. On a donc durci le test.

## Étape 2 — FILLS RÉALISTES (coût de sélection adverse par fill, cf maker mesuré à 16 %)

| Coût adverse / fill | net (15 coins, 6h) | verdict |
|---|---|---|
| 0 bps (optimiste) | +$0.18 | ~breakeven |
| **2 bps (réaliste)** | **−$2.70** | négatif |
| **5 bps (réaliste)** | **−$7.01** | négatif |
| 8 bps (pessimiste) | −$11.33 | négatif |

→ **Le petit grind ne survit PAS à des remplissages réalistes.** Un grid passif se fait remplir du
mauvais côté (comme le maker), et ça suffit à faire passer le net sous zéro.

## Étape 3 — STRESS-TEST par régime (ce que les 6h de calme n'ont pas), fills réalistes 3 bps

| Régime | Grid constant (net / blow-ups / DD) | Martingale ×2 (net / blow-ups / DD) |
|---|---|---|
| range (calme) | +$3.5 / 0 / $0.9 | +$11.6 / 0 / $2.5 |
| **downtrend** | **−$208 / 21 / $208** | **−$1 898 / 18 / $1 898** |
| flash-crash | −$37.8 / 4 / $46 | −$419.9 / 4 / $422 |
| uptrend | +$18.4 / 0 / $0 | +$18.4 / 0 / $0 |

→ Le grinder grince en marché calme/haussier, mais un **downtrend le détruit** (−$208), et la
**martingale est ~9× pire** (−$1 898 sur la même mise de base). C'est **exactement** le mode d'échec
de passivbot, et pourquoi il a besoin de docs `equity_hard_stop_loss`.

## Verdict honnête (final sur cette piste)

Le grid/market-making **n'est pas un edge gratuit pour nous** : avec des fills réalistes il est
**breakeven au mieux** en marché calme, et il porte un **risque de queue catastrophique** en tendance.
Le beau chiffre de la martingale est un mirage de fenêtre calme — il se paie très cher au premier vrai
mouvement. **Zéro promesse tenue, aucune illusion entretenue.**

Le market-making *peut* marcher pour des acteurs avec de vrais avantages (rebates maker, faible
latence, gestion d'inventaire, couverture) — pas pour un bot paper retail qui subit la sélection
adverse. **On a testé rigoureusement, et la porte se referme honnêtement.**

## Sécurité
✅ 0 ordre réel · 0 argent · 0 clé · 0 signature. Lecture seule, paper-only.
