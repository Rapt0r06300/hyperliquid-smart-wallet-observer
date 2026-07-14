# Q1 — L'edge brut vient d'une table MESURÉE. Jamais d'une formule.

> Décidé et mesuré le 2026-07-13. La vérité est dans le code
> (`src/hl_observer/edge/measured_edge_table.py`, `edge_source.py`) et dans les tests
> (`tests/test_measured_edge_table.py`, `tests/test_edge_source_q1.py`). **Un document ment sans
> bruit ; un test, non.**

## Le problème, en deux lignes de code

```python
# opportunities/fresh_opportunity.py:342
return 14.0 + score*0.55 + wallets*9.0 + notional/25_000 + tightness*10.0

# copy_wallet/wallet_mirror_runtime.py:144
expected_edge = 24.0 + score*24.0 + copyability*18.0
```

**Onze constantes magiques. Aucune n'a jamais été mesurée.**

Et comme `edge_net = edge_brut − coûts`, un brut inventé rend le net inventé. Tout ce qui suivait
— le seuil d'edge minimum, le gate `EDGE_REMAINING_TOO_LOW`, le RiskEngine — était une
**arithmétique impeccable sur un mensonge**. Le refus « edge insuffisant » ne refusait rien de
réel.

Le correctif #327 avait ajouté un *garde-fou sur ce nombre*. Un garde-fou sur un nombre inventé
garde un nombre inventé.

## Ce qui le remplace

Le seul edge brut honnête : **ce que le prix a réellement fait**, dans le sens du trade, après un
signal du même type.

```
markout = sens × (mid(T+H) − mid(T)) / mid(T) × 10 000
```

Trois disciplines, non négociables :

**1. Borne basse, pas moyenne.** On rend `moyenne − 1,96 × erreur_standard`. Une moyenne de
+50 bps sur des observations très dispersées n'est pas un edge — la borne basse le dit toute
seule, en plongeant sous zéro. Avec `n=1`, l'erreur standard est *infinie* : un coup de chance ne
devient jamais une thèse.

**2. Pas de donnée → pas de trade.** Un bucket sans assez d'échantillons ne rend pas une valeur
par défaut, pas une moyenne globale, pas zéro. Il rend `None`, et l'appelant **refuse**. `None`
(« je ne sais pas ») n'est pas `0.0` (« le prix n'a pas bougé ») : les confondre, c'est fabriquer
de la donnée.

**3. Anti-lookahead dur.** La table porte `construite_jusqu_a_ms`. Interroger un signal
*antérieur* à cette date, c'est lui demander son propre futur. Refus.

## 🚩 La purge des alphas fantômes — la partie que j'ai failli rater

J'avais écrit un test exigeant « aucune cellule à edge positif ». **Il a échoué.** La table
d'entraînement en contient trois — dont BTC, signal < 1 s, score élevé : *n=56, moyenne
+23,1 bps*.

Mon test était mal ciblé. Mais ces trois buckets sont **dangereux** — car la validation
hors-échantillon disait déjà la vérité : sur les signaux de test qu'ils auraient acceptés, le
prix fait **−8,03 bps nets**.

> **Un bucket qui trouve de l'edge sur ses propres données ne prouve rien. C'est la définition du
> sur-ajustement.**

Livrer cette table, c'eût été remplacer une formule *inventée* par une formule *sur-ajustée*. Le
même mensonge, mieux habillé.

Le pipeline **purge** donc : `valider_hors_echantillon()` ne garde que les cellules confirmées sur
des données jamais vues, **avec les statistiques du test**. La table d'entraînement survit à part
(`table_edge_entrainement.json`), pour l'audit — le moteur ne la lit jamais.

## Le résultat, sur les vraies données

| | |
|---|---|
| signaux lus | 273 459 |
| écartés `coin=""` (bug d'avant le 11/07) | 34 556 |
| écartés sans mark à T+60 s (**on n'extrapole pas**) | 215 545 |
| **markouts réels mesurés** | **23 358** |
| train / test (coupe chronologique) | 16 350 / 7 008 |
| cellules d'entraînement | 300 |
| cellules **confirmées** hors échantillon | 57 |
| ... dont à **edge net positif** | **0** |

Sur les 44 signaux de test que la table d'entraînement aurait acceptés : markout réel **+3,97 bps
brut**, soit **−8,03 bps net** après 12 bps de coûts. Winrate 50 %.

**La table livrée n'autorise rien.**

Ce n'est pas une panne. C'est la **troisième confirmation indépendante** — après la preuve OOS du
11/07 (24 133 signaux, −7,97 bps même à coût zéro) et la courbe edge/horizon plate — que **le
copy-trading n'a pas d'edge sur Hyperliquid**.

## Le branchement

`HYPERSMART_EDGE_SOURCE` — porte unique, `src/hl_observer/edge/edge_source.py` :

| valeur | comportement |
|---|---|
| `table` (**défaut**) | l'edge vient de la table mesurée. Pas de cellule → `None` → **NO_TRADE**. |
| `formule` | la vieille formule. **Autorisée** — mais chaque décision est estampillée `fabrique=True` + raison `EDGE_FABRIQUE_FORMULE`, dans le résultat, le journal, le dashboard et l'audit. |
| autre chose | **refus** (deny-by-default : une faute de frappe ne rallume pas le mensonge). |

En mode `table`, la formule n'est **jamais** appelée — pas de repli silencieux. C'est testé.

> **On peut mentir à la machine. On ne se ment plus à soi-même.**

## ⚠️ Ce que ça change concrètement pour le prochain run

**Avec le défaut (`table`), le moteur de copie refusera quasiment toutes les entrées.**

C'est **voulu**, et c'est correct : il n'y a pas d'edge à capturer. Un PnL paper bâti sur
`14 + score×0,55 + …` ne valait rien.

Pour re-trader malgré tout (par exemple pour tester d'autres briques du système), il faut le
demander explicitement :

```
HYPERSMART_EDGE_SOURCE=formule
```

…et chaque décision portera alors la mention **FABRIQUÉE**. Aucun PnL produit dans ce mode ne doit
être présenté comme réaliste.

## Reconstruire la table

```
Q1-TABLE-EDGE.cmd          (Windows, sans pause -> q1_table_edge.txt)
python tools/construire_table_edge.py --horizon-s 60 --min-n 30
```

## Ce qui reste ouvert

- La table ne couvre que la stratégie `COPY`. Les moteurs **arbitrage** et **funding** ont leurs
  propres chemins d'edge — Q2 s'en occupe.
- Horizon unique (60 s). La courbe edge/horizon est plate (mesuré le 11/07), donc peu d'espoir
  ailleurs — mais ça se re-mesure en une commande.
- `min_n=30` est un choix. Plus strict = moins de buckets, plus sûr. Ça se règle.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
