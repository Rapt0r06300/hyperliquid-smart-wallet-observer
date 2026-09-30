# Q2 — L'arbitrage se juge sur des jambes exécutables. Jamais sur le mid.

> Mesuré le 2026-07-13 sur **9 543 carnets réels, 173 marchés**. Code :
> `src/hl_observer/arbitrage/executable_legs.py`. Tests : `tests/test_executable_legs.py`
> (21 verts) + 69 en non-régression. Outil : `Q2-MESURE.cmd`.

## Le mid n'est pas un prix

C'est la moyenne de deux prix qu'on ne peut pas avoir. **On achète à l'ask, on vend au bid.**

Et le détecteur qui tourne **dans le moteur live** (`strategies/fusion_runtime.py:181`,
`refactor_fusion/runner.py:123`) calculait son écart comme ceci :

```python
spread = abs(a.mid - b.mid) / max((a.mid + b.mid) / 2.0, 1e-9) * 10_000.0
```

Deux fautes dans une seule ligne.

**1. Le mid.** `PriceEvent` *porte* le bid et l'ask. Le détecteur les recevait et les jetait pour
en faire une moyenne inexécutable.

**2. `abs()`.** Un arbitrage a une **direction** : on achète quelque part, on vend ailleurs. La
valeur absolue rend le même chiffre dans les deux sens — donc elle « trouve » une opportunité
même quand le seul sens réalisable est perdant.

## Le théorème (exact, pas une marge de prudence)

Pour « acheter sur A, vendre sur B » :

```
edge_mid  = mid_B − mid_A
edge_réel = bid_B − ask_A

edge_mid − edge_réel = (ask_B − bid_B)/2 + (ask_A − bid_A)/2
                     = demi_spread_B + demi_spread_A
```

**Le mid surestime tout arbitrage d'exactement un demi-spread par jambe.** Toujours. C'est une
identité algébrique — vérifiée par **fuzzing sur 2 000 carnets aléatoires** dans
`test_LE_THEOREME_le_mid_surestime_d_un_demi_spread_PAR_JAMBE`.

Le mid ne peut jamais *sous*-estimer un arbitrage. **Il ne se trompe que dans un sens — celui qui
fait trader.**

## 🚩 Le test historique ne passait que parce que le spread était ZÉRO

```python
PriceEvent("hl", "HYPE", 100, 100, 1)     # bid == ask
```

Un carnet qui n'existe pas. Quand `bid == ask`, `mid == bid == ask` : le mid ne ment pas. C'était
le **seul** cas où l'ancien code était juste, et c'est exactement celui qu'on testait.

## De combien le mid ment-il, sur NOS carnets ?

| | |
|---|---|
| demi-spread médian | 0,89 bps → le mid ment de **1,77 bps** (2 jambes) |
| p75 | 2,15 bps → **4,29 bps** |
| p95 | 8,01 bps → **16,03 bps** |
| **p99** | **24,62 bps** → **49,25 bps** |

Le seuil du détecteur est de **20 bps**. Au p99, le mensonge du mid le dépasse **à lui seul**.

Les marchés où le mid aurait inventé de l'arbitrage **à partir de rien** :

| marché | le mid ment de | profondeur médiane |
|---|---|---|
| **HMSTR** | **48,4 bps** | 36 119 $ |
| **PURR** | **42,3 bps** | 535 $ ⚠️ |
| **CASHCAT** | **35,5 bps** | 2 838 $ |
| NOT | 26,1 bps | 27 002 $ |
| BOME | 24,2 bps | 21 589 $ |

CASHCAT est **le marché que T1 avait sorti comme meilleur candidat market-making**. Le même
marché, vu par deux bugs différents, ressort deux fois comme « opportunité ». Ce n'est pas un
hasard : **un spread large fabrique de l'edge dans tous les modèles qui n'exécutent pas.**

## 🔴 Le second bug : la liquidité inventée

