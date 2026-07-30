# Edge-decay des wallets — la courbe complète (2026-07-30)

## 1. Le résultat qui change la question

| Horizon | n | Markout **brut** | Net après 9 bps | Hit-rate net |
|---:|---:|---:|---:|---:|
| 30 s | 3 886 | **+0,74 bps** | −8,26 | 16,6 % |
| 60 s | 3 886 | **+1,65 bps** | −7,35 | 23,1 % |
| 120 s | 3 813 | **+2,47 bps** | −6,53 | 27,3 % |
| 300 s | 3 869 | **+2,57 bps** | −6,43 | 37,6 % |

**Le markout brut est positif et croissant.** Le hit-rate aussi (16,6 % → 37,6 %). Il y a donc bien un
**signal** dans les fills de ces wallets — ce n'est pas du bruit blanc.

Mais il **plafonne autour de 2,6 bps** à 5 minutes, alors que nos coûts aller-retour sont de 9 bps.

La question n'est donc plus « le copy-wallet a-t-il un edge ? » — il en a un, petit. Elle devient :
**peut-on exécuter sous ~2,6 bps aller-retour ?** Sur Hyperliquid en taker, non : les frais seuls y sont
déjà supérieurs, avant même le spread. C'est un verdict beaucoup plus précis que « copy = mort ».

## 2. Correction d'une mesure que j'avais publiée

Le gate de résolution mesure la cadence médiane du tape : **16 701 ms**.

Conséquence directe : les markouts « à 5 s » que j'ai publiés au commit `1e71c87` **n'étaient pas
mesurables**. Le prix lu à « t+5 s » était en réalité la cotation suivante, jusqu'à 16,7 s plus tard. Le
chiffre de −9,45 bps n'était pas faux par malice, il était **hors résolution**.

Les horizons 100 ms → 10 s sont désormais **refusés et comptés** (`HORIZON_SOUS_LA_CADENCE`), jamais
rabattus sur la cotation suivante. C'est exactement le rôle du gate : m'empêcher, moi, de mesurer ce qui
n'est pas là.

## 3. Ce que cela implique pour la suite

- **Les horizons courts restent inconnus.** 100 ms → 10 s ne sont pas « mauvais » : ils sont **non mesurés**.
  Les trancher exige une bande **BBO/L2 à haute cadence**, pas `allMids`.
- **`allMids` sert au screening, pas à la promotion.** Un mid n'est pas un prix exécutable ; aucun wallet ne
  peut passer CORE sur cette base.
- **Le prochain gain de mesure** est la bande BBO causale sur les coins des wallets — c'est elle qui ouvrira
  la moitié gauche de la courbe.

## 3bis. P4 — mesure exécutable : le verdict est un constat de couverture

Le markout exécutable (achat à l'**ask**, sortie au **bid**) est implémenté et testé. Appliqué aux données
réelles, il ne peut **rien** mesurer :

| Bande | Cadence | Problème |
|---|---:|---|
| `bbo_tape` | 2 ms | sa fenêtre **commence après** le dernier fill des wallets → **0 épisode commun** |
| `bbo_synchro` | 264 ms | ne couvre que les majors → **6 épisodes** seulement, sous le minimum de 20 |
| `allMids` | 16,7 s | couvre 99 coins, mais c'est un **mid** → screening seulement |

**Aucune mesure promouvable n'est possible sur les données actuelles.** Ce n'est pas un résultat de
stratégie, c'est un constat de couverture — et l'écrire vaut mieux que de tirer une courbe de 6 épisodes,
ce qui aurait fabriqué un faux edge.

Ce qu'il faut : une **collecte BBO simultanée** des fills et des carnets, sur les coins que ces wallets
tradent réellement. Aucun besoin d'AWS — un run ciblé suffit.

## 4. Ce qui n'a pas été fait dans ce run

P1 (S3 requester-pays / node non-validating), P3 (TWAP réel), P4 (markout L2 exécutable), P5 (réparation
DESYNC), P6 (tape cross-venue synchronisée), P7 (dYdX), P8 (dette : 101 orphelins / 372 testés-non-branchés /
HS-070→100), P9 (scoreboard multi-stratégies), P10 (recette Windows).

La CI est réparée mais **non déclenchée** : je ne peux pas pousser ni lancer GitHub Actions depuis ce
sandbox. Le premier run vert devra être constaté après un push.

---

`Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.`
