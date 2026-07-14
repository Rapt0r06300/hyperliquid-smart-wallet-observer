# Audit PnL — moteur GRINDER

## Verdict : **LE GRINDER NE TRADE PAS.**

| | |
|---|---|
| trades GRINDER dans la session analysée | **0** |
| PnL GRINDER | **n/a** |

Le moteur Grinder (market making, funding delta-neutre, arbitrage, grid) **n'a produit aucun
aller-retour**. Tout le PnL observé provient du copy-trading (SNIPER).

## Pourquoi il ne trade pas

Le Grinder n'existe pas comme moteur séparé. Ses stratégies (`funding_delta_neutral_paper`,
`ws_price_discrepancy_paper`, `triangular_paper_detection`) **émettent bien des ordres paper**, mais
ceux-ci ne sont matérialisés que si le flag A/B `HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION`
est actif — **et il est absent des launchers**.

> **Le Grinder est branché sur un interrupteur éteint.**

## Ce que la mesure dit quand même (et qui le concerne directement)

Sur les trades qui ont eu lieu :

| | par trade (notionnel 500 $) |
|---|---|
| mouvement brut moyen | **−3,6 bps** |
| frais | **+13,0 bps** |

**Les frais représentent 83 % de la perte nette.** C'est *exactement* la pathologie du Grinder
décrite dans le brief : *le signal ne perd presque rien, les frais mangent tout.*

Cela permet de poser le seuil de viabilité du Grinder **avant même qu'il ne trade** :

| exécution | frais aller-retour | edge brut minimum requis |
|---|---|---|
| **taker** | 9,0 bps (2 × 4,5) | > 9 bps + spread + slippage ≈ **> 20 bps** |
| **maker** (Post-Only) | 3,0 bps (2 × 1,5) | > 3 bps + sélection adverse ≈ **> 8-10 bps** |

> ⚠️ Le modèle croyait jusqu'ici que le maker **rapportait** 1 bps. C'était faux (corrigé).
> Sans cette correction, toute validation de la piste « maker-first » aurait été **une illusion**.

## Prérequis avant toute expérience Grinder

Les pistes 24 à 28, 34 à 37 et 44 à 48 (spread dynamique, profondeur, microprice, OFI,
probabilité de fill, maker vs taker) exigent **le carnet L2** — que le bot **n'enregistrait pas**.
L'enregistrement est désormais câblé et **s'activera au prochain lancement**.

**Verdict : `DATA_MISSING`. Aucune expérience Grinder n'est honnêtement testable aujourd'hui.**

---
*Aucune promesse de PnL. Simulation paper uniquement.*