`collection/l2_snapshot_cache.py`, ligne 81 :

```python
if remain_usd2 > 0:
    qty += remain_usd2 / float(levels_ask[-1][0])   # SUPPRIMÉE
```

Quand le notionnel demandé dépassait ce que le carnet **visible** contient, cette ligne
prolongeait le dernier niveau **à l'infini, au même prix**. Elle rendait donc un slippage faible
pile dans le cas où le slippage explose : celui du carnet trop mince.

**Un coût sous-estimé exactement quand il compte n'est pas une approximation — c'est un mensonge
orienté.**

Combien de fois s'est-il déclenché ? **19 fois** (0,20 % des carnets). Peu — mais pas zéro, et
concentré : **PURR, 6 fois sur 14 (43 %)**. Ces entrées-là ont été validées contre un coût
fabriqué.

Désormais : profondeur insuffisante → `None` → repli **explicitement marqué**
(`book_costs_used=False`), jamais une validation silencieuse.

## 🔴 Le trou de collecte (trouvé en ouvrant le fichier, pas en le supposant)

`runtime/replay/l2_book*.jsonl` **n'enregistre pas les niveaux**. Seulement un résumé :

```json
{"coin":"BTC","bid":63906.0,"ask":63907.0,"spread_bps":0.156,
 "bid_depth_usd":1764977.7,"ask_depth_usd":543801.9,"bid_size":13.6,"ask_size":7.4}
```

Le walk-the-book **est** fait en direct (`parse_l2book()` reçoit bien les niveaux du WS), mais
l'enregistrement les jette. **Conséquence : on ne pourra jamais ré-auditer après coup le slippage
d'une entrée passée, ni rejouer une décision de carnet.**

C'est le point aveugle d'IMPROVE-07 (« enregistrer le carnet L2 ») : on enregistre *un* carnet,
pas *le* carnet. Noté, pas comblé ici — le combler double la taille du fichier et mérite sa
propre décision.

Détail qui compte : **le top-of-book ne suffit que 68 % du temps** pour 500 $. Dans 32 % des cas
on traverse plusieurs niveaux — donc le slippage est réel, et il est actuellement calculé sans
qu'on puisse le vérifier.

## Ce qui est livré

`arbitrage/executable_legs.py` — module pur, aucune I/O :

- `jambe_executable(niveaux, sens, notional)` → le **VWAP réellement obtenu** en traversant le
  carnet. **N'extrapole jamais** : profondeur insuffisante → `JAMBE_PROFONDEUR_INSUFFISANTE`,
  et `prix_moyen = None` (un prix rendu ici serait un prix inventé).
- `arbitrage_executable(...)` → essaie **les deux sens**, garde le meilleur *exécutable*, et
  porte **aussi** le chiffre du mid + l'écart entre les deux. Raison dédiée
  `ARBITRAGE_VISIBLE_SUR_LE_MID_MAIS_PAS_EXECUTABLE` — c'est ce cas-là qu'il fallait pouvoir
  nommer.
- `surestimation_du_mid_bps(...)` → le théorème, calculable, toujours ≥ 0.

Le détecteur live garde `spread_bps` (le mid) comme **diagnostic**, mais ne déclenche plus que sur
`edge_executable_bps`. Le comparateur cross-source, lui, ne classe plus les venues par mid — car
**le mid le plus bas n'est pas l'ask le plus bas** : une venue au mid serré mais au spread large
peut être plus chère à l'achat qu'une venue au mid plus haut. C'est testé.

## Limite honnête

**On ne collecte pas de carnet CEX.** L'arbitrage cross-venue Hyperliquid↔CEX ne peut donc pas
être mesuré aujourd'hui — seulement rendu *incapable de mentir* le jour où on le mesurera. Les
chiffres ci-dessus mesurent le **mensonge du mid**, pas un edge cross-venue qui n'existe peut-être
pas du tout.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
