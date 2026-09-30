# Le Grinder : mesure réelle, et le bug que la mesure a révélé

**2026-07-11.** Tu as lancé `MESURER_SEUIL_FUNDING.cmd`. Voici ce que la donnée dit, et ce qu'elle
m'a fait découvrir en creusant — **bien plus important que le seuil lui-même.**

---

## 1. La mesure : le seuil est quasi-mort (confirmé)

**232 marchés Hyperliquid, funding horaire réel :**

| | |
|---|---|
| médiane | **0,1250 bps/h** |
| 90ᵉ centile | 0,1250 bps/h |
| 99ᵉ centile | 0,6035 bps/h |
| maximum | 6,5472 bps/h (CASHCAT) |
| **seuil du bot** | **2,5000 bps/h** |
| **marchés qui passent** | **1 sur 232 (0,4 %)** |

Le seuil est à **20× la médiane du marché**. Verdict : **QUASI-MORT**.

Et le seul marché qui passe est **CASHCAT** — un meme coin que le gate de liquidité refusera de
toute façon. En pratique : **zéro marché tradable. Le Grinder ne pouvait pas trader.**

**Le soupçon était juste** : le seuil vient d'un repo où le funding tombe **toutes les 8 heures**.
Hyperliquid paie **toutes les heures**. La conversion a produit une barre 20× trop haute.

---

## 2. 🔴 LE VRAI PROBLÈME — et il est bien pire

La logique disait : *« le seuil est mort → baisse-le »*. **Je ne l'ai pas fait. Heureusement.**

En vérifiant l'économie avant de toucher au réglage, j'ai regardé le PnL du funding-arb :

```python
net = funding_encaissé − coûts_entrée − coûts_sortie     # ← AUCUN terme de prix
```

Puis la structure de la position :

```python
class FundingArbPosition:
    receiving_side: str      # UNE seule jambe
    ...                      # pas de jambe de couverture. Pas de prix d'entrée. Rien.
```

### La « paire delta-neutre » n'a qu'UNE JAMBE

Il n'y a **aucune couverture**. Juste un frais forfaitaire (`hedge_venue_extra_bps = 1 bps`) qui
fait **semblant** d'en être une.

C'est donc une **position nue sur un perp** — dont le PnL **ignorait totalement le prix du
sous-jacent**.

### Ce que ça produit

> Short CASHCAT pour encaisser 6,5 bps/h de funding.
> Le coin monte de 5 %.
> **Le modèle affiche un GAIN.** La réalité : **−500 bps.**

Un revenu de funding **sans risque de marché**. Ça n'existe pas. C'était du **PnL fabriqué** —
exactement ce que la règle « aucune donnée fabriquée » interdit.

### Le verrou mort nous a protégés

Si j'avais baissé le seuil en lisant « QUASI-MORT » — ce que la logique appelait — **le Grinder se
serait mis à imprimer des profits fictifs.**

C'est très précisément pour ça qu'on **mesure avant de régler**.

---

## 3. Ce qui a été corrigé

Le PnL compte désormais le prix, de bout en bout :

| | |
|---|---|
| `FundingArbPosition` | mémorise son **prix d'entrée** |
| clôture | `net = funding + **PnL de prix** − coûts` |
| prix inconnu | `price_pnl_unknown: True` + `INSUFFICIENT_DATA` — **on n'invente pas** |
| ledger | crédite le PnL de prix, et trace d'où vient chaque dollar |

**8 tests** verrouillent ça, dont celui qui compte : *un short écrasé par le prix perd de l'argent* —
et un test dédié au **signe**, car une inversion transformerait chaque perte en gain.

**Le seuil, lui, n'a PAS été touché.** On ne rouvre pas une vanne tant que ce qui est derrière n'est
pas honnête.

---

## 4. L'économie, maintenant qu'elle est vraie

Coût d'un aller-retour : **6 bps**. Au funding médian de **0,125 bps/h** :

| funding | heures pour couvrir le coût | verdict |
|---|---|---|
| médiane (0,125 bps/h) | **48 h** | limite (max_hold = 72 h) |
| 99ᵉ centile (0,60 bps/h) | 9,9 h | jouable |
| CASHCAT (6,5 bps/h) | 0,9 h | mais illiquide |

Et la taille de jambe est de **25 $**. Même dans le meilleur cas réaliste, une paire rapporte
**quelques centimes sur plusieurs jours** — tout en portant, désormais visiblement, **un risque de
prix plein**.

> **Sans couverture réelle, le « funding-arb » n'est pas un arbitrage.** C'est un pari directionnel
> qui touche un petit loyer. Il n'y a pas de repas gratuit ici, et je ne vais pas te faire croire
> qu'il y en a un.

---

## 5. Le seul chemin honnête, si tu veux un vrai Grinder

Une **vraie** position delta-neutre a **deux jambes** :

> **long spot + short perp**, sur le **même** actif, **tous les deux sur Hyperliquid**.

Le prix s'annule entre les deux jambes ; il ne reste que le funding. **Là**, l'edge ne dépend
d'aucune prédiction — c'est le seul mécanisme du projet dont on puisse dire ça.

Ce que ça demande : la seconde jambe (spot HL) dans le modèle, et l'historique de funding pour
vérifier que le taux **persiste** assez longtemps pour couvrir 6 bps de coût. **Le bot enregistre
désormais ce funding.** C'est la donnée qui manque, pas le code.

**Ce que je ne ferai pas** : baisser le seuil pour « faire tourner le Grinder ». Ça produirait des
trades, un PnL, une courbe — et rien de tout ça ne serait vrai.

---

*Simulation paper uniquement. **0 ordre réel, 0 argent réel, 0 clé privée, 0 signature,
0 dépôt/retrait.** Aucune promesse de PnL positif.*
