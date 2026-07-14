# Preuve d'absence d'edge en copy-trading — mesure du 2026-07-11

**Ce document existe pour qu'on ne recommence jamais.** Il n'est pas un avis : c'est une mesure,
reproductible, sur les signaux réels enregistrés.

## Le matériau

- **24 133 signaux réels** (candidats enregistrés pendant le run des 9–10 juillet)
- **prix à la seconde** sur les 8 coins où le bot a réellement tradé (SOL, BTC, HYPE, BNB, NEAR,
  ETH, ARB, AVNT) — 16 462 marks
- chaque signal est rejoué sur le **chemin de prix réellement observé**, avec les **coûts réels**
  (dégradation de copie mesurée à l'entrée + aller-retour de sortie)
- **split temporel train / test** : on règle sur la première moitié, on juge sur la seconde

## Le résultat, en une ligne

> **Après un ordre de whale, le prix bouge de −0,7 à +0,8 bps en moyenne — dans un bruit de 50 à
> 100 bps. Le signal ne prédit rien.**

| horizon | mouvement après signal LONG | après signal SHORT |
|---|---|---|
| 1 min | −0,39 bps | +1,26 bps |
| 5 min | +0,80 bps | −0,73 bps |
| 15 min | +0,61 bps | −2,82 bps |

À comparer au **coût de 21 bps** par aller-retour (frais 4 + spread 3 + slippage 5 + sélection
adverse 2 + latence, puis la sortie).

## Tout ce qui a été essayé — et qui échoue

| piste | résultat hors échantillon |
|---|---|
| TP 40 / SL 126 (la config qui tournait) | −34,0 bps · PF 0,09 |
| TP 90 / SL 60 (ratio corrigé) | −30,8 bps · PF 0,16 |
| tenir 1 h, barrières larges | −33,0 bps · PF 0,15 |
| tenir 2 h, sans TP/SL | −41,4 bps · PF 0,10 |
| filtrer par edge ≥ 40 bps | −41,3 bps · PF 0,13 |
| filtrer par fraîcheur ≤ 2 s | −28,0 bps · PF 0,24 |
| consensus ≥ 4 wallets | −19,8 bps · PF 0,39 |
| gros ordres (≥ 10 k$) **et** signal frais | apport +3,7 bps (il en faut 21) |
| **inverser le signal** (faire l'inverse du whale) | −11,6 bps · PF 0,55 |
| couvrir le marché (jambe BTC inverse) | −23,8 bps — la couverture coûte plus qu'elle ne rapporte |
| **coûts ramenés à ZÉRO** | **−7,97 bps** |

**La dernière ligne clôt le débat.** Même en supprimant *tous* les frais, tout le spread, tout le
slippage, l'espérance reste négative. Le problème n'est pas les coûts : **il n'y a rien à
extraire**. Aucun réglage, aucun filtre, aucun modèle — pas même un transformer ou du RL — ne peut
tirer 21 bps d'un signal qui en vaut zéro.

## Un piège dans lequel je suis tombé (à ne pas refaire)

Une première mesure semblait montrer un edge de **+35 bps à 1 h**. C'était **faux** : je
soustrayais « la dérive moyenne du coin sur la fenêtre », donc une information **future**. Du
lookahead. La couverture BTC — elle, réellement implémentable — ne reproduit pas ce gain, ce qui a
révélé l'artefact.

**Règle : toute mesure qui soustrait une moyenne calculée sur la période testée est suspecte.**

## Pourquoi le run a perdu −64 $ (et ce n'était pas de la malchance)

TP 40 bps / SL 126 bps exige **75,9 % de winrate** pour seulement rentrer dans ses frais. Mesuré :
10 TP et 10 SL. `10 × 2 $ − 10 × 6,30 $ = −43 $`, plus les frais → **−64 $**. Arithmétique.

Par ailleurs 73 % des positions étaient SHORT dans un marché qui montait : **97 % de la perte vient
des shorts** (−62,63 $ contre −1,36 $ pour les longs). Ce n'est pas un edge inversé — c'est du
bêta subi, faute de neutralité directionnelle.

## Ce qui reste — les seules pistes crédibles

Le copy-trading essaie de **prédire**. On vient de prouver qu'il n'y a rien à prédire ici. Restent
les stratégies dont l'espérance **ne repose sur aucune prédiction** :

1. **Market making** — on *encaisse* le spread au lieu de le payer.
   Espérance = spread capturé × taux de fill − sélection adverse − inventaire.
2. **Funding delta-neutre** — on encaisse le taux de financement, sans pari directionnel.
   Espérance = funding perçu − coût des deux jambes.
3. **Arbitrage** — on capture un écart *constaté*, pas anticipé.

Ces trois pistes étaient **intestables** : on n'enregistrait ni le carnet, ni le funding.
C'est corrigé (`collection/microstructure_recorder.py`, câblé aux deux pollers qui récupéraient
déjà ces données **et les jetaient**). Zéro appel réseau supplémentaire.

## Prochaine étape

Relancer le bot. Il enregistrera le carnet L2 et le funding. **Alors seulement** on pourra dire si
l'une de ces trois pistes a une espérance positive — avec la même rigueur que ci-dessus, et le même
droit de conclure « non ».

---
*Simulation paper uniquement. Aucun ordre réel, aucun argent réel. Aucune promesse de PnL n'est
faite dans ce document — c'est précisément son objet.*
